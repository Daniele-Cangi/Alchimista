#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"
AUTH_ISSUER="${3:-}"
AUTH_AUDIENCE="${4:-}"
AUTH_JWKS_URL="${5:-}"
AUTH_TENANT_CLAIMS="${6:-tenant,tenants}"
AUTH_REQUIRE_TENANT_CLAIM="${7:-true}"

if [[ -z "$AUTH_ISSUER" || -z "$AUTH_AUDIENCE" ]]; then
  echo "Usage: $0 <project_id> <region> <auth_issuer> <auth_audience> [auth_jwks_url] [auth_tenant_claims] [auth_require_tenant_claim]"
  exit 1
fi

COMMON_ENV="AUTH_ENABLED=true#AUTH_ISSUER=${AUTH_ISSUER}#AUTH_AUDIENCE=${AUTH_AUDIENCE}#AUTH_REQUIRE_TENANT_CLAIM=${AUTH_REQUIRE_TENANT_CLAIM}#AUTH_TENANT_CLAIMS=${AUTH_TENANT_CLAIMS}#AUTH_ALGORITHMS=RS256"
if [[ -n "$AUTH_JWKS_URL" ]]; then
  COMMON_ENV="${COMMON_ENV}#AUTH_JWKS_URL=${AUTH_JWKS_URL}"
fi

echo "Applying OIDC auth settings to ingestion-api-service..."
gcloud run services update ingestion-api-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "^#^${COMMON_ENV}" \
  --quiet >/dev/null

echo "Applying OIDC auth settings to rag-query-service..."
gcloud run services update rag-query-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "^#^${COMMON_ENV}" \
  --quiet >/dev/null

echo "Applying OIDC auth settings to document-processor-service..."
gcloud run services update document-processor-service \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --update-env-vars "^#^${COMMON_ENV}#AUTH_ALLOW_UNAUTHENTICATED_PUBSUB=true" \
  --quiet >/dev/null

echo "P3.3 OIDC auth settings applied."
echo "Note: /v1/process/pubsub remains allowed without bearer token until Pub/Sub push OIDC is configured."
echo "Next step: ./scripts/apply_p3_pubsub_push_oidc.sh ${PROJECT_ID} ${REGION}"
