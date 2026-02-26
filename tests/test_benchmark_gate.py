from services.shared.benchmark_metrics import QueryBenchmarkResult, compute_summary

from scripts.check_benchmark_gate import evaluate_gates


def test_evaluate_gates_passes() -> None:
    summary = compute_summary(
        [
            QueryBenchmarkResult(
                query_id="q1",
                success=True,
                has_citations=True,
                expected_doc_hit=True,
                expected_doc_rank=1,
                keyword_hit=True,
                latency_ms=120,
            ),
            QueryBenchmarkResult(
                query_id="q2",
                success=True,
                has_citations=True,
                expected_doc_hit=True,
                expected_doc_rank=2,
                keyword_hit=True,
                latency_ms=180,
            ),
        ]
    )
    gates = {
        "max_error_rate": 0.05,
        "min_citation_coverage": 1.0,
        "min_recall_at_k": 1.0,
        "min_mrr": 0.7,
        "max_p95_latency_ms": 250,
    }

    checks = evaluate_gates(gates=gates, summary=summary)
    assert all(item["passed"] for item in checks)


def test_evaluate_gates_fails_on_mrr() -> None:
    summary = compute_summary(
        [
            QueryBenchmarkResult(
                query_id="q1",
                success=True,
                has_citations=True,
                expected_doc_hit=True,
                expected_doc_rank=3,
                keyword_hit=True,
                latency_ms=100,
            ),
            QueryBenchmarkResult(
                query_id="q2",
                success=True,
                has_citations=True,
                expected_doc_hit=True,
                expected_doc_rank=3,
                keyword_hit=True,
                latency_ms=110,
            ),
        ]
    )
    gates = {
        "max_error_rate": 0.05,
        "min_citation_coverage": 1.0,
        "min_recall_at_k": 1.0,
        "min_mrr": 0.5,
        "max_p95_latency_ms": 250,
    }

    checks = evaluate_gates(gates=gates, summary=summary)
    mrr_check = [item for item in checks if item["gate"] == "min_mrr"][0]
    assert not mrr_check["passed"]


def test_evaluate_gates_fails_on_latency() -> None:
    summary = compute_summary(
        [
            QueryBenchmarkResult(
                query_id="q1",
                success=True,
                has_citations=True,
                expected_doc_hit=True,
                expected_doc_rank=1,
                keyword_hit=True,
                latency_ms=300,
            ),
            QueryBenchmarkResult(
                query_id="q2",
                success=True,
                has_citations=True,
                expected_doc_hit=True,
                expected_doc_rank=1,
                keyword_hit=True,
                latency_ms=450,
            ),
        ]
    )
    gates = {
        "max_error_rate": 0.05,
        "min_citation_coverage": 1.0,
        "min_recall_at_k": 1.0,
        "min_mrr": 1.0,
        "max_p95_latency_ms": 400,
    }

    checks = evaluate_gates(gates=gates, summary=summary)
    latency_check = [item for item in checks if item["gate"] == "max_p95_latency_ms"][0]
    assert not latency_check["passed"]
