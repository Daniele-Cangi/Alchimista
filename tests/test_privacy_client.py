from urllib.error import URLError

import pytest

from services.shared import privacy
from services.shared.privacy import PrivacyClient, PrivacyDetectRequest, PrivacyServiceError


def test_privacy_client_rejects_malformed_response(monkeypatch) -> None:
    client = PrivacyClient(base_url="http://privacy", token="token")
    monkeypatch.setattr(client, "_post", lambda path, payload: {"findings": "not-a-list"})

    with pytest.raises(PrivacyServiceError, match="malformed"):
        client.detect(PrivacyDetectRequest(text="alice@example.com"))


def test_privacy_client_reports_unavailable_without_leaking_payload(monkeypatch) -> None:
    client = PrivacyClient(base_url="http://privacy", token="token")
    monkeypatch.setattr(
        privacy,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(URLError("connection refused")),
    )

    with pytest.raises(PrivacyServiceError, match="unavailable") as exc_info:
        client.detect(PrivacyDetectRequest(text="alice@example.com"))

    assert "alice@example.com" not in str(exc_info.value)


def test_privacy_client_reads_workspace_runtime_settings(monkeypatch) -> None:
    client = PrivacyClient(base_url="http://privacy", token="token")
    captured = {}

    def fake_get(path):
        captured["path"] = path
        return {
            "workspace": "matter a",
            "privacy_policy": "strict",
            "privacy_detector": "rizzo_regex",
            "privacy_mapping_enabled": True,
        }

    monkeypatch.setattr(client, "_get", fake_get)
    settings = client.settings("matter a")

    assert captured["path"].endswith("workspace=matter%20a")
    assert settings.privacy_policy.value == "strict"
