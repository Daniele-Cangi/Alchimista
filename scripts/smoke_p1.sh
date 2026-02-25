#!/usr/bin/env bash
set -euo pipefail

INGEST_URL="${INGEST_URL:-http://localhost:8011}"
PROCESSOR_URL="${PROCESSOR_URL:-http://localhost:8012}"
RAG_URL="${RAG_URL:-http://localhost:8013}"
TENANT="${TENANT:-default}"

TMP_FILE="/tmp/alchimista_test_doc.txt"
cat > "$TMP_FILE" <<DOC
Contract effective date: 2026-02-25.
Supplier email: legal@example.com
Invoice amount: 1200 DKK
DOC

echo "[1/4] Upload multipart to ingestion..."
RESP="$(curl -sS -X POST "$INGEST_URL/v1/ingest" -F "tenant=$TENANT" -F "file=@$TMP_FILE;type=text/plain")"
echo "$RESP"

DOC_ID="$(python3 - <<PY
import json
print(json.loads('''$RESP''')['doc_id'])
PY
)"
GCS_URI="$(python3 - <<PY
import json
print(json.loads('''$RESP''')['gcs_uri'])
PY
)"
TRACE_ID="$(python3 - <<PY
import json
print(json.loads('''$RESP''')['trace_id'])
PY
)"

echo "[2/4] Trigger processor directly (bypassing subscription)..."
PAYLOAD="$(cat <<JSON
{"id":"$DOC_ID","uri":"$GCS_URI","type":"text/plain","size":120,"tenant":"$TENANT","ts":"$(date -Iseconds)","trace_id":"$TRACE_ID"}
JSON
)"
curl -sS -X POST "$PROCESSOR_URL/v1/process" -H 'Content-Type: application/json' -d "$PAYLOAD"
echo

echo "[3/4] Check document status..."
curl -sS "$INGEST_URL/v1/doc/$DOC_ID?tenant=$TENANT"
echo

echo "[4/4] Query RAG with mandatory citations..."
curl -sS -X POST "$RAG_URL/v1/query" -H 'Content-Type: application/json' -d "{\"query\":\"What is the invoice amount?\",\"tenant\":\"$TENANT\",\"top_k\":3,\"trace_id\":\"$TRACE_ID\"}"
echo
