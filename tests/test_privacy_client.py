import pytest

from services.shared.privacy import PrivacyClient, PrivacyDetectRequest, PrivacyServiceError


def test_privacy_client_rejects_malformed_response(monkeypatch) -> None:
    client = PrivacyClient(base_url="http://privacy", token="token")
    monkeypatch.setattr(client, "_post", lambda path, payload: {"findings": "not-a-list"})

    with pytest.raises(PrivacyServiceError, match="malformed"):
        client.detect(PrivacyDetectRequest(text="alice@example.com"))
