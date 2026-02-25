import pytest

from services.shared.contracts import (
    AIDecisionAdminQueryRequest,
    AIDecisionBundleRequest,
    AIDecisionExportRequest,
    AIDecisionIngestRequest,
    AIDecisionPackageRequest,
    AIDecisionQueryRequest,
    AIDecisionVerifyRequest,
    ConnectorIngestResponse,
    ConfidenceBand,
    GCSConnectorImportRequest,
    IngestMessage,
    LegalHoldCreateRequest,
    QueryAnswer,
    RetentionPolicyUpsertRequest,
)


def test_ingest_message_contract() -> None:
    payload = {
        "id": "doc_1",
        "uri": "gs://bucket/raw/doc.pdf",
        "type": "application/pdf",
        "size": 123,
        "tenant": "default",
        "ts": "2026-02-25T10:00:00Z",
        "trace_id": "trace-1",
    }
    model = IngestMessage.model_validate(payload)
    assert model.id == "doc_1"


def test_query_answer_requires_citations() -> None:
    answer = QueryAnswer.model_validate(
        {
            "text": "ok",
            "score": 0.9,
            "citations": [{"doc_id": "d1", "chunk_id": "c1"}],
        }
    )
    assert answer.citations[0].doc_id == "d1"


def test_ai_decision_contract_normalizes_context_ids() -> None:
    payload = {
        "decision_id": "d-001",
        "model": "gpt-4",
        "model_version": "2024-01",
        "input": "case input",
        "output": "approved",
        "confidence": 0.94,
        "context_docs": ["doc_id_1", " doc_id_1 ", "doc_id_2"],
        "context_chunks": ["chunk_1", "chunk_1"],
        "tenant": "vendor-x",
        "trace_id": "trace-1",
    }
    model = AIDecisionIngestRequest.model_validate(payload)
    assert model.context_docs == ["doc_id_1", "doc_id_2"]
    assert model.context_chunks == ["chunk_1"]


def test_ai_decision_contract_rejects_empty_context_doc_ids() -> None:
    with pytest.raises(ValueError):
        AIDecisionIngestRequest.model_validate(
            {
                "decision_id": "d-001",
                "model": "gpt-4",
                "input": "case input",
                "output": "approved",
                "context_docs": ["doc_id_1", " "],
                "tenant": "vendor-x",
            }
        )


def test_ai_decision_query_contract_defaults() -> None:
    model = AIDecisionQueryRequest.model_validate({"tenant": "default"})
    assert model.offset == 0
    assert model.limit == 50
    assert model.order.value == "desc"


def test_ai_decision_query_contract_normalizes_advanced_lists() -> None:
    model = AIDecisionQueryRequest.model_validate(
        {
            "tenant": "default",
            "outputs": ["approved", " approved ", "rejected"],
            "context_docs": ["doc-1", "doc-1"],
            "context_chunks": ["chunk-1", " chunk-1 ", "chunk-2"],
            "decision_ids": ["d-001", " d-001 ", "d-002"],
            "confidence_band": "high",
        }
    )
    assert model.outputs == ["approved", "rejected"]
    assert model.context_docs == ["doc-1"]
    assert model.context_chunks == ["chunk-1", "chunk-2"]
    assert model.decision_ids == ["d-001", "d-002"]
    assert model.confidence_band == ConfidenceBand.HIGH


def test_ai_decision_query_contract_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError):
        AIDecisionQueryRequest.model_validate(
            {
                "tenant": "default",
                "min_confidence": 0.9,
                "max_confidence": 0.2,
            }
        )


def test_ai_decision_export_contract_defaults() -> None:
    model = AIDecisionExportRequest.model_validate({"tenant": "default"})
    assert model.limit == 200
    assert model.offset == 0
    assert model.include_context is False


def test_ai_decision_bundle_contract_defaults() -> None:
    model = AIDecisionBundleRequest.model_validate({"tenant": "default"})
    assert model.include_policy_snapshot is True
    assert model.include_context is False


def test_ai_decision_admin_query_contract_defaults_and_normalization() -> None:
    model = AIDecisionAdminQueryRequest.model_validate(
        {
            "tenants": ["default", " default ", "vendor-x"],
            "decision_ids": ["d-001", " d-001 ", "d-002"],
            "outputs": ["approved", " approved "],
        }
    )
    assert model.tenants == ["default", "vendor-x"]
    assert model.decision_ids == ["d-001", "d-002"]
    assert model.outputs == ["approved"]
    assert model.limit == 50


def test_ai_decision_admin_query_contract_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError):
        AIDecisionAdminQueryRequest.model_validate(
            {
                "tenants": ["default"],
                "created_from": "2026-02-28T00:00:00Z",
                "created_to": "2026-02-01T00:00:00Z",
            }
        )


def test_ai_decision_package_contract_defaults() -> None:
    model = AIDecisionPackageRequest.model_validate({"tenant": "default"})
    assert model.include_context is True
    assert model.include_policy_snapshot is True
    assert model.limit == 50


def test_ai_decision_verify_contract_accepts_gs_uri() -> None:
    model = AIDecisionVerifyRequest.model_validate(
        {
            "tenant": "default",
            "gs_uri": "gs://alchimista-reports-994021588311/reports/default/audit/packages/p1/manifest.json",
            "strict_tenant_path": True,
        }
    )
    assert model.gs_uri.startswith("gs://")


def test_ai_decision_verify_contract_rejects_non_gs_uri() -> None:
    with pytest.raises(ValueError):
        AIDecisionVerifyRequest.model_validate(
            {
                "tenant": "default",
                "gs_uri": "https://example.com/file.json",
            }
        )


def test_gcs_connector_contract_rejects_invalid_uri() -> None:
    with pytest.raises(ValueError):
        GCSConnectorImportRequest.model_validate(
            {
                "source_gcs_uri": "/tmp/local.txt",
                "tenant": "default",
            }
        )


def test_gcs_connector_response_contract() -> None:
    model = ConnectorIngestResponse.model_validate(
        {
            "connector": "gcs",
            "tenant": "default",
            "doc_id": "d1",
            "trace_id": "t1",
            "status": "QUEUED",
            "source_gcs_uri": "gs://src/path/a.pdf",
            "raw_gcs_uri": "gs://raw/path/a.pdf",
            "published": True,
        }
    )
    assert model.connector == "gcs"


def test_retention_policy_contract_defaults() -> None:
    model = RetentionPolicyUpsertRequest.model_validate({"tenant": "default"})
    assert model.artifact_type == "audit_artifacts"
    assert model.retain_days == 365
    assert model.immutable_required is True


def test_legal_hold_contract_requires_reason_length() -> None:
    with pytest.raises(ValueError):
        LegalHoldCreateRequest.model_validate(
            {
                "tenant": "default",
                "scope_type": "document",
                "scope_id": "doc-1",
                "reason": "x",
            }
        )
