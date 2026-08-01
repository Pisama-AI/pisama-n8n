#!/usr/bin/env bash
# Start a local n8n, Pisama API, and dashboard backed by real captured executions.
set -euo pipefail

DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_STATE_DIR="${PISAMA_DEMO_STATE_DIR:-/tmp/pisama-n8n-demo-${UID}}"
DEMO_API_PORT="${PISAMA_DEMO_API_PORT:-8400}"
DEMO_DASHBOARD_PORT="${PISAMA_DEMO_DASHBOARD_PORT:-3555}"
DEMO_N8N_PORT="${PISAMA_DEMO_N8N_PORT:-5678}"
DEMO_API_KEY="${PISAMA_DEMO_API_KEY:-pisama-local-demo-key}"
DEMO_PYTHON="${PISAMA_DEMO_PYTHON:-$DEMO_ROOT/.venv-demo/bin/python}"
DEMO_FIXTURE="$DEMO_ROOT/server/tests/fixtures/executions/data_contract/CLOUD-112117-missing-required-value.json"
DEMO_MANIFEST="$DEMO_ROOT/eval/closed_loop_cases.json"
DEMO_CSV="$DEMO_STATE_DIR/pisama-clear-error-cases.csv"
DEMO_PIDS=()

mkdir -p "$DEMO_STATE_DIR"

