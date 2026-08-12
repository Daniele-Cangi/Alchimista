from __future__ import annotations

import importlib
import sys


def _load_ingestion(monkeypatch, tmp_path):
    monkeypatch.setenv("ALCHIMISTA_PROFILE", "local")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("ALCHIMISTA_API_TOKEN", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "objects"))
    monkeypatch.setenv("PRIVACY_POLICY", "off")
    monkeypatch.delenv("PRIVACY_SERVICE_TOKEN", raising=False)
    sys.modules.pop("services.ingestion_api_service.main", None)
    return importlib.import_module("services.ingestion_api_service.main")


def test_document_hold_matching_covers_tenant_and_document(monkeypatch, tmp_path) -> None:
    ingestion = _load_ingestion(monkeypatch, tmp_path)
    holds = [
        {"hold_id": "tenant-hold", "tenant": "matter-a", "scope_type": "tenant", "scope_id": "matter-a", "released_at": None},
        {"hold_id": "doc-hold", "tenant": "matter-a", "scope_type": "document", "scope_id": "doc-1", "released_at": None},
        {"hold_id": "other-doc", "tenant": "matter-a", "scope_type": "document", "scope_id": "doc-2", "released_at": None},
        {"hold_id": "released", "tenant": "matter-a", "scope_type": "document", "scope_id": "doc-1", "released_at": "2026-08-12"},
        {"hold_id": "other-tenant", "tenant": "matter-b", "scope_type": "tenant", "scope_id": "*", "released_at": None},
    ]

    result = ingestion._matching_legal_hold_ids_for_document(
        tenant="matter-a",
        doc_id="doc-1",
        holds=holds,
    )

    assert result == ["tenant-hold", "doc-hold"]
