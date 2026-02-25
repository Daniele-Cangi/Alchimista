from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

from services.shared.config import RuntimeConfig


_AI_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


@dataclass(frozen=True)
class NeighborHit:
    chunk_id: str
    distance: float


class VertexVectorSearchClient:
    def __init__(self, *, project_id: str, region: str, index_id: str, index_endpoint_id: str, deployed_index_id: str):
        credentials, _ = google.auth.default(scopes=[_AI_SCOPE])
        self._session = AuthorizedSession(credentials)
        self._base = f"https://{region}-aiplatform.googleapis.com/v1"
        self._index_name = f"projects/{project_id}/locations/{region}/indexes/{index_id}"
        self._index_endpoint_name = f"projects/{project_id}/locations/{region}/indexEndpoints/{index_endpoint_id}"
        self._deployed_index_id = deployed_index_id
        self._query_base = self._resolve_query_base()

    def upsert_chunks(self, *, tenant: str, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        datapoints: list[dict[str, Any]] = []
        for chunk in chunks:
            datapoints.append(
                {
                    "datapointId": chunk["chunk_id"],
                    "featureVector": chunk["embedding"],
                    "restricts": [
                        {"namespace": "tenant", "allowList": [tenant]},
                        {"namespace": "doc_id", "allowList": [chunk["doc_id"]]},
                    ],
                }
            )

        for batch in _batch(datapoints, 100):
            self._post(
                f"{self._base}/{self._index_name}:upsertDatapoints",
                {"datapoints": batch},
            )

    def remove_chunks(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        for batch in _batch(chunk_ids, 1000):
            self._post(
                f"{self._base}/{self._index_name}:removeDatapoints",
                {"datapointIds": batch},
            )

    def find_neighbors(
        self,
        *,
        query_embedding: list[float],
        tenant: str,
        top_k: int,
        doc_ids: list[str] | None = None,
    ) -> list[NeighborHit]:
        restricts: list[dict[str, Any]] = [{"namespace": "tenant", "allowList": [tenant]}]
        if doc_ids:
            restricts.append({"namespace": "doc_id", "allowList": doc_ids})

        payload = {
            "deployedIndexId": self._deployed_index_id,
            "queries": [
                {
                    "datapoint": {
                        "featureVector": query_embedding,
                        "restricts": restricts,
                    },
                    "neighborCount": max(1, top_k),
                }
            ],
            "returnFullDatapoint": False,
        }
        query_url = f"{self._query_base}/{self._index_endpoint_name}:findNeighbors"
        try:
            body = self._post(query_url, payload)
        except Exception:
            if self._query_base == self._base:
                raise
            # Fallback to control-plane endpoint if public endpoint call fails.
            body = self._post(f"{self._base}/{self._index_endpoint_name}:findNeighbors", payload)
        nearest = body.get("nearestNeighbors") or []
        if not nearest:
            return []
        neighbors = nearest[0].get("neighbors") or []
        hits: list[NeighborHit] = []
        for item in neighbors:
            datapoint = item.get("datapoint") or {}
            chunk_id = datapoint.get("datapointId")
            if not chunk_id:
                continue
            hits.append(NeighborHit(chunk_id=chunk_id, distance=float(item.get("distance", 0.0))))
        return hits

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._session.post(url, json=payload, timeout=60)
        if response.status_code >= 400:
            raise RuntimeError(
                f"Vertex request failed ({response.status_code}): "
                f"{_shorten(response.text)} payload={_shorten(json.dumps(payload, separators=(',', ':')))}"
            )
        if not response.text:
            return {}
        return response.json()

    def _resolve_query_base(self) -> str:
        try:
            endpoint = self._session.get(f"{self._base}/{self._index_endpoint_name}", timeout=30)
            if endpoint.status_code >= 400:
                return self._base
            body = endpoint.json()
            host = body.get("publicEndpointDomainName")
            if host:
                return f"https://{host}/v1"
        except Exception:
            return self._base
        return self._base


def build_vertex_client(config: RuntimeConfig) -> VertexVectorSearchClient | None:
    if config.vector_backend != "vertex_ai_vector_search":
        return None
    if not config.vertex_index_id or not config.vertex_index_endpoint_id or not config.vertex_deployed_index_id:
        return None
    return VertexVectorSearchClient(
        project_id=config.project_id,
        region=config.region,
        index_id=config.vertex_index_id,
        index_endpoint_id=config.vertex_index_endpoint_id,
        deployed_index_id=config.vertex_deployed_index_id,
    )


def _batch(values: list[Any], size: int) -> list[list[Any]]:
    out: list[list[Any]] = []
    for idx in range(0, len(values), size):
        out.append(values[idx : idx + size])
    return out


def _shorten(text: str, max_len: int = 800) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...(truncated)"
