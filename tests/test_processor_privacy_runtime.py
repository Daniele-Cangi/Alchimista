from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from services.shared.privacy import PrivacyPolicy
from services.shared.runtime_settings import PrivacyRuntimeSettings


def _load_processor(monkeypatch, storage_path: Path):
    monkeypatch.setenv("ALCHIMISTA_PROFILE", "local")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("ALCHIMISTA_API_TOKEN", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_POLICY", "off")
    monkeypatch.delenv("PRIVACY_SERVICE_TOKEN", raising=False)
    sys.modules.pop("services.document_processor_service.main", None)
    return importlib.import_module("services.document_processor_service.main")


class _SettingsStore:
    def __init__(self, settings: PrivacyRuntimeSettings) -> None:
        self.settings = settings
        self.workspaces: list[str] = []

    @contextmanager
    def processing_snapshot(self, workspace: str):
        self.workspaces.append(workspace)
        yield self.settings


class _UnavailableSettingsStore:
    @contextmanager
    def processing_snapshot(self, workspace: str):
        raise OSError(f"settings unavailable for {workspace}")
        yield  # pragma: no cover


def test_processor_uses_persisted_workspace_policy_without_privacy_client(
    monkeypatch,
    tmp_path,
) -> None:
    processor = _load_processor(monkeypatch, tmp_path / "objects")
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

    with processor._privacy_runtime("matter-a") as (policy, mapping_enabled):
        assert policy == PrivacyPolicy.STRICT
        assert mapping_enabled is False

    assert store.workspaces == ["matter-a"]


def test_processor_never_falls_back_to_global_off_when_settings_are_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("PRIVACY_FAIL_CLOSED", "false")
    processor = _load_processor(monkeypatch, tmp_path / "objects")
    monkeypatch.setattr(processor, "runtime_settings_store", _UnavailableSettingsStore())

    assert processor.config.privacy_policy == PrivacyPolicy.OFF.value
    assert processor.config.privacy_fail_closed is False
    with pytest.raises(OSError, match="settings unavailable"):
        with processor._privacy_runtime("protected-workspace"):
            pass
