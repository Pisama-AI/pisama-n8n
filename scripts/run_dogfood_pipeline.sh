#!/usr/bin/env bash
# Run the real n8n evidence pipeline.  This is intentionally fail-closed:
# missing credentials or stale build provenance stop the run rather than
# producing a report that looks complete.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
: "${PISAMA_N8N_URL:?set the disposable n8n URL}"
: "${PISAMA_N8N_API_KEY:?set the scoped n8n API key}"
: "${PISAMA_API_KEY:?set the Pisama dogfood API key}"
: "${PISAMA_SERVER_URL:?set the Pisama dogfood server URL}"
: "${ANTHROPIC_API_KEY:?set the Anthropic dogfood key}"
: "${PISAMA_BUILD_REVISION:?set the deployed commit revision}"

export PYTHONPATH="$ROOT/engine${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "${DOGFOOD_ARTIFACT_DIR:-artifacts/dogfood}"
OUT="${DOGFOOD_ARTIFACT_DIR:-artifacts/dogfood}/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"

echo '[dogfood] native structured-output and recovery captures'
python3 scripts/capture_native_agent_evidence.py --extended > "$OUT/native.json"

if [[ "${RUN_CLAUDE_CAPTURE:-1}" == 1 ]]; then
  echo '[dogfood] fresh API-only Claude P0/P1 corpus'
  python3 scripts/capture_claude_agent_evidence.py --core > "$OUT/core-corpus.json"
fi

echo '[dogfood] current-build core gate'
python3 scripts/audit_dogfood_corpus.py \
  --server-url "$PISAMA_SERVER_URL" --api-key "$PISAMA_API_KEY" \
  --require-profile core --require-current-build \
  --require agent_diagnostics:n8n_native_structured_parser_rejection \
  --output "$OUT/audit.json"

if [[ "${REQUIRE_REPAIR_EVIDENCE:-1}" == 1 ]]; then
  python3 - "$PISAMA_SERVER_URL" "$PISAMA_API_KEY" <<'PY'
import json, sys, urllib.request
url, key = sys.argv[1:]
r = urllib.request.Request(url.rstrip('/') + '/api/v1/operations/summary',
                           headers={'Authorization': 'Bearer ' + key})
with urllib.request.urlopen(r, timeout=20) as response:
    summary = json.load(response)
statuses = summary.get('repairs_by_status', {})
if not statuses.get('rolled_back'):
    raise SystemExit('repair evidence missing: run detect -> review -> apply -> observe -> rollback')
print('[dogfood] repair lifecycle evidence present:', statuses)
PY
fi

if [[ "${RUN_UPGRADE_GATE:-1}" == 1 ]]; then
  echo '[dogfood] SQLite upgrade/backup/restore gate'
  python3 scripts/verify_n8n_upgrade_restore.py > "$OUT/upgrade-restore.json"
fi

echo "[dogfood] PASS: evidence written to $OUT"
