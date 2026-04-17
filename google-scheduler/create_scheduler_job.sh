#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PROJECT_ID:-}" || -z "${LOCATION:-}" || -z "${GITHUB_PAT:-}" ]]; then
  cat <<EOF
Usage: PROJECT_ID=<project> LOCATION=<location> GITHUB_PAT=<token> bash google-scheduler/create_scheduler_job.sh

Required environment variables:
  PROJECT_ID  - Google Cloud project ID
  LOCATION    - Cloud Scheduler location (e.g. asia-northeast3)
  GITHUB_PAT  - GitHub personal access token with Actions permissions
EOF
  exit 1
fi

JOB_NAME="optimize-dispatch"
URI="https://api.github.com/repos/wansang/finance/actions/workflows/optimize.yml/dispatches"
SCHEDULE="0 0 * * 6"  # UTC: Saturday 00:00 => KST Saturday 09:00

gcloud scheduler jobs create http "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$LOCATION" \
  --schedule="$SCHEDULE" \
  --time-zone="UTC" \
  --uri="$URI" \
  --http-method=POST \
  --headers="Content-Type=application/json","Accept=application/vnd.github+json","Authorization=Bearer $GITHUB_PAT" \
  --message-body='{"ref":"main"}'

echo "Created Cloud Scheduler job: $JOB_NAME"
