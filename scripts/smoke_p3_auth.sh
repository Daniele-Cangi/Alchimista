#!/usr/bin/env bash
set -euo pipefail

TOKEN="${1:-}"
TENANT="${2:-default}"
RAG_URL="${RAG_URL:-https://rag-query-service-pe7qslbcvq-ez.a.run.app}"

if [[ -z "$TOKEN" ]]; then
  echo "Usage: $0 <bearer_token> [tenant]" >&2
  exit 1
fi

HTTP_CODE="$(curl -sS -o /tmp/alchimista_auth_smoke.json -w '%{http_code}' \
  -X POST "${RAG_URL}/v1/query" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"query\":\"What is the amount due for ALPHA-INV-001?\",\"tenant\":\"${TENANT}\",\"top_k\":3}")"

echo "http_code=${HTTP_CODE}"
cat /tmp/alchimista_auth_smoke.json
echo
