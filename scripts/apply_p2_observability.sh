#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-secure-electron-474908-k9}"
REGION="${2:-europe-west4}"

INGEST_SUBSCRIPTION="${INGEST_SUBSCRIPTION:-doc-ingest-sub}"
DLQ_SUBSCRIPTION="${DLQ_SUBSCRIPTION:-doc-ingest-topic-dlq-sub}"
PROCESSOR_SERVICE="${PROCESSOR_SERVICE:-document-processor-service}"
SQL_INSTANCE="${SQL_INSTANCE:-alchimista-test-db}"
NOTIFICATION_CHANNEL="${NOTIFICATION_CHANNEL:-}"

DASHBOARD_DISPLAY_NAME="${DASHBOARD_DISPLAY_NAME:-Alchimista P2 Operations}"

if [[ -z "$NOTIFICATION_CHANNEL" ]]; then
  NOTIFICATION_CHANNEL="$(
    gcloud alpha monitoring channels list \
      --project "$PROJECT_ID" \
      --format='value(name)' \
      | head -n 1
  )"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DASHBOARD_FILE="${TMP_DIR}/dashboard.json"
cat >"$DASHBOARD_FILE" <<EOF
{
  "displayName": "${DASHBOARD_DISPLAY_NAME}",
  "gridLayout": {
    "columns": "2",
    "widgets": [
      {
        "title": "Ingest Backlog Age (seconds)",
        "xyChart": {
          "dataSets": [
            {
              "legendTemplate": "${INGEST_SUBSCRIPTION}",
              "plotType": "LINE",
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\\" AND resource.type=\\"pubsub_subscription\\" AND resource.labels.subscription_id=\\"${INGEST_SUBSCRIPTION}\\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_MAX"
                  }
                }
              }
            }
          ]
        }
      },
      {
        "title": "DLQ Undelivered Messages",
        "xyChart": {
          "dataSets": [
            {
              "legendTemplate": "${DLQ_SUBSCRIPTION}",
              "plotType": "LINE",
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\\"pubsub.googleapis.com/subscription/num_undelivered_messages\\" AND resource.type=\\"pubsub_subscription\\" AND resource.labels.subscription_id=\\"${DLQ_SUBSCRIPTION}\\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_MAX"
                  }
                }
              }
            }
          ]
        }
      },
      {
        "title": "Processor P95 Request Latency",
        "xyChart": {
          "dataSets": [
            {
              "legendTemplate": "${PROCESSOR_SERVICE}",
              "plotType": "LINE",
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\\"run.googleapis.com/request_latencies\\" AND resource.type=\\"cloud_run_revision\\" AND resource.labels.service_name=\\"${PROCESSOR_SERVICE}\\"",
                  "aggregation": {
                    "alignmentPeriod": "120s",
                    "perSeriesAligner": "ALIGN_PERCENTILE_95"
                  }
                }
              }
            }
          ]
        }
      },
      {
        "title": "Cloud SQL Active Backends",
        "xyChart": {
          "dataSets": [
            {
              "legendTemplate": "${SQL_INSTANCE}",
              "plotType": "LINE",
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\\"cloudsql.googleapis.com/database/postgresql/num_backends\\" AND resource.type=\\"cloudsql_database\\" AND resource.labels.database_id=\\"${PROJECT_ID}:${SQL_INSTANCE}\\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_MAX"
                  }
                }
              }
            }
          ]
        }
      }
    ]
  }
}
EOF

dash_name="$(
  gcloud monitoring dashboards list \
    --project "$PROJECT_ID" \
    --filter="displayName=\"${DASHBOARD_DISPLAY_NAME}\"" \
    --format='value(name)' \
    | head -n 1
)"

if [[ -n "$dash_name" ]]; then
  jq --arg name "$dash_name" '.name = $name' "$DASHBOARD_FILE" >"${TMP_DIR}/dashboard.update.json"
  gcloud monitoring dashboards update \
    --project "$PROJECT_ID" \
    --config-from-file "${TMP_DIR}/dashboard.update.json" \
    >/dev/null
  echo "dashboard_updated=${dash_name}"
else
  gcloud monitoring dashboards create \
    --project "$PROJECT_ID" \
    --config-from-file "$DASHBOARD_FILE" \
    >/dev/null
  dash_name="$(
    gcloud monitoring dashboards list \
      --project "$PROJECT_ID" \
      --filter="displayName=\"${DASHBOARD_DISPLAY_NAME}\"" \
      --format='value(name)' \
      | head -n 1
  )"
  echo "dashboard_created=${dash_name}"
fi

