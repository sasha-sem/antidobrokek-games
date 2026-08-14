#!/usr/bin/env bash
set -euo pipefail

base_url="${QUIZ_URL:-http://localhost}"
admin_token="${ADMIN_TOKEN:?Set ADMIN_TOKEN in the environment}"
output="${1:-dobrokek-meme-stats.csv}"

curl --fail --show-error --silent \
    -H "X-Admin-Token: ${admin_token}" \
    "${base_url%/}/api/admin/meme-stats.csv" \
    --output "${output}"

echo "Statistics exported: ${output}"
