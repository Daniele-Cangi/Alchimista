#!/usr/bin/env bash
set -euo pipefail

TOKEN="${1:-}"
TENANT="${2:-default}"
RAG_URL="${RAG_URL:-https://rag-query-service-pe7qslbcvq-ez.a.run.app}"
INGEST_URL="${INGEST_URL:-https://ingestion-api-service-pe7qslbcvq-ez.a.run.app}"

if [[ -z "$TOKEN" ]]; then
  echo "Usage: $0 <bearer_token> [tenant]" >&2
  exit 1
fi

TMP_BODY="$(mktemp)"
trap 'rm -f "$TMP_BODY"' EXIT

request_code() {
  local expected_codes="$1"
  shift
  local label="$1"
  shift

  local code
  code="$(curl -sS -o "$TMP_BODY" -w '%{http_code}' "$@")"
  IFS=',' read -r -a allowed <<<"$expected_codes"
  for expected in "${allowed[@]}"; do
    if [[ "$code" == "$expected" ]]; then
      echo "ok ${label} http_code=${code}"
      return 0
    fi
  done

  local body
  body="$(head -c 400 "$TMP_BODY" | tr '\n' ' ')"
  echo "fail ${label} expected=${expected_codes} actual=${code} body=${body}" >&2
  return 1
}

QUERY_PAYLOAD="{\"query\":\"auth boundary smoke test\",\"tenant\":\"${TENANT}\",\"top_k\":1}"
DECISIONS_PAYLOAD="{\"tenant\":\"${TENANT}\",\"limit\":1,\"offset\":0,\"order\":\"desc\"}"

request_code "200" "rag healthz open" \
  -X GET "${RAG_URL}/v1/healthz"

request_code "200" "ingest healthz open" \
  -X GET "${INGEST_URL}/v1/healthz"

request_code "401" "rag query rejects unauthenticated" \
  -X POST "${RAG_URL}/v1/query" \
  -H 'Content-Type: application/json' \
  -d "${QUERY_PAYLOAD}"

request_code "401" "ingest decisions query rejects unauthenticated" \
  -X POST "${INGEST_URL}/v1/decisions/query" \
  -H 'Content-Type: application/json' \
  -d "${DECISIONS_PAYLOAD}"

request_code "200" "rag query accepts authenticated" \
  -X POST "${RAG_URL}/v1/query" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "${QUERY_PAYLOAD}"

request_code "200" "ingest decisions query accepts authenticated" \
  -X POST "${INGEST_URL}/v1/decisions/query" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "${DECISIONS_PAYLOAD}"

echo "auth_enforcement=ok tenant=${TENANT}"
