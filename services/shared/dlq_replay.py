from __future__ import annotations

import json
from typing import Any

from services.shared.contracts import IngestMessage


def parse_ingest_message_from_dlq(raw_data: bytes) -> IngestMessage:
    payload = json.loads(raw_data.decode("utf-8"))
    return extract_ingest_message(payload)


def extract_ingest_message(payload: dict[str, Any]) -> IngestMessage:
    wrapped = payload.get("event")
    if isinstance(wrapped, dict):
        return IngestMessage.model_validate(wrapped)
    return IngestMessage.model_validate(payload)
