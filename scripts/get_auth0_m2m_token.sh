#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${1:-}"
CLIENT_ID="${2:-}"
CLIENT_SECRET="${3:-}"
AUDIENCE="${4:-https://api.alchimista.ai}"
SCOPE="${5:-}"

if [[ -z "$DOMAIN" || -z "$CLIENT_ID" || -z "$CLIENT_SECRET" ]]; then
  echo "Usage: $0 <auth0_domain> <client_id> <client_secret> [audience] [scope]" >&2
  exit 1
fi

TOKEN_URL="https://${DOMAIN}/oauth/token"

if [[ -n "$SCOPE" ]]; then
  RESPONSE="$(curl -fsS -X POST "$TOKEN_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"client_id\":\"${CLIENT_ID}\",\"client_secret\":\"${CLIENT_SECRET}\",\"audience\":\"${AUDIENCE}\",\"grant_type\":\"client_credentials\",\"scope\":\"${SCOPE}\"}")"
else
  RESPONSE="$(curl -fsS -X POST "$TOKEN_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"client_id\":\"${CLIENT_ID}\",\"client_secret\":\"${CLIENT_SECRET}\",\"audience\":\"${AUDIENCE}\",\"grant_type\":\"client_credentials\"}")"
fi

ACCESS_TOKEN="$(jq -r '.access_token // empty' <<<"$RESPONSE")"
if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "Token response did not contain access_token:" >&2
  echo "$RESPONSE" >&2
  exit 1
fi

echo "$ACCESS_TOKEN"
