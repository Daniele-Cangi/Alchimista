#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
SERVICE_NAME="${2:-my-first-app}"
BUCKET="run-sources-${PROJECT_ID}-us-central1"
DEST="${3:-./_archive/from-run-sources}"

mkdir -p "$DEST"

OBJ="$(gcloud storage ls gs://${BUCKET}/services/${SERVICE_NAME}/*.zip | sort | tail -n1)"

echo "Downloading: $OBJ"
gcloud storage cp "$OBJ" "$DEST/latest.zip"
unzip -o "$DEST/latest.zip" -d "$DEST/latest" >/dev/null

echo "Recovered source at: $DEST/latest"
