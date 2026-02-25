from services.shared.contracts import IngestMessage, QueryAnswer


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
