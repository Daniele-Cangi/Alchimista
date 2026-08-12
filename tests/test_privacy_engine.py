import base64
import json
from contextlib import contextmanager

import pytest
from cryptography.exceptions import InvalidTag

from services.privacy_service import engine as engine_module
from services.privacy_service.engine import PrivacyEngine, RizzoHttpDetector, RizzoRegexDetector
from services.privacy_service import vault as vault_module
from services.privacy_service.vault import EncryptedValue, PiiVaultRepository, VaultCipher


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


def test_vault_keyring_decrypts_old_rows_and_encrypts_with_active_key() -> None:
    v1 = base64.urlsafe_b64encode(b"a" * 32).decode("ascii")
    v2 = base64.urlsafe_b64encode(b"b" * 32).decode("ascii")
    old_cipher = VaultCipher.from_base64(v1, "v1")
    old_value = old_cipher.encrypt(
        "alice@example.com",
        tenant="default",
        doc_id="doc-1",
        placeholder="[EMAIL_1]",
    )
    keyring = VaultCipher.from_configuration(
        active_key_version="v2",
        keys_json=json.dumps({"v1": v1, "v2": v2}),
        legacy_key=v1,
        legacy_key_version="v1",
    )

    assert keyring.decrypt(
        old_value,
        tenant="default",
        doc_id="doc-1",
        placeholder="[EMAIL_1]",
    ) == "alice@example.com"
    new_value = keyring.encrypt(
        "bob@example.com",
        tenant="default",
        doc_id="doc-1",
        placeholder="[EMAIL_2]",
    )
    assert new_value.key_version == "v2"
    assert keyring.available_key_versions == frozenset({"v1", "v2"})


def test_vault_keyring_fails_closed_for_unknown_row_version() -> None:
    cipher = _cipher()
    with pytest.raises(ValueError, match="not available"):
        cipher.decrypt(
            EncryptedValue(ciphertext=b"ciphertext", nonce=b"0" * 12, key_version="v0"),
            tenant="default",
            doc_id="doc-1",
            placeholder="[EMAIL_1]",
        )


def test_vault_keyring_accepts_legacy_single_key_configuration() -> None:
    encoded = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    cipher = VaultCipher.from_configuration(
        active_key_version="",
        keys_json="",
        legacy_key=encoded,
        legacy_key_version="v1",
    )
    assert cipher.key_version == "v1"
    assert cipher.available_key_versions == frozenset({"v1"})


def test_vault_keyring_requires_active_version_to_exist() -> None:
    encoded = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
    with pytest.raises(ValueError, match="not present"):
        VaultCipher.from_configuration(
            active_key_version="v2",
            keys_json=json.dumps({"v1": encoded}),
            legacy_key="",
            legacy_key_version="v1",
        )


def test_vault_repository_reports_stored_versions_missing_from_keyring(monkeypatch) -> None:
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query):
            assert "SELECT DISTINCT key_version" in query

        def fetchall(self):
            return [{"key_version": "v1"}, {"key_version": "retired"}]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    @contextmanager
    def fake_get_connection(database_url):
        assert database_url == "postgresql://unused"
        yield FakeConnection()

    monkeypatch.setattr(vault_module, "get_connection", fake_get_connection)
    repository = PiiVaultRepository("postgresql://unused", _cipher())

    assert repository.unavailable_key_versions() == ["retired"]


def test_irreversible_mode_never_touches_mapping_vault() -> None:
    class RejectingVault:
        def assert_document_scope(self, **kwargs):
            raise AssertionError("irreversible mode must not validate document scope")

        def load_value_placeholders(self, **kwargs):
            raise AssertionError("irreversible mode must not load mappings")

        def store(self, **kwargs):
            raise AssertionError("irreversible mode must not store mappings")

    engine = PrivacyEngine(detector=RizzoRegexDetector(), cipher=_cipher(), vault=RejectingVault())
    result = engine.protect(
        text="alice@example.com",
        tenant="default",
        doc_id="doc-1",
        replace=True,
        reversible=False,
        persist_mapping=False,
    )
    assert result.protected_text == "[EMAIL_1]"


def test_reversible_mapping_requires_existing_tenant_document_scope() -> None:
    class MissingDocumentVault:
        def assert_document_scope(self, **kwargs):
            raise ValueError("Reversible mapping requires an existing document in the same tenant")

        def load_value_placeholders(self, **kwargs):
            raise AssertionError("missing document must fail before loading mappings")

        def store(self, **kwargs):
            raise AssertionError("missing document must fail before storing mappings")

    engine = PrivacyEngine(detector=RizzoRegexDetector(), cipher=_cipher(), vault=MissingDocumentVault())
    with pytest.raises(ValueError, match="existing document"):
        engine.protect(
            text="alice@example.com",
            tenant="default",
            doc_id="missing",
            replace=True,
            reversible=True,
            persist_mapping=True,
        )


def test_full_detector_health_uses_internal_model_token(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        captured["token"] = request.get_header("X-model-token")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(engine_module, "urlopen", fake_urlopen)
    detector = RizzoHttpDetector("http://model", timeout_seconds=20, token="model-secret")

    assert detector.ready() is True
    assert captured == {"token": "model-secret", "timeout": 10}


def test_full_detector_chunks_transport_and_preserves_global_offsets(monkeypatch) -> None:
    payload_lengths: list[int] = []
    marker = "ALICE"

    class Response:
        status = 200

        def __init__(self, payload: dict):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert timeout == 20
        payload = json.loads(request.data.decode("utf-8"))
        text = payload["text"]
        payload_lengths.append(len(text))
        segments = []
        cursor = 0
        while True:
            index = text.find(marker, cursor)
            if index < 0:
                break
            if index > cursor:
                segments.append({"t": text[cursor:index]})
            segments.append(
                {"t": marker, "label": "FULLNAME", "score": 0.98, "src": "modello"}
            )
            cursor = index + len(marker)
        if cursor < len(text):
            segments.append({"t": text[cursor:]})
        return Response({"segments": segments})

    monkeypatch.setattr(engine_module, "urlopen", fake_urlopen)
    detector = RizzoHttpDetector(
        "http://model",
        timeout_seconds=20,
        token="model-secret",
        max_request_chars=16,
        overlap_chars=8,
    )
    text = "0123456789ALICE---0123456789ALICE---tail"

    findings = detector.detect(text)

    assert len(payload_lengths) > 1
    assert max(payload_lengths) <= 16
    assert [(item["start"], item["end"]) for item in findings] == [
        (10, 15),
        (28, 33),
    ]
    assert all(text[item["start"] : item["end"]] == marker for item in findings)


def test_full_detector_empty_input_does_not_call_model(monkeypatch) -> None:
    monkeypatch.setattr(
        engine_module,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("empty input must not be sent to the model service")
        ),
    )

    assert RizzoHttpDetector("http://model").detect("") == []
