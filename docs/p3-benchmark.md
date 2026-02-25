# P3.1 Benchmark

This benchmark is the objective baseline for retrieval and citation quality.

## Scope
- Fixed dataset in `benchmark/dataset_v1.json`
- End-to-end flow:
  1. ingest docs
  2. processor completion (`QUEUED/RUNNING` -> `SUCCEEDED`)
  3. query rag
- Metrics:
  - `recall_at_k`
  - `citation_coverage`
  - `keyword_hit_rate`
  - `mrr`
  - `error_rate`

## Run
```bash
./scripts/run_p3_benchmark.py \
  --dataset benchmark/dataset_v1.json \
  --output-dir reports/benchmarks
```

Optional URLs:
```bash
INGEST_URL='https://ingestion-api-service-pe7qslbcvq-ez.a.run.app' \
RAG_URL='https://rag-query-service-pe7qslbcvq-ez.a.run.app' \
./scripts/run_p3_benchmark.py
```

Processing mode:
- Default: `event-driven` (recommended in production, waits on `/v1/doc/{id}` until terminal status).
- Optional: `direct` (calls `document-processor-service /v1/process` and then waits on status).
- Benchmark ingest uses tenant-scoped runtime doc IDs (`<tenant>::<dataset_doc_id>`) to avoid cross-tenant ID collisions.

```bash
./scripts/run_p3_benchmark.py \
  --processing-mode event-driven \
  --processing-timeout-seconds 300 \
  --poll-interval-seconds 2
```

Optional bearer token (for P3.3 JWT/OIDC protected endpoints):
```bash
BENCHMARK_BEARER_TOKEN='REPLACE_ME' \
./scripts/run_p3_benchmark.py
```

## Output
- `reports/benchmarks/benchmark_<timestamp>.json`
- `reports/benchmarks/latest.json`

`latest.json` should be treated as the active baseline reference for P3.2 experiments.
