from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.shared.db import get_connection


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes
    key_version: str


class VaultCipher:
    def __init__(self, key: bytes, key_version: str):
        if len(key) != 32:
            raise ValueError("Privacy vault key must decode to exactly 32 bytes")
        self._key = key
        self._aesgcm = AESGCM(key)
        self.key_version = key_version

    @classmethod
    def from_base64(cls, value: str, key_version: str) -> "VaultCipher":
        try:
            padded = value + ("=" * ((-len(value)) % 4))
            key = base64.urlsafe_b64decode(padded.encode("ascii"))
        except Exception as exc:
            raise ValueError("PRIVACY_VAULT_KEY must be URL-safe base64") from exc
        return cls(key, key_version)

    def encrypt(self, value: str, *, tenant: str, doc_id: str, placeholder: str) -> EncryptedValue:
        nonce = os.urandom(12)
        aad = _aad(tenant, doc_id, placeholder, self.key_version)
        ciphertext = self._aesgcm.encrypt(nonce, value.encode("utf-8"), aad)
        return EncryptedValue(ciphertext=ciphertext, nonce=nonce, key_version=self.key_version)

    def decrypt(
        self,
        value: EncryptedValue,
        *,
        tenant: str,
        doc_id: str,
        placeholder: str,
    ) -> str:
        if value.key_version != self.key_version:
            raise ValueError("Privacy vault key version is not available")
        aad = _aad(tenant, doc_id, placeholder, value.key_version)
        plaintext = self._aesgcm.decrypt(value.nonce, value.ciphertext, aad)
        return plaintext.decode("utf-8")

    def value_hash(self, value: str) -> str:
        normalized = re.sub(r"\s+", " ", value.strip()).casefold()
        return hmac.new(self._key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


class PiiVaultRepository:
    def __init__(self, database_url: str, cipher: VaultCipher):
        self._database_url = database_url
        self._cipher = cipher

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
