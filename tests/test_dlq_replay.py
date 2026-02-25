import json

from services.shared.dlq_replay import parse_ingest_message_from_dlq


def test_parse_ingest_message_from_direct_payload() -> None:
    payload = {
        "id": "doc_1",
        "uri": "gs://bucket/raw/doc.pdf",
        "type": "application/pdf",
        "size": 123,
        "tenant": "default",
        "ts": "2026-02-25T10:00:00Z",
        "trace_id": "trace-1",
    }
    model = parse_ingest_message_from_dlq(json.dumps(payload).encode("utf-8"))
    assert model.id == "doc_1"


def test_parse_ingest_message_from_wrapped_payload() -> None:
    payload = {
        "reason": "parse failed",
        "trace_id": "replay-trace",
        "event": {
            "id": "doc_2",
            "uri": "gs://bucket/raw/doc2.pdf",
            "type": "application/pdf",
            "size": 456,
            "tenant": "default",
            "ts": "2026-02-25T10:00:00Z",
            "trace_id": "trace-2",
        },
    }
    model = parse_ingest_message_from_dlq(json.dumps(payload).encode("utf-8"))
    assert model.id == "doc_2"
