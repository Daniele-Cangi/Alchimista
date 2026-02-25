import json
import logging

from services.shared.logging_utils import log_event


def test_log_event_always_contains_context_keys(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="alchimista"):
        log_event("info", "test_event", custom="value")

    payload = json.loads(caplog.records[-1].message)
    assert payload["message"] == "test_event"
    assert payload["trace_id"] is None
    assert payload["doc_id"] is None
    assert payload["job_id"] is None
    assert payload["tenant"] is None
    assert payload["custom"] == "value"
