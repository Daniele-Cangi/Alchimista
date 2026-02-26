from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class QueryBenchmarkResult:
    query_id: str
    success: bool
    has_citations: bool
    expected_doc_hit: bool
    expected_doc_rank: int | None
    keyword_hit: bool
    latency_ms: int | None = None


def compute_summary(results: list[QueryBenchmarkResult]) -> dict[str, float | int]:
    total_queries = len(results)
    if total_queries == 0:
        return {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "error_rate": 0.0,
            "citation_coverage": 0.0,
            "recall_at_k": 0.0,
            "keyword_hit_rate": 0.0,
            "mrr": 0.0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "max_latency_ms": 0,
        }

    failed_queries = sum(1 for item in results if not item.success)
    successful_queries = total_queries - failed_queries

    citation_hits = sum(1 for item in results if item.has_citations)
    expected_hits = sum(1 for item in results if item.expected_doc_hit)
    keyword_hits = sum(1 for item in results if item.keyword_hit)

    rr_sum = 0.0
    for item in results:
        if item.expected_doc_rank:
            rr_sum += 1.0 / float(item.expected_doc_rank)

    latencies = [int(item.latency_ms) for item in results if item.latency_ms is not None and item.latency_ms >= 0]
    p50_latency_ms = _percentile_nearest_rank(latencies, 0.50)
    p95_latency_ms = _percentile_nearest_rank(latencies, 0.95)
    max_latency_ms = max(latencies) if latencies else 0

    return {
        "total_queries": total_queries,
        "successful_queries": successful_queries,
        "failed_queries": failed_queries,
        "error_rate": failed_queries / float(total_queries),
        "citation_coverage": citation_hits / float(total_queries),
        "recall_at_k": expected_hits / float(total_queries),
        "keyword_hit_rate": keyword_hits / float(total_queries),
        "mrr": rr_sum / float(total_queries),
        "p50_latency_ms": p50_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "max_latency_ms": max_latency_ms,
    }


def _percentile_nearest_rank(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    if percentile <= 0:
        return min(values)
    if percentile >= 1:
        return max(values)

    sorted_values = sorted(values)
    index = max(0, math.ceil(len(sorted_values) * percentile) - 1)
    return int(sorted_values[index])
