#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


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
    required = {
        "min_success_rate",
        "min_citation_coverage",
        "min_recall_at_k",
        "min_mrr",
    }
    missing = [key for key in sorted(required) if key not in gates]
    if missing:
        raise RuntimeError(f"Missing benchmark gates in spec: {', '.join(missing)}")
    return {key: float(gates[key]) for key in required}


def evaluate_gates(*, gates: dict[str, float], summary: dict[str, Any]) -> list[dict[str, Any]]:
    total = int(summary.get("total_queries") or 0)
    successful = int(summary.get("successful_queries") or 0)
    success_rate = (successful / float(total)) if total else 0.0

    actual_values = {
        "min_success_rate": success_rate,
        "min_citation_coverage": float(summary.get("citation_coverage") or 0.0),
        "min_recall_at_k": float(summary.get("recall_at_k") or 0.0),
        "min_mrr": float(summary.get("mrr") or 0.0),
    }

    checks: list[dict[str, Any]] = []
    for key in sorted(gates.keys()):
        expected = float(gates[key])
        actual = float(actual_values.get(key, 0.0))
        checks.append(
            {
                "gate": key,
                "expected_min": expected,
                "actual": actual,
                "passed": actual >= expected,
            }
        )
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
