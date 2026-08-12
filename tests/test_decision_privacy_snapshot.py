from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path

from services.shared.contracts import AIDecisionIngestRequest
from services.shared.privacy import (
    PrivacyEngineMetadata,
    PrivacyPseudonymizeResponse,
)
from services.shared.runtime_settings import PrivacyRuntimeSettings


def _load_ingestion(monkeypatch, storage_path: Path):
    monkeypatch.setenv("ALCHIMISTA_PROFILE", "local")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("ALCHIMISTA_API_TOKEN", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_POLICY", "off")
    monkeypatch.delenv("PRIVACY_SERVICE_TOKEN", raising=False)
    sys.modules.pop("services.ingestion_api_service.main", None)
    return importlib.import_module("services.ingestion_api_service.main")


class _SnapshotStore:
    active = False

    @contextmanager
    def processing_snapshot(self, workspace: str):
        assert workspace == "matter-a"
        self.active = True
        try:
            yield PrivacyRuntimeSettings(
                workspace=workspace,
                privacy_policy="strict",
                privacy_detector="rizzo_regex",
                privacy_mapping_enabled=False,
            )
        finally:
            self.active = False


class _PrivacyClient:
    def __init__(self, snapshot: _SnapshotStore) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def pseudonymize(self, request):
        assert self.snapshot.active is True
        self.calls += 1
        return PrivacyPseudonymizeResponse(
            protected_text=f"[PROTECTED_{self.calls}]",
            findings=[],
            pii_count=1,
            pii_types=["EMAIL"],
            engine=PrivacyEngineMetadata(
                name="rizzo-pii",
                version="test",
                source_revision="abc",
                mode="regex_checksum",
            ),
            reversible=False,
            mapping_stored=False,
        )


def test_decision_input_and_output_share_one_runtime_settings_snapshot(
    monkeypatch,
    tmp_path,
) -> None:
    ingestion = _load_ingestion(monkeypatch, tmp_path / "objects")
    snapshot = _SnapshotStore()
    client = _PrivacyClient(snapshot)
    monkeypatch.setattr(ingestion, "runtime_settings_store", snapshot)
    monkeypatch.setattr(ingestion, "privacy_client", client)
    payload = AIDecisionIngestRequest(
        decision_id="decision-1",
        model="test-model",
        input="alice@example.com",
        output="Contact alice@example.com",
        context_docs=["doc-1"],
        tenant="matter-a",
    )

    protected = ingestion._protect_decision_evidence(payload)

    assert protected.input == "[PROTECTED_1]"
    assert protected.output == "[PROTECTED_2]"
    assert client.calls == 2
    assert snapshot.active is False
    assert protected.metadata["_decision_privacy"]["privacy_policy"] == "strict"
