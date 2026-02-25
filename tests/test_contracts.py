import pytest

from services.shared.contracts import AIDecisionIngestRequest, AIDecisionQueryRequest, IngestMessage, QueryAnswer


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
