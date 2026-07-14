#!/usr/bin/env bash
# Self-host smoke gate: bring the server up via docker compose and prove it detects a
# real n8n failure over HTTP, then tear down. Requires docker + a captured fixture.
#
#   scripts/verify_selfhost.sh [path-to-execution-fixture.json]
#
# Exit 0 = the containerized server booted, ingested the fixture, fired the expected
# detector, and persisted it. Non-zero = self-host is broken.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="${1:-$REPO/../pisama-worktrees/n8n-eval-harness/n8n-workflows/executions/error/ERROR-01-throw.json}"
KEY="selfhost-smoke-key"
PORT=8400

if [[ ! -f "$FIXTURE" ]]; then
  echo "FAIL: fixture not found: $FIXTURE" >&2; exit 1
fi

cleanup() { (cd "$REPO/deploy" && docker compose down -v >/dev/null 2>&1) || true; }
trap cleanup EXIT

echo "[selfhost] docker compose up --build ..."
(cd "$REPO/deploy" && PISAMA_API_KEY="$KEY" docker compose up -d --build server)

echo "[selfhost] waiting for health ..."
for _ in $(seq 1 30); do
  s=$(cd "$REPO/deploy" && docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q server)" 2>/dev/null || echo starting)
  [[ "$s" == "healthy" ]] && break
  sleep 3
done

code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/healthz")
[[ "$code" == "200" ]] || { echo "FAIL: /healthz returned $code" >&2; exit 1; }

fired=$(curl -s -m 10 -X POST "http://127.0.0.1:$PORT/api/v1/n8n/webhook" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  --data-binary @"$FIXTURE" \
  | python3 -c "import sys,json;print(','.join(d['detector'] for d in json.load(sys.stdin).get('detections',[]) if d.get('detected')))")

echo "[selfhost] fired detectors: ${fired:-<none>}"
[[ -n "$fired" ]] || { echo "FAIL: no detection fired on a real failure fixture" >&2; exit 1; }

stored=$(curl -s -m 5 "http://127.0.0.1:$PORT/api/v1/detections" -H "Authorization: Bearer $KEY" \
  | python3 -c "import sys,json;print(len(json.load(sys.stdin)))")
[[ "$stored" -gt 0 ]] || { echo "FAIL: detections did not persist" >&2; exit 1; }

echo "PASS: self-host server detects+persists a real n8n failure over HTTP ($stored rows)."
