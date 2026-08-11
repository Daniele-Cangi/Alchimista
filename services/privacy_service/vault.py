from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.shared.db import get_connection


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes
    key_version: str


class VaultCipher:
    def __init__(self, key: bytes, key_version: str):
        self._initialize({key_version: key}, key_version)

    @classmethod
    def from_base64(cls, value: str, key_version: str) -> "VaultCipher":
        return cls(_decode_key(value), key_version)

    @classmethod
    def from_base64_keyring(
        cls,
        values: Mapping[str, str],
        active_key_version: str,
    ) -> "VaultCipher":
        keys = {version: _decode_key(value) for version, value in values.items()}
        instance = cls.__new__(cls)
        instance._initialize(keys, active_key_version)
        return instance

    @classmethod
    def from_configuration(
        cls,
        *,
        active_key_version: str,
        keys_json: str,
        legacy_key: str,
        legacy_key_version: str,
    ) -> "VaultCipher":
        encoded_keys: dict[str, str] = {}
        if keys_json.strip():
            try:
                parsed = json.loads(keys_json)
            except Exception as exc:
                raise ValueError("PRIVACY_VAULT_KEYS_JSON must be valid JSON") from exc
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("PRIVACY_VAULT_KEYS_JSON must be a non-empty object")
            if not all(
                isinstance(version, str) and isinstance(value, str)
                for version, value in parsed.items()
            ):
                raise ValueError("PRIVACY_VAULT_KEYS_JSON keys and values must be strings")
            encoded_keys.update(parsed)

        if legacy_key:
            legacy_version = legacy_key_version.strip() or "v1"
            configured = encoded_keys.get(legacy_version)
            if configured is not None and configured != legacy_key:
                raise ValueError("Legacy privacy vault key conflicts with keyring entry")
            encoded_keys[legacy_version] = legacy_key

        if not encoded_keys:
            raise ValueError("PRIVACY_VAULT_KEYS_JSON or PRIVACY_VAULT_KEY is required")

        active = active_key_version.strip()
        if not active:
            if legacy_key:
                active = legacy_key_version.strip() or "v1"
            elif len(encoded_keys) == 1:
                active = next(iter(encoded_keys))
            else:
                raise ValueError("PRIVACY_VAULT_ACTIVE_KEY_VERSION is required for a multi-key keyring")
        return cls.from_base64_keyring(encoded_keys, active)

    @property
    def available_key_versions(self) -> frozenset[str]:
        return frozenset(self._keys)

    def _initialize(self, keys: Mapping[str, bytes], active_key_version: str) -> None:
        if not keys:
            raise ValueError("Privacy vault keyring cannot be empty")
        for version, key in keys.items():
            if not version or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version):
                raise ValueError("Privacy vault key versions must use 1-64 safe characters")
            if len(key) != 32:
                raise ValueError("Privacy vault key must decode to exactly 32 bytes")
        if active_key_version not in keys:
            raise ValueError("Active privacy vault key version is not present in the keyring")
        self._keys = dict(keys)
        self._ciphers = {version: AESGCM(key) for version, key in keys.items()}
        self.key_version = active_key_version

    def encrypt(self, value: str, *, tenant: str, doc_id: str, placeholder: str) -> EncryptedValue:
        nonce = os.urandom(12)
        aad = _aad(tenant, doc_id, placeholder, self.key_version)
        ciphertext = self._ciphers[self.key_version].encrypt(nonce, value.encode("utf-8"), aad)
        return EncryptedValue(ciphertext=ciphertext, nonce=nonce, key_version=self.key_version)

    def decrypt(
        self,
        value: EncryptedValue,
        *,
        tenant: str,
        doc_id: str,
        placeholder: str,
    ) -> str:
        cipher = self._ciphers.get(value.key_version)
        if cipher is None:
            raise ValueError("Privacy vault key version is not available")
        aad = _aad(tenant, doc_id, placeholder, value.key_version)
        plaintext = cipher.decrypt(value.nonce, value.ciphertext, aad)
        return plaintext.decode("utf-8")

    def value_hash(self, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value.strip()).casefold()
        active_key = self._keys[self.key_version]
        return hmac.new(active_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


class PiiVaultRepository:
    def __init__(self, database_url: str, cipher: VaultCipher):
        self._database_url = database_url
        self._cipher = cipher

    def assert_document_scope(self, *, tenant: str, doc_id: str) -> None:
        with get_connection(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM documents WHERE doc_id = %s AND tenant = %s",
                    (doc_id, tenant),
                )
                row = cur.fetchone()
        if not row:
            raise ValueError("Reversible mapping requires an existing document in the same tenant")

    def unavailable_key_versions(self) -> list[str]:
        with get_connection(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT key_version FROM pii_vault")
                rows = cur.fetchall()
        stored = {str(row["key_version"]) for row in rows}
        return sorted(stored - self._cipher.available_key_versions)

    def load_value_placeholders(self, *, tenant: str, doc_id: str) -> dict[tuple[str, str], str]:
        with get_connection(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entity_type, placeholder, encrypted_value, nonce, key_version
                    FROM pii_vault
                    WHERE tenant = %s AND doc_id = %s
                    """,
                    (tenant, doc_id),
                )
                rows = cur.fetchall()
        result: dict[tuple[str, str], str] = {}
        for row in rows:
            raw = self._cipher.decrypt(
                EncryptedValue(
                    ciphertext=bytes(row["encrypted_value"]),
                    nonce=bytes(row["nonce"]),
                    key_version=str(row["key_version"]),
                ),
                tenant=tenant,
                doc_id=doc_id,
                placeholder=str(row["placeholder"]),
            )
            result[(str(row["entity_type"]), _normalize(raw))] = str(row["placeholder"])
        return result

    def store(
        self,
        *,
        tenant: str,
        doc_id: str,
        entity_type: str,
        placeholder: str,
        value: str,
        value_hash: str,
    ) -> None:
        encrypted = self._cipher.encrypt(value, tenant=tenant, doc_id=doc_id, placeholder=placeholder)
        with get_connection(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pii_vault (
                      tenant, doc_id, entity_type, placeholder, encrypted_value, nonce,
                      key_version, value_hash, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (tenant, doc_id, placeholder)
                    DO UPDATE SET
                      entity_type = EXCLUDED.entity_type,
                      encrypted_value = EXCLUDED.encrypted_value,
                      nonce = EXCLUDED.nonce,
                      key_version = EXCLUDED.key_version,
                      value_hash = EXCLUDED.value_hash,
                      updated_at = NOW()
                    """,
                    (
                        tenant,
                        doc_id,
                        entity_type,
                        placeholder,
                        encrypted.ciphertext,
                        encrypted.nonce,
                        encrypted.key_version,
                        value_hash,
                    ),
                )
                conn.commit()

    def restore(self, *, tenant: str, doc_id: str, text: str) -> tuple[str, int]:
        placeholders = sorted(set(re.findall(r"\[[A-Z][A-Z0-9_]*_\d+\]", text)))
        if not placeholders:
            return text, 0
        with get_connection(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT placeholder, encrypted_value, nonce, key_version
                    FROM pii_vault
                    WHERE tenant = %s AND doc_id = %s AND placeholder = ANY(%s)
                    """,
                    (tenant, doc_id, placeholders),
                )
                rows = cur.fetchall()
        restored = text
        count = 0
        for row in rows:
            placeholder = str(row["placeholder"])
            value = self._cipher.decrypt(
                EncryptedValue(
                    ciphertext=bytes(row["encrypted_value"]),
                    nonce=bytes(row["nonce"]),
                    key_version=str(row["key_version"]),
                ),
                tenant=tenant,
                doc_id=doc_id,
                placeholder=placeholder,
            )
            occurrences = restored.count(placeholder)
            restored = restored.replace(placeholder, value)
            count += occurrences
        return restored, count


def _aad(tenant: str, doc_id: str, placeholder: str, key_version: str) -> bytes:
    return f"alchimista-pii-vault\x00{tenant}\x00{doc_id}\x00{placeholder}\x00{key_version}".encode("utf-8")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _decode_key(value: str) -> bytes:
    try:
        padded = value + ("=" * ((-len(value)) % 4))
        key = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except Exception as exc:
        raise ValueError("Privacy vault keys must be URL-safe base64") from exc
    if len(key) != 32:
        raise ValueError("Privacy vault key must decode to exactly 32 bytes")
    return key