create_or_update_policy() {
  local display_name="$1"
  local policy_file="$2"
  local existing
  existing="$(
    gcloud monitoring policies list \
      --project "$PROJECT_ID" \
      --filter="displayName=\"${display_name}\"" \
      --format='value(name)' \
      | head -n 1
  )"

  if [[ -n "$existing" ]]; then
    if [[ -n "$NOTIFICATION_CHANNEL" ]]; then
      gcloud monitoring policies update "$existing" \
        --project "$PROJECT_ID" \
        --policy-from-file "$policy_file" \
        --set-notification-channels "$NOTIFICATION_CHANNEL" \
        >/dev/null
    else
      gcloud monitoring policies update "$existing" \
        --project "$PROJECT_ID" \
        --policy-from-file "$policy_file" \
        >/dev/null
    fi
    echo "policy_updated=${display_name}"
  else
    if [[ -n "$NOTIFICATION_CHANNEL" ]]; then
      gcloud monitoring policies create \
        --project "$PROJECT_ID" \
        --policy-from-file "$policy_file" \
        --notification-channels "$NOTIFICATION_CHANNEL" \
        >/dev/null
    else
      gcloud monitoring policies create \
        --project "$PROJECT_ID" \
        --policy-from-file "$policy_file" \
        >/dev/null
    fi
    echo "policy_created=${display_name}"
  fi
}

POLICY_BACKLOG_FILE="${TMP_DIR}/policy_backlog.json"
cat >"$POLICY_BACKLOG_FILE" <<EOF
{
  "displayName": "Alchimista P2 Ingest Backlog Age",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Ingest subscription backlog age over 300s",
      "conditionThreshold": {
        "filter": "metric.type=\\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\\" AND resource.type=\\"pubsub_subscription\\" AND resource.labels.subscription_id=\\"${INGEST_SUBSCRIPTION}\\"",
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_MAX"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 300,
        "duration": "300s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "documentation": {
    "content": "Ingest backlog age is above 300 seconds. Check processor capacity and subscription health.",
    "mimeType": "text/markdown"
  },
  "enabled": true
}
EOF

POLICY_DLQ_FILE="${TMP_DIR}/policy_dlq.json"
cat >"$POLICY_DLQ_FILE" <<EOF
{
  "displayName": "Alchimista P2 DLQ Growth",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "DLQ has undelivered messages",
      "conditionThreshold": {
        "filter": "metric.type=\\"pubsub.googleapis.com/subscription/num_undelivered_messages\\" AND resource.type=\\"pubsub_subscription\\" AND resource.labels.subscription_id=\\"${DLQ_SUBSCRIPTION}\\"",
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_MAX"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "300s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "documentation": {
    "content": "DLQ contains pending messages. Use /v1/admin/replay-dlq after root-cause analysis.",
    "mimeType": "text/markdown"
  },
  "enabled": true
}
EOF

POLICY_P95_FILE="${TMP_DIR}/policy_p95.json"
cat >"$POLICY_P95_FILE" <<EOF
{
  "displayName": "Alchimista P2 Processor P95 Latency",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Processor p95 request latency is over 1000 ms",
      "conditionThreshold": {
        "filter": "metric.type=\\"run.googleapis.com/request_latencies\\" AND resource.type=\\"cloud_run_revision\\" AND resource.labels.service_name=\\"${PROCESSOR_SERVICE}\\"",
        "aggregations": [
          {
            "alignmentPeriod": "120s",
            "perSeriesAligner": "ALIGN_PERCENTILE_95"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 1000,
        "duration": "120s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "documentation": {
    "content": "Processor latency p95 is high. Verify OCR/parse load and Cloud SQL pressure.",
    "mimeType": "text/markdown"
  },
  "enabled": true
}
EOF

POLICY_SQL_FILE="${TMP_DIR}/policy_sql.json"
cat >"$POLICY_SQL_FILE" <<EOF
{
  "displayName": "Alchimista P2 Cloud SQL Connections",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Cloud SQL active backends above 80",
      "conditionThreshold": {
        "filter": "metric.type=\\"cloudsql.googleapis.com/database/postgresql/num_backends\\" AND resource.type=\\"cloudsql_database\\" AND resource.labels.database_id=\\"${PROJECT_ID}:${SQL_INSTANCE}\\"",
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_MAX"
          }
        ],
        "comparison": "COMPARISON_GT",
        "thresholdValue": 80,
        "duration": "300s",
        "trigger": {
          "count": 1
        }
      }
    }
  ],
  "documentation": {
    "content": "Cloud SQL backend connections are high. Verify connection pooling and processor concurrency.",
    "mimeType": "text/markdown"
  },
  "enabled": true
}
EOF

create_or_update_policy "Alchimista P2 Ingest Backlog Age" "$POLICY_BACKLOG_FILE"
create_or_update_policy "Alchimista P2 DLQ Growth" "$POLICY_DLQ_FILE"
create_or_update_policy "Alchimista P2 Processor P95 Latency" "$POLICY_P95_FILE"
create_or_update_policy "Alchimista P2 Cloud SQL Connections" "$POLICY_SQL_FILE"

if [[ -n "$NOTIFICATION_CHANNEL" ]]; then
  echo "notification_channel=${NOTIFICATION_CHANNEL}"
else
  echo "notification_channel=none"
fi
