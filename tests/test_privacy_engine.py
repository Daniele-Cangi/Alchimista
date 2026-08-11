import base64

import pytest
from cryptography.exceptions import InvalidTag

from services.privacy_service.engine import PrivacyEngine, RizzoRegexDetector
from services.privacy_service.vault import EncryptedValue, VaultCipher


def _cipher(byte: bytes = b"k") -> VaultCipher:
    return VaultCipher.from_base64(base64.urlsafe_b64encode(byte * 32).decode("ascii"), "v1")


def test_repeated_identical_pii_uses_one_type_aware_placeholder() -> None:
    engine = PrivacyEngine(detector=RizzoRegexDetector(), cipher=_cipher(), vault=None)
    text = "Email alice@example.com; ripeti alice@example.com."

    result = engine.protect(
        text=text,
        tenant="default",
        doc_id=None,
        replace=True,
        reversible=False,
        persist_mapping=False,
    )

    assert len(result.findings) == 2
    assert {finding.placeholder for finding in result.findings} == {"[EMAIL_1]"}
    assert result.protected_text.count("[EMAIL_1]") == 2
    assert "alice@example.com" not in result.protected_text


def test_placeholder_collision_is_skipped() -> None:
    engine = PrivacyEngine(detector=RizzoRegexDetector(), cipher=_cipher(), vault=None)
    result = engine.protect(
        text="Existing [EMAIL_1], new alice@example.com",
        tenant="default",
        doc_id=None,
        replace=True,
        reversible=False,
        persist_mapping=False,
    )

    assert result.findings[0].placeholder == "[EMAIL_2]"
    assert "[EMAIL_1]" in result.protected_text


def test_privacy_findings_never_serialize_raw_values() -> None:
    engine = PrivacyEngine(detector=RizzoRegexDetector(), cipher=_cipher(), vault=None)
    result = engine.protect(
        text="alice@example.com",
        tenant="default",
        doc_id=None,
        replace=False,
        reversible=False,
        persist_mapping=False,
    )

    serialized = result.findings[0].model_dump_json()
    assert "alice@example.com" not in serialized
    assert result.findings[0].value_hash


def test_vault_cipher_rejects_wrong_key() -> None:
    first = _cipher(b"a")
    second = _cipher(b"b")
    encrypted = first.encrypt(
        "alice@example.com",
        tenant="default",
        doc_id="doc-1",
        placeholder="[EMAIL_1]",
    )

    with pytest.raises(InvalidTag):
        second.decrypt(
            EncryptedValue(
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_version=encrypted.key_version,
            ),
            tenant="default",
            doc_id="doc-1",
            placeholder="[EMAIL_1]",
        )


def test_vault_key_must_be_256_bits() -> None:
    short = base64.urlsafe_b64encode(b"too-short").decode("ascii")
    with pytest.raises(ValueError, match="32 bytes"):
        VaultCipher.from_base64(short, "v1")
