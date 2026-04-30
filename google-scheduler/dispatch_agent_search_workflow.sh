#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${GITHUB_PAT:-}" ]]; then
  echo "ERROR: GITHUB_PAT environment variable is required."
  echo "export GITHUB_PAT=your_token_here"
  exit 1
fi

curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GITHUB_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"ref":"main"}' \
  "https://api.github.com/repos/wansang/finance/actions/workflows/agent_search.yml/dispatches"

echo "Dispatched agent_search workflow to GitHub Actions."
