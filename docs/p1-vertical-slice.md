# P1 Vertical Slice Contract

## Pub/Sub ingest message
```json
{
  "id": "doc_id",
  "uri": "gs://bucket/raw/doc.pdf",
  "type": "application/pdf",
  "size": 123,
  "tenant": "default",
  "ts": "ISO8601",
  "trace_id": "uuid"
}
```

## SQL jobs state machine
- `QUEUED`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`

## Query response
```json
{
  "answers": [
    {
      "text": "...",
      "score": 0.87,
      "citations": [
        {"doc_id": "...", "chunk_id": "..."}
      ]
    }
  ]
}
```

## Service endpoints
### ingestion-api-service
- `POST /v1/ingest`
- `POST /v1/ingest/complete`
- `GET /v1/doc/{id}`

### document-processor-service
- `POST /v1/process`
- `POST /v1/process/pubsub`

### rag-query-service
- `POST /v1/query`
