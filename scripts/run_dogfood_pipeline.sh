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
  echo '[dogfood] Claude tool recovery captures'
  python3 scripts/capture_claude_agent_evidence.py > "$OUT/claude.json"
fi

if [[ "${RUN_REAL_CORPUS:-1}" == 1 ]]; then
  : "${N8N_EVAL_EMAIL:?set the disposable n8n owner email}"
  : "${N8N_EVAL_PASSWORD:?set the disposable n8n owner password}"
  : "${N8N_EVAL_KEY:?set the disposable n8n evaluation key}"
  echo '[dogfood] fresh real P0/P1 corpus'
  N8N_EVAL_URL="$PISAMA_N8N_URL" python3 eval/generate_real_corpus.py > "$OUT/core-corpus.log"
fi

echo '[dogfood] current-build core gate'
python3 scripts/audit_dogfood_corpus.py \
  --server-url "$PISAMA_SERVER_URL" --api-key "$PISAMA_API_KEY" \
  --require-profile core --require-current-build --output "$OUT/audit.json"

if [[ "${RUN_UPGRADE_GATE:-1}" == 1 ]]; then
  echo '[dogfood] SQLite upgrade/backup/restore gate'
  python3 scripts/verify_n8n_upgrade_restore.py > "$OUT/upgrade-restore.json"
fi

echo "[dogfood] PASS: evidence written to $OUT"
