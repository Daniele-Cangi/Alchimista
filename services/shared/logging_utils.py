from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("alchimista")


def log_event(level: str, message: str, **kwargs: Any) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "message": message,
        **kwargs,
    }
    line = json.dumps(payload, ensure_ascii=True)
    if level.lower() == "error":
        logger.error(line)
    elif level.lower() == "warning":
        logger.warning(line)
    else:
        logger.info(line)
