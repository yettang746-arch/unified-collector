#!/bin/bash
# Trigger daily collection via API
# Usage: bash trigger-collect.sh
set -e

API_URL="${COLLECTOR_URL:-https://collector.255202.xyz}"
API_KEY="${API_KEY:-cbtc_2026_k3y}"

echo "🚀 Triggering collection at $(date)"
curl -s -X POST "${API_URL}/api/v1/collect" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" | python3 -m json.tool

echo ""
echo "📊 Stats:"
curl -s "${API_URL}/api/v1/articles/stats" \
  -H "Authorization: Bearer ${API_KEY}" | python3 -m json.tool
