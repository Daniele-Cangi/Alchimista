from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Callable

import google.auth
from google.auth.transport.requests import AuthorizedSession

from services.shared.config import RuntimeConfig


_AI_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


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


@dataclass
class VertexTextEmbeddingClient:
    project_id: str
    region: str
    model: str
    timeout_seconds: int
    target_dimensions: int

    def __post_init__(self) -> None:
        credentials, _ = google.auth.default(scopes=[_AI_SCOPE])
        self._session = AuthorizedSession(credentials)
        self._url = (
            f"https://{self.region}-aiplatform.googleapis.com/v1/"
            f"projects/{self.project_id}/locations/{self.region}/publishers/google/models/{self.model}:predict"
        )

    def embed(self, text: str) -> list[float]:
        payload = {
            "instances": [{"content": text}],
            "parameters": {"autoTruncate": True},
        }
        response = self._session.post(self._url, json=payload, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Vertex embedding request failed ({response.status_code}): "
                f"{_shorten(response.text)} payload={_shorten(json.dumps(payload, separators=(',', ':')))}"
            )

        try:
            body = response.json()
        except Exception as exc:
            raise RuntimeError(f"Vertex embedding invalid JSON: {exc}") from exc

        values = _extract_embedding_values(body)
        return project_embedding(values, self.target_dimensions)


def build_embedder(config: RuntimeConfig) -> Callable[[str], list[float]]:
    if config.embedding_backend == "vertex_text_embedding":
        client = VertexTextEmbeddingClient(
            project_id=config.project_id,
            region=config.region,
            model=config.vertex_embedding_model,
            timeout_seconds=config.embedding_timeout_seconds,
            target_dimensions=config.embedding_dimensions,
        )
        return client.embed

    return lambda text: deterministic_embedding(text, config.embedding_dimensions)


def project_embedding(values: list[float], target_dimensions: int) -> list[float]:
    if target_dimensions <= 0:
        raise ValueError("target_dimensions must be > 0")
    if not values:
        return deterministic_embedding("", target_dimensions)

    if len(values) == target_dimensions:
        return _normalize(values)
    if len(values) < target_dimensions:
        padded = values + [0.0] * (target_dimensions - len(values))
        return _normalize(padded)

    projected = [0.0] * target_dimensions
    for idx, value in enumerate(values):
        projected[idx % target_dimensions] += float(value)
    return _normalize(projected)


def _extract_embedding_values(body: dict[str, Any]) -> list[float]:
    predictions = body.get("predictions")
    if not isinstance(predictions, list) or not predictions:
        raise RuntimeError(f"Vertex embedding missing predictions: {body}")
    first = predictions[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"Vertex embedding invalid prediction entry: {first}")

    candidates: list[Any] = [
        first.get("embeddings"),
        first.get("embedding"),
        first.get("values"),
    ]
    for candidate in candidates:
        parsed = _read_values(candidate)
        if parsed:
            return parsed
    raise RuntimeError(f"Vertex embedding values not found: {first}")


def _read_values(candidate: Any) -> list[float]:
    if candidate is None:
        return []
    if isinstance(candidate, dict):
        if "values" in candidate:
            return _read_values(candidate.get("values"))
        if "value" in candidate:
            return _read_values(candidate.get("value"))
        return []
    if isinstance(candidate, list):
        out: list[float] = []
        for item in candidate:
            if not isinstance(item, (int, float)):
                return []
            out.append(float(item))
        return out
    return []


def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def _shorten(text: str, max_len: int = 600) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...(truncated)"
