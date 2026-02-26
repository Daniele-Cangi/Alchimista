from services.shared.benchmark_metrics import QueryBenchmarkResult, compute_summary


def test_compute_summary_basic() -> None:
    results = [
        QueryBenchmarkResult(
            query_id="q1",
            success=True,
            has_citations=True,
            expected_doc_hit=True,
            expected_doc_rank=1,
            keyword_hit=True,
            latency_ms=100,
        ),
        QueryBenchmarkResult(
            query_id="q2",
            success=True,
            has_citations=True,
            expected_doc_hit=False,
            expected_doc_rank=None,
            keyword_hit=False,
            latency_ms=200,
        ),
        QueryBenchmarkResult(
            query_id="q3",
            success=False,
            has_citations=False,
            expected_doc_hit=False,
            expected_doc_rank=None,
            keyword_hit=False,
            latency_ms=300,
        ),
    ]

    summary = compute_summary(results)
    assert summary["total_queries"] == 3
    assert summary["successful_queries"] == 2
    assert summary["failed_queries"] == 1
    assert summary["error_rate"] == 1 / 3
    assert summary["citation_coverage"] == 2 / 3
    assert summary["recall_at_k"] == 1 / 3
    assert summary["keyword_hit_rate"] == 1 / 3
    assert summary["mrr"] == 1 / 3
    assert summary["p50_latency_ms"] == 200
    assert summary["p95_latency_ms"] == 300
    assert summary["max_latency_ms"] == 300
