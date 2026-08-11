from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any


logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("alchimista")

_SENSITIVE_KEYS = {
    "text",
    "input",
    "output",
    "payload",
    "source_text",
    "entity_value",
    "raw_value",
    "plaintext",
    "mapping",
    "encrypted_value",
}
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_CF_RE = re.compile(r"\b[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]\b")
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ .\-]?\d){12,18}(?!\d)")
_IBAN_RE = re.compile(r"\b[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}\b")


def log_event(level: str, message: str, **kwargs: Any) -> None:
    required_context = {
        "trace_id": kwargs.pop("trace_id", None),
        "doc_id": kwargs.pop("doc_id", None),
        "job_id": kwargs.pop("job_id", None),
        "tenant": kwargs.pop("tenant", None),
    }
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "message": message,
        **required_context,
        **kwargs,
    }
    line = json.dumps(_sanitize_for_log(payload), ensure_ascii=True)
    if level.lower() == "error":
        logger.error(line)
    elif level.lower() == "warning":
        logger.warning(line)
    else:
        logger.info(line)


def _sanitize_for_log(value: Any, *, key: str | None = None) -> Any:
    if key and key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _sanitize_for_log(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_log(item) for item in value]
    if isinstance(value, str):
        sanitized = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
        sanitized = _CF_RE.sub("[REDACTED_CF]", sanitized)
        sanitized = _CARD_RE.sub("[REDACTED_CARD]", sanitized)
        sanitized = _IBAN_RE.sub("[REDACTED_IBAN]", sanitized)
        return sanitized
    return value
