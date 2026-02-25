#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.shared.benchmark_metrics import QueryBenchmarkResult, compute_summary


DEFAULT_INGEST_URL = "https://ingestion-api-service-pe7qslbcvq-ez.a.run.app"
DEFAULT_PROCESSOR_URL = "https://document-processor-service-pe7qslbcvq-ez.a.run.app"
DEFAULT_RAG_URL = "https://rag-query-service-pe7qslbcvq-ez.a.run.app"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P3.1 benchmark for Alchimista.")
    parser.add_argument("--dataset", default="benchmark/dataset_v1.json")
    parser.add_argument("--output-dir", default="reports/benchmarks")
    parser.add_argument("--ingest-url", default=os.getenv("INGEST_URL", DEFAULT_INGEST_URL))
    parser.add_argument("--processor-url", default=os.getenv("PROCESSOR_URL", DEFAULT_PROCESSOR_URL))
    parser.add_argument("--rag-url", default=os.getenv("RAG_URL", DEFAULT_RAG_URL))
    parser.add_argument("--timeout-seconds", type=int, default=60)
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tenant = str(dataset.get("tenant", "benchmark"))
    top_k = int(dataset.get("top_k", 3))

    alias_to_doc_id: dict[str, str] = {}
    document_runs: list[dict[str, Any]] = []

    for doc in dataset["documents"]:
        doc_alias = str(doc["alias"])
        doc_id = str(doc["doc_id"])
        filename = str(doc["filename"])
        content_type = str(doc.get("content_type", "text/plain"))
        content = _apply_tokens(str(doc["content"]), run_id)

        ingest = _multipart_ingest(
            ingest_url=args.ingest_url,
            tenant=tenant,
            doc_id=doc_id,
            filename=filename,
            content_type=content_type,
            content=content.encode("utf-8"),
            timeout=args.timeout_seconds,
        )
        process = _direct_process(
            processor_url=args.processor_url,
            message={
                "id": ingest["doc_id"],
                "uri": ingest["gcs_uri"],
                "type": content_type,
                "size": len(content.encode("utf-8")),
                "tenant": tenant,
                "ts": datetime.now(timezone.utc).isoformat(),
                "trace_id": ingest["trace_id"],
            },
            timeout=args.timeout_seconds,
        )
        status = _document_status(
            ingest_url=args.ingest_url,
            doc_id=ingest["doc_id"],
            tenant=tenant,
            timeout=args.timeout_seconds,
        )

        alias_to_doc_id[doc_alias] = ingest["doc_id"]
        document_runs.append(
            {
                "alias": doc_alias,
                "doc_id": ingest["doc_id"],
                "trace_id": ingest["trace_id"],
                "processor_status": process.get("status"),
                "job_id": (status.get("job") or {}).get("job_id"),
            }
        )

    query_results: list[dict[str, Any]] = []
    summary_inputs: list[QueryBenchmarkResult] = []

    for query_case in dataset["queries"]:
        query_id = str(query_case["query_id"])
        query_text = _apply_tokens(str(query_case["query"]), run_id)
        expected_alias = str(query_case["expected_doc_alias"])
        expected_doc_id = alias_to_doc_id.get(expected_alias)
        expected_keyword = _apply_tokens(str(query_case.get("expected_keyword", "")), run_id)
        trace_id = str(uuid4())

        started = time.perf_counter()
        try:
            response = _query_rag(
                rag_url=args.rag_url,
                payload={
                    "query": query_text,
                    "tenant": tenant,
                    "top_k": top_k,
                    "trace_id": trace_id,
                },
                timeout=args.timeout_seconds,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            answers = response.get("answers") or []
            top_answer = answers[0] if answers else {}
            citations = top_answer.get("citations") or []
            citation_doc_ids = [item.get("doc_id") for item in citations if isinstance(item, dict)]

            expected_doc_rank = None
            for idx, citation_doc_id in enumerate(citation_doc_ids, start=1):
                if citation_doc_id == expected_doc_id:
                    expected_doc_rank = idx
                    break

            has_citations = len(citations) > 0
            expected_doc_hit = expected_doc_rank is not None
            keyword_hit = expected_keyword.lower() in str(top_answer.get("text", "")).lower()
            success = len(answers) > 0

            query_results.append(
                {
                    "query_id": query_id,
                    "trace_id": trace_id,
                    "query": query_text,
                    "expected_doc_alias": expected_alias,
                    "expected_doc_id": expected_doc_id,
                    "expected_keyword": expected_keyword,
                    "success": success,
                    "has_citations": has_citations,
                    "expected_doc_hit": expected_doc_hit,
                    "expected_doc_rank": expected_doc_rank,
                    "keyword_hit": keyword_hit,
                    "latency_ms": elapsed_ms,
                    "citations": citations,
                    "answer_preview": str(top_answer.get("text", ""))[:300],
                    "error": None,
                }
            )
            summary_inputs.append(
                QueryBenchmarkResult(
                    query_id=query_id,
                    success=success,
                    has_citations=has_citations,
                    expected_doc_hit=expected_doc_hit,
                    expected_doc_rank=expected_doc_rank,
                    keyword_hit=keyword_hit,
                )
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            query_results.append(
                {
                    "query_id": query_id,
                    "trace_id": trace_id,
                    "query": query_text,
                    "expected_doc_alias": expected_alias,
                    "expected_doc_id": expected_doc_id,
                    "expected_keyword": expected_keyword,
                    "success": False,
                    "has_citations": False,
                    "expected_doc_hit": False,
                    "expected_doc_rank": None,
                    "keyword_hit": False,
                    "latency_ms": elapsed_ms,
                    "citations": [],
                    "answer_preview": "",
                    "error": str(exc),
                }
            )
            summary_inputs.append(
                QueryBenchmarkResult(
                    query_id=query_id,
                    success=False,
                    has_citations=False,
                    expected_doc_hit=False,
                    expected_doc_rank=None,
                    keyword_hit=False,
                )
            )

    summary = compute_summary(summary_inputs)

    report = {
        "run_id": run_id,
        "dataset": dataset.get("name"),
        "dataset_path": str(dataset_path),
        "tenant": tenant,
        "top_k": top_k,
        "service_urls": {
            "ingest_url": args.ingest_url,
            "processor_url": args.processor_url,
            "rag_url": args.rag_url,
        },
        "documents": document_runs,
        "queries": query_results,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"benchmark_{run_id}.json"
    latest_path = output_dir / "latest.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    latest_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(json.dumps({"report_path": str(report_path), "summary": summary}, ensure_ascii=True))
    return 0


def _apply_tokens(value: str, run_id: str) -> str:
    return value.replace("{{RUN_ID}}", run_id)


def _multipart_ingest(
    *,
    ingest_url: str,
    tenant: str,
    doc_id: str,
    filename: str,
    content_type: str,
    content: bytes,
    timeout: int,
) -> dict[str, Any]:
    with NamedTemporaryFile("wb", delete=True) as tmp:
        tmp.write(content)
        tmp.flush()
        with open(tmp.name, "rb") as fh:
            files = {"file": (filename, fh, content_type)}
            data = {"tenant": tenant, "doc_id": doc_id, "force_reprocess": "true"}
            response = requests.post(f"{ingest_url}/v1/ingest", files=files, data=data, timeout=timeout)
    _raise_for_status(response)
    body = response.json()
    if "doc_id" not in body or "gcs_uri" not in body or "trace_id" not in body:
        raise RuntimeError(f"Unexpected ingest response: {body}")
    return body


def _direct_process(*, processor_url: str, message: dict[str, Any], timeout: int) -> dict[str, Any]:
    response = requests.post(f"{processor_url}/v1/process", json=message, timeout=timeout)
    _raise_for_status(response)
    return response.json()


def _document_status(*, ingest_url: str, doc_id: str, tenant: str, timeout: int) -> dict[str, Any]:
    response = requests.get(f"{ingest_url}/v1/doc/{doc_id}", params={"tenant": tenant}, timeout=timeout)
    _raise_for_status(response)
    return response.json()


def _query_rag(*, rag_url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    response = requests.post(f"{rag_url}/v1/query", json=payload, timeout=timeout)
    _raise_for_status(response)
    return response.json()


def _raise_for_status(response: requests.Response) -> None:
    if response.status_code < 400:
        return
    raise RuntimeError(f"HTTP {response.status_code}: {response.text}")


if __name__ == "__main__":
    raise SystemExit(main())
