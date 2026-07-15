#!/usr/bin/env bash
# Seed a deployed pisama-n8n server with the bundled REAL captured execution fixtures.
#   PISAMA_API_KEY=<key> scripts/seed_hosted.sh https://pisama-n8n-api.fly.dev
set -euo pipefail

BASE="${1:?usage: PISAMA_API_KEY=<key> seed_hosted.sh <server-base-url>}"
: "${PISAMA_API_KEY:?set PISAMA_API_KEY}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURES="$REPO/server/tests/fixtures/executions"

count=0
for f in "$FIXTURES"/{timeout,error,resource,healthy}/*.json; do
  code=$(curl -s -m 30 -o /dev/null -w '%{http_code}' -X POST "$BASE/api/v1/n8n/webhook" \
    -H "Authorization: Bearer $PISAMA_API_KEY" \
    -H "Content-Type: application/json" \
    --data-binary @"$f")
  [[ "$code" == "200" ]] && count=$((count+1)) || echo "  WARN: $f -> $code" >&2
done

echo "seeded $count executions"
fired=$(curl -s -m 15 "$BASE/api/v1/detections" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(1 for r in d if r['detected']))")
echo "detections fired on server: $fired"
