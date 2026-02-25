# P3.1 Benchmark

This benchmark is the objective baseline for retrieval and citation quality.

## Scope
- Fixed dataset in `benchmark/dataset_v1.json`
- End-to-end flow:
  1. ingest docs
  2. processor run
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
PROCESSOR_URL='https://document-processor-service-pe7qslbcvq-ez.a.run.app' \
RAG_URL='https://rag-query-service-pe7qslbcvq-ez.a.run.app' \
./scripts/run_p3_benchmark.py
```

## Output
- `reports/benchmarks/benchmark_<timestamp>.json`
- `reports/benchmarks/latest.json`

`latest.json` should be treated as the active baseline reference for P3.2 experiments.
