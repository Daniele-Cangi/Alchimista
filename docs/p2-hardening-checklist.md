# P2 Hardening Checklist

## Queue reliability
- [ ] Create pull subscription on `doc-ingest-topic`
- [ ] Configure dead-letter policy to `doc-ingest-topic-dlq`
- [ ] Add replay admin endpoint/tool from DLQ to ingest topic

## Backpressure
- [ ] Set Cloud Run max instances per service
- [ ] Set Pub/Sub max outstanding messages per worker
- [ ] Add timeout and retry budget policy

## Security
- [ ] Create dedicated service accounts per service
- [ ] Replace default compute SA usage
- [ ] Enforce CMEK + UBLA on raw/processed/reports buckets
- [ ] Secret Manager for DB credentials and API keys

## Observability
- [ ] Dashboard: backlog age, error rate, p95 processing time
- [ ] Alerts: failed jobs spike, DLQ growth, SQL connection saturation
- [ ] Structured logs include `trace_id`, `doc_id`, `job_id`, `tenant`
