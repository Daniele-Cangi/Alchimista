# P2 Hardening Checklist

## Queue reliability
- [x] Configure subscription on `doc-ingest-topic`
- [x] Configure dead-letter policy to `doc-ingest-topic-dlq`
- [x] Add replay admin endpoint/tool from DLQ to ingest topic (`POST /v1/admin/replay-dlq`, `scripts/replay_dlq.sh`)

## Backpressure
- [x] Set Cloud Run max instances per service (`scripts/apply_p2_backpressure.sh`)
- [x] Set per-instance inflight guard in processor (`PROCESSOR_MAX_INFLIGHT`)
- [x] Add timeout and retry budget policy (Cloud Run timeout + Pub/Sub retry delays + delivery attempts)

## Security
- [x] Create dedicated service accounts per service
- [x] Replace default compute SA usage
- [x] Enforce CMEK + UBLA on raw/processed/reports buckets
- [x] Secret Manager for DB credentials and API keys

## Observability
- [x] Dashboard: backlog age, error rate, p95 processing time (`Alchimista P2 Operations`)
- [x] Alerts: failed jobs spike, DLQ growth, SQL connection saturation (`scripts/apply_p2_observability.sh`)
- [x] Structured logs include `trace_id`, `doc_id`, `job_id`, `tenant` (`services/shared/logging_utils.py`)
