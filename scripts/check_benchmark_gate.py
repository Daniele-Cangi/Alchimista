#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_GATES = {
    "min_success_rate",
    "max_error_rate",
    "min_citation_coverage",
    "min_recall_at_k",
    "min_mrr",
    "max_p95_latency_ms",
}

REQUIRED_GATES = {
    "max_error_rate",
    "min_citation_coverage",
    "min_recall_at_k",
    "min_mrr",
    "max_p95_latency_ms",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate benchmark summary against gates in spec/project.yaml.")
    parser.add_argument("--spec", default="spec/project.yaml")
    parser.add_argument("--report", default="reports/benchmarks/latest.json")
    parser.add_argument("--allow-missing-report", action="store_true")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    report_path = Path(args.report)

    gates = load_gates(spec_path)
    if not report_path.exists():
        if args.allow_missing_report:
            print(json.dumps({"report": str(report_path), "status": "skipped_missing_report"}, ensure_ascii=True))
            return 0
        raise RuntimeError(f"Benchmark report not found: {report_path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = dict(report.get("summary") or {})
    run_id = str(report.get("run_id") or "unknown")

    checks = evaluate_gates(gates=gates, summary=summary)
    passed = all(item["passed"] for item in checks)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "report_path": str(report_path),
                "passed": passed,
                "checks": checks,
            },
            ensure_ascii=True,
        )
    )
    return 0 if passed else 1


def load_gates(spec_path: Path) -> dict[str, float]:
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    gates = (((raw or {}).get("benchmark") or {}).get("gates") or {})
    if not isinstance(gates, dict):
        raise RuntimeError("benchmark.gates must be a mapping in spec/project.yaml")

    unknown = [key for key in sorted(gates.keys()) if key not in SUPPORTED_GATES]
    if unknown:
        raise RuntimeError(f"Unknown benchmark gates in spec: {', '.join(unknown)}")

    missing = [key for key in sorted(REQUIRED_GATES) if key not in gates]
    if missing:
        raise RuntimeError(f"Missing benchmark gates in spec: {', '.join(missing)}")
    return {key: float(value) for key, value in gates.items()}


def evaluate_gates(*, gates: dict[str, float], summary: dict[str, Any]) -> list[dict[str, Any]]:
    total = int(summary.get("total_queries") or 0)
    successful = int(summary.get("successful_queries") or 0)
    success_rate = (successful / float(total)) if total else 0.0

    actual_values = {
        "min_success_rate": success_rate,
        "max_error_rate": float(summary.get("error_rate") or 0.0),
        "min_citation_coverage": float(summary.get("citation_coverage") or 0.0),
        "min_recall_at_k": float(summary.get("recall_at_k") or 0.0),
        "min_mrr": float(summary.get("mrr") or 0.0),
        "max_p95_latency_ms": float(summary.get("p95_latency_ms") if summary.get("p95_latency_ms") is not None else float("inf")),
    }

    checks: list[dict[str, Any]] = []
    for key in sorted(gates.keys()):
        if key not in actual_values:
            raise RuntimeError(f"Unsupported gate at evaluation time: {key}")
        expected = float(gates[key])
        actual = float(actual_values.get(key, 0.0))
        if key.startswith("min_"):
            comparator = ">="
            passed = actual >= expected
            expected_field = {"expected_min": expected}
        elif key.startswith("max_"):
            comparator = "<="
            passed = actual <= expected
            expected_field = {"expected_max": expected}
        else:
            raise RuntimeError(f"Invalid gate naming convention: {key}")

        checks.append(
            {
                "gate": key,
                "operator": comparator,
                "expected": expected,
                "actual": actual,
                "passed": passed,
                **expected_field,
            }
        )
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
