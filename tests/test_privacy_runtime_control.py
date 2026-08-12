from __future__ import annotations

import base64
import importlib
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from services.shared.privacy import PrivacySettingsUpdate
from services.shared.runtime_settings import PrivacyRuntimeSettings


def _load_main(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("ALCHIMISTA_API_TOKEN", "a" * 32)
    monkeypatch.setenv("PRIVACY_SERVICE_TOKEN", "p" * 32)
    monkeypatch.setenv("PRIVACY_POLICY", "protect_egress")
    monkeypatch.setenv("PRIVACY_DETECTOR", "rizzo_regex")
    monkeypatch.setenv("PRIVACY_VAULT_KEY", base64.urlsafe_b64encode(b"k" * 32).decode("ascii"))
    monkeypatch.setenv("RIZZO_BASE_URL", "http://model")
    monkeypatch.setenv("RIZZO_MODEL_TOKEN", "m" * 32)
    sys.modules.pop("services.privacy_service.main", None)
    return importlib.import_module("services.privacy_service.main")


def _request() -> Request:
    return Request({"type": "http", "headers": [(b"x-privacy-token", b"p" * 32)]})


class FakeDetector:
    def __init__(self, ready: bool):
        self.is_ready = ready

    def ready(self) -> bool:
        return self.is_ready


class FakeStore:
    def __init__(self):
        self.updated = None
        self.active_workspaces: list[str] = []

    def update(self, **kwargs):
        self.updated = kwargs
        return PrivacyRuntimeSettings(
            workspace=kwargs["workspace"],
            privacy_policy=kwargs["privacy_policy"],
            privacy_detector=kwargs["privacy_detector"],
            privacy_mapping_enabled=kwargs["privacy_mapping_enabled"],
        )

    def workspaces_using_detector(self, detector):
        assert detector == "rizzo_http"
        return self.active_workspaces


def test_full_detector_cannot_activate_before_model_ready(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    store = FakeStore()
    monkeypatch.setattr(main, "settings_store", store)
    monkeypatch.setitem(main.detectors, "rizzo_http", FakeDetector(False))
    payload = PrivacySettingsUpdate(
        workspace="default",
        privacy_policy="strict",
        privacy_detector="rizzo_http",
        privacy_mapping_enabled=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        main.update_settings(payload, _request())

    assert exc_info.value.status_code == 409
    assert store.updated is None


def test_ready_full_detector_selection_is_persisted(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    store = FakeStore()
    monkeypatch.setattr(main, "settings_store", store)
    monkeypatch.setitem(main.detectors, "rizzo_http", FakeDetector(True))
    monkeypatch.setattr(main, "_model_request", lambda method, path: {"state": "READY", "loaded": True})
    payload = PrivacySettingsUpdate(
        workspace="matter-a",
        privacy_policy="strict",
        privacy_detector="rizzo_http",
        privacy_mapping_enabled=False,
    )

    response = main.update_settings(payload, _request())

    assert response.privacy_detector.value == "rizzo_http"
    assert store.updated["workspace"] == "matter-a"
    assert store.updated["privacy_mapping_enabled"] is False


def test_active_full_detector_must_switch_before_unload(monkeypatch) -> None:
    main = _load_main(monkeypatch)
    store = FakeStore()
    store.active_workspaces = ["default"]
    monkeypatch.setattr(main, "settings_store", store)

    with pytest.raises(HTTPException) as exc_info:
        main.model_action("unload", _request())

    assert exc_info.value.status_code == 409
