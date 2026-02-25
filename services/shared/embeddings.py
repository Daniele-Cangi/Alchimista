from __future__ import annotations

import hashlib
import math


def deterministic_embedding(text: str, dimensions: int = 128) -> list[float]:
    seed = text.encode("utf-8", errors="ignore")
    values: list[float] = []
    nonce = 0

    while len(values) < dimensions:
        digest = hashlib.sha256(seed + nonce.to_bytes(4, "big", signed=False)).digest()
        for i in range(0, len(digest), 2):
            if len(values) >= dimensions:
                break
            raw = int.from_bytes(digest[i : i + 2], "big", signed=False)
            mapped = (raw / 65535.0) * 2.0 - 1.0
            values.append(mapped)
        nonce += 1

    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
