#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
OUT_DIR="${2:-./snapshots}"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="${OUT_DIR}/${PROJECT_ID}-${TS}"

mkdir -p "$DEST"

gcloud config set project "$PROJECT_ID" >/dev/null

gcloud run services list --format=json > "$DEST/run-services.json"
gcloud run services describe my-first-app --region=europe-west4 --format=json > "$DEST/run-my-first-app.json"
gcloud sql instances list --format=json > "$DEST/sql-instances.json"
gcloud sql instances describe alchimista-test-db --format=json > "$DEST/sql-alchimista-test-db.json"
gcloud compute networks list --format=json > "$DEST/networks.json"
gcloud compute networks vpc-access connectors list --region=europe-west4 --format=json > "$DEST/vpc-connectors-europe-west4.json"
gcloud compute addresses list --global --format=json > "$DEST/global-addresses.json"
gcloud services list --enabled --format=json > "$DEST/enabled-services.json"

echo "Snapshot written to: $DEST"
