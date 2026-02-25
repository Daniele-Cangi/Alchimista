from __future__ import annotations

import math
from typing import Any


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[i] * right[i] for i in range(size))
    left_norm = math.sqrt(sum(left[i] * left[i] for i in range(size))) or 1.0
    right_norm = math.sqrt(sum(right[i] * right[i] for i in range(size))) or 1.0
    return dot / (left_norm * right_norm)


def rank_chunks(query_embedding: list[float], chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for item in chunks:
        emb = item.get("embedding")
        if not emb:
            continue
        score = cosine_similarity(query_embedding, emb)
        scored.append({**item, "score": score})
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]
