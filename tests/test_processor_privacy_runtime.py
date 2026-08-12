from __future__ import annotations

import importlib
import sys

import pytest

from services.shared.privacy import PrivacyPolicy
from services.shared.runtime_settings import PrivacyRuntimeSettings


def _load_processor(monkeypatch):
    monkeypatch.setenv("ALCHIMISTA_PROFILE", "local")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("ALCHIMISTA_API_TOKEN", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("PRIVACY_POLICY", "off")
    monkeypatch.delenv("PRIVACY_SERVICE_TOKEN", raising=False)
    sys.modules.pop("services.document_processor_service.main", None)
    return importlib.import_module("services.document_processor_service.main")


class _SettingsStore:
    def __init__(self, settings: PrivacyRuntimeSettings) -> None:
        self.settings = settings
        self.workspaces: list[str] = []

    def get(self, workspace: str) -> PrivacyRuntimeSettings:
        self.workspaces.append(workspace)
        return self.settings


class _UnavailableSettingsStore:
    def get(self, workspace: str) -> PrivacyRuntimeSettings:
        raise OSError(f"settings unavailable for {workspace}")


def test_processor_uses_persisted_workspace_policy_without_privacy_client(
    monkeypatch,
) -> None:
    processor = _load_processor(monkeypatch)
    store = _SettingsStore(
        PrivacyRuntimeSettings(
            workspace="matter-a",
            privacy_policy="strict",
            privacy_detector="rizzo_regex",
            privacy_mapping_enabled=False,
        )
    )
    monkeypatch.setattr(processor, "runtime_settings_store", store)
    monkeypatch.setattr(processor, "privacy_client", None)

    policy, mapping_enabled = processor._privacy_runtime("matter-a")

    assert policy == PrivacyPolicy.STRICT
    assert mapping_enabled is False
    assert store.workspaces == ["matter-a"]


def test_processor_never_falls_back_to_global_off_when_settings_are_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PRIVACY_FAIL_CLOSED", "false")
    processor = _load_processor(monkeypatch)
    monkeypatch.setattr(processor, "runtime_settings_store", _UnavailableSettingsStore())

    assert processor.config.privacy_policy == PrivacyPolicy.OFF.value
    assert processor.config.privacy_fail_closed is False
    with pytest.raises(RuntimeError, match="Unable to load workspace privacy settings"):
        processor._privacy_runtime("protected-workspace")