cleanup() {
  if ((${#DEMO_PIDS[@]})); then
    kill "${DEMO_PIDS[@]}" >/dev/null 2>&1 || true
    wait "${DEMO_PIDS[@]}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

wait_for_url() {
  local label="$1"
  local url="$2"
  for _ in $(seq 1 90); do
    if curl --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "FAIL: $label did not start. See $DEMO_STATE_DIR/$label.log" >&2
  exit 1
}

if [[ ! -x "$DEMO_PYTHON" ]]; then
  command -v uv >/dev/null || {
    echo "FAIL: install uv or set PISAMA_DEMO_PYTHON to a Python 3.11 environment." >&2
    exit 1
  }
  DEMO_VENV_DIR="$(dirname "$(dirname "$DEMO_PYTHON")")"
  uv venv --python 3.11 "$DEMO_VENV_DIR"
fi

if ! "$DEMO_PYTHON" -c 'import fastapi, sqlalchemy, uvicorn' >/dev/null 2>&1; then
  uv pip install --python "$DEMO_PYTHON" -e "$DEMO_ROOT/engine" -e "$DEMO_ROOT/server"
fi

if [[ ! -x "$DEMO_ROOT/dashboard/node_modules/.bin/next" ]]; then
  (cd "$DEMO_ROOT/dashboard" && npm ci)
fi

"$DEMO_PYTHON" - "$DEMO_ROOT" "$DEMO_MANIFEST" "$DEMO_CSV" <<'PY'
import csv
import json
import sys
from pathlib import Path

root, manifest_path, output_path = map(Path, sys.argv[1:])
manifest = json.loads(manifest_path.read_text())
clear_errors = [case for case in manifest["cases"] if case["expected_modes"]][:4]
with output_path.open("w", newline="") as output:
    writer = csv.DictWriter(
        output,
        fieldnames=["dataset_id", "case_id", "execution_payload", "expected_modes", "label_evidence"],
    )
    writer.writeheader()
    for case in clear_errors:
        writer.writerow(
            {
                "dataset_id": "pisama-closed-loop-v1",
                "case_id": case["id"],
                "execution_payload": json.dumps(json.loads((root / case["payload_path"]).read_text())),
                "expected_modes": json.dumps(case["expected_modes"]),
                "label_evidence": " ".join(case["label_evidence"]),
            }
        )
PY

if ! curl --fail --silent --max-time 2 "http://127.0.0.1:$DEMO_N8N_PORT/healthz" >/dev/null 2>&1; then
  command -v n8n >/dev/null || {
    echo "FAIL: n8n is not running and the n8n command is unavailable." >&2
    exit 1
  }
  (
    export N8N_PORT="$DEMO_N8N_PORT"
    export N8N_SECURE_COOKIE=false
    export N8N_DIAGNOSTICS_ENABLED=false
    exec n8n start
  ) >"$DEMO_STATE_DIR/n8n.log" 2>&1 &
  DEMO_PIDS+=("$!")
fi
wait_for_url n8n "http://127.0.0.1:$DEMO_N8N_PORT/healthz"

if curl --silent --max-time 2 "http://127.0.0.1:$DEMO_API_PORT/healthz" >/dev/null 2>&1; then
  echo "FAIL: port $DEMO_API_PORT already has a Pisama server. Stop it or set PISAMA_DEMO_API_PORT." >&2
  exit 1
fi
(
  cd "$DEMO_ROOT"
  export DATABASE_URL="sqlite:///$DEMO_STATE_DIR/pisama-demo.db"
  export PISAMA_API_KEY="$DEMO_API_KEY"
  export PISAMA_CORS_ORIGINS="http://127.0.0.1:$DEMO_DASHBOARD_PORT,http://localhost:$DEMO_DASHBOARD_PORT"
  DEMO_BUILD_REVISION="$(git rev-parse HEAD)"
  export PISAMA_BUILD_REVISION="$DEMO_BUILD_REVISION"
  export PYTHONPATH="$DEMO_ROOT/engine:$DEMO_ROOT/server"
  exec "$DEMO_PYTHON" -m uvicorn pisama_n8n_server.app:app \
    --host 127.0.0.1 --port "$DEMO_API_PORT"
) >"$DEMO_STATE_DIR/pisama-api.log" 2>&1 &
DEMO_PIDS+=("$!")
wait_for_url pisama-api "http://127.0.0.1:$DEMO_API_PORT/healthz"

DEMO_AUTH_HEADER="Authorization: Bearer $DEMO_API_KEY"
DEMO_DETECTION_COUNT="$(
  curl --fail --silent --show-error \
    -H "$DEMO_AUTH_HEADER" \
    "http://127.0.0.1:$DEMO_API_PORT/api/v1/detections" \
  | "$DEMO_PYTHON" -c 'import json,sys; print(len(json.load(sys.stdin)))'
)"
if [[ "$DEMO_DETECTION_COUNT" == "0" ]]; then
  curl --fail --silent --show-error \
    -X POST "http://127.0.0.1:$DEMO_API_PORT/api/v1/n8n/webhook" \
    -H "$DEMO_AUTH_HEADER" \
    -H "Content-Type: application/json" \
    --data-binary "@$DEMO_FIXTURE" >/dev/null
fi

if curl --silent --max-time 2 "http://127.0.0.1:$DEMO_DASHBOARD_PORT" >/dev/null 2>&1; then
  echo "FAIL: port $DEMO_DASHBOARD_PORT is already in use. Stop it or set PISAMA_DEMO_DASHBOARD_PORT." >&2
  exit 1
fi
(
  cd "$DEMO_ROOT/dashboard"
  export NEXT_PUBLIC_SAAS=0
  export NEXT_PUBLIC_API_BASE="http://127.0.0.1:$DEMO_API_PORT"
  export NEXT_PUBLIC_API_KEY="$DEMO_API_KEY"
  exec npm run dev -- --hostname 127.0.0.1 --port "$DEMO_DASHBOARD_PORT"
) >"$DEMO_STATE_DIR/dashboard.log" 2>&1 &
DEMO_PIDS+=("$!")
wait_for_url dashboard "http://127.0.0.1:$DEMO_DASHBOARD_PORT"

echo
echo "Pisama closed-loop demo is ready."
echo "  n8n:       http://127.0.0.1:$DEMO_N8N_PORT"
echo "  dashboard: http://127.0.0.1:$DEMO_DASHBOARD_PORT/detections"
echo "  API:       http://127.0.0.1:$DEMO_API_PORT"
echo "  dataset:   $DEMO_CSV"
echo "  workflow:  $DEMO_ROOT/examples/pisama-closed-loop-evaluation.json"
echo
echo "The dashboard already contains one real captured failure."
echo "For n8n Evaluation, import the dataset CSV into a Data table and select it in the workflow."
echo "For locally installed n8n, change both Pisama URLs to http://127.0.0.1:$DEMO_API_PORT."
echo "Use Header Auth with Authorization: Bearer $DEMO_API_KEY."
echo "Press Ctrl-C to stop the services started by this command."

wait
