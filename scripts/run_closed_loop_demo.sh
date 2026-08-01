#!/usr/bin/env bash
# Launch an isolated, pre-provisioned 19-case n8n and Pisama closed-loop demo.
set -euo pipefail

DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO_STATE_DIR="${PISAMA_DEMO_STATE_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/pisama-n8n-demo.XXXXXX")}"
DEMO_API_PORT="${PISAMA_DEMO_API_PORT:-8400}"
DEMO_DASHBOARD_PORT="${PISAMA_DEMO_DASHBOARD_PORT:-3555}"
DEMO_N8N_PORT="${PISAMA_DEMO_N8N_PORT:-5678}"
DEMO_N8N_BROKER_PORT="${PISAMA_DEMO_N8N_BROKER_PORT:-5680}"
DEMO_PYTHON="${PISAMA_DEMO_PYTHON:-$DEMO_ROOT/.venv-demo/bin/python}"
DEMO_N8N_VERSION="2.32.7"
DEMO_N8N_LICENSE_KEY="${PISAMA_DEMO_N8N_LICENSE_KEY:-}"
DEMO_PIDS=()

random_secret() {
  if command -v openssl >/dev/null; then
    openssl rand -hex 32
  else
    "$DEMO_PYTHON" -c 'import secrets; print(secrets.token_hex(32))'
  fi
}

random_password() {
  if command -v openssl >/dev/null; then
    openssl rand -hex 20
  else
    "$DEMO_PYTHON" -c 'import secrets; print(secrets.token_hex(20))'
  fi
}

DEMO_API_KEY="${PISAMA_DEMO_API_KEY:-$(random_secret)}"
DEMO_HOLDOUT_KEY="${PISAMA_DEMO_HOLDOUT_KEY:-$(random_secret)}"
DEMO_N8N_PASSWORD="${PISAMA_DEMO_N8N_PASSWORD:-Pisama-$(random_password)}"
DEMO_N8N_ENCRYPTION_KEY="${PISAMA_DEMO_N8N_ENCRYPTION_KEY:-$(random_secret)}"
DEMO_DATABASE_URL="sqlite:///$DEMO_STATE_DIR/pisama-demo.db"

mkdir -p "$DEMO_STATE_DIR/n8n"

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
  for _ in $(seq 1 180); do
    if curl --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "FAIL: $label did not start. See $DEMO_STATE_DIR/$label.log" >&2
  exit 1
}

wait_for_json_data() {
  local label="$1"
  local url="$2"
  for _ in $(seq 1 180); do
    if curl --fail --silent --max-time 2 "$url" 2>/dev/null \
      | "$DEMO_PYTHON" -c 'import json,sys; assert isinstance(json.load(sys.stdin).get("data"), dict)' \
      >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  echo "FAIL: $label did not become ready at $url" >&2
  exit 1
}

require_free_port() {
  local label="$1"
  local url="$2"
  if curl --silent --max-time 2 "$url" >/dev/null 2>&1; then
    echo "FAIL: $label port is already in use. Choose another PISAMA_DEMO_*_PORT." >&2
    exit 1
  fi
}

if [[ ! -x "$DEMO_PYTHON" ]]; then
  command -v uv >/dev/null || {
    echo "FAIL: install uv or set PISAMA_DEMO_PYTHON to Python 3.11." >&2
    exit 1
  }
  uv venv --python 3.11 "$(dirname "$(dirname "$DEMO_PYTHON")")"
fi

if ! "$DEMO_PYTHON" -c 'import fastapi, httpx, sqlalchemy, uvicorn' >/dev/null 2>&1; then
  uv pip install --python "$DEMO_PYTHON" -e "$DEMO_ROOT/engine" -e "$DEMO_ROOT/server"
fi

if [[ ! -x "$DEMO_ROOT/dashboard/node_modules/.bin/next" ]]; then
  (cd "$DEMO_ROOT/dashboard" && npm ci)
fi
command -v npx >/dev/null || {
  echo "FAIL: npx is required to run the pinned n8n $DEMO_N8N_VERSION package." >&2
  exit 1
}

require_free_port n8n "http://127.0.0.1:$DEMO_N8N_PORT/healthz"
require_free_port pisama-api "http://127.0.0.1:$DEMO_API_PORT/healthz"
require_free_port dashboard "http://127.0.0.1:$DEMO_DASHBOARD_PORT"

DEMO_BUILD_REVISION="$(git -C "$DEMO_ROOT" rev-parse HEAD)"
if [[ -n "$(git -C "$DEMO_ROOT" status --porcelain)" ]]; then
  DEMO_BUILD_REVISION="$DEMO_BUILD_REVISION-dirty"
fi
export PYTHONPATH="$DEMO_ROOT/engine:$DEMO_ROOT/server"
export PISAMA_BUILD_REVISION="$DEMO_BUILD_REVISION"

"$DEMO_PYTHON" "$DEMO_ROOT/scripts/import_closed_loop_corpus.py" \
  --database-url "$DEMO_DATABASE_URL" >"$DEMO_STATE_DIR/corpus-import.json"

(
  export N8N_USER_FOLDER="$DEMO_STATE_DIR/n8n"
  export N8N_PORT="$DEMO_N8N_PORT"
  export N8N_RUNNERS_BROKER_PORT="$DEMO_N8N_BROKER_PORT"
  export N8N_ENCRYPTION_KEY="$DEMO_N8N_ENCRYPTION_KEY"
  export N8N_SECURE_COOKIE=false
  export N8N_DIAGNOSTICS_ENABLED=false
  export N8N_PERSONALIZATION_ENABLED=false
  export N8N_VERSION_NOTIFICATIONS_ENABLED=false
  if [[ -n "$DEMO_N8N_LICENSE_KEY" ]]; then
    export N8N_LICENSE_ACTIVATION_KEY="$DEMO_N8N_LICENSE_KEY"
  fi
  exec npx --yes "n8n@$DEMO_N8N_VERSION" start
) >"$DEMO_STATE_DIR/n8n.log" 2>&1 &
DEMO_PIDS+=("$!")
wait_for_url n8n "http://127.0.0.1:$DEMO_N8N_PORT/healthz"
wait_for_json_data n8n-rest "http://127.0.0.1:$DEMO_N8N_PORT/rest/settings"

(
  cd "$DEMO_ROOT"
  export DATABASE_URL="$DEMO_DATABASE_URL"
  export PISAMA_ENV=production
  export PISAMA_API_KEY="$DEMO_API_KEY"
  export PISAMA_HOLDOUT_ADMIN_KEY="$DEMO_HOLDOUT_KEY"
  export PISAMA_CORS_ORIGINS="http://127.0.0.1:$DEMO_DASHBOARD_PORT,http://localhost:$DEMO_DASHBOARD_PORT"
  exec "$DEMO_PYTHON" -m uvicorn pisama_n8n_server.app:app \
    --host 127.0.0.1 --port "$DEMO_API_PORT"
) >"$DEMO_STATE_DIR/pisama-api.log" 2>&1 &
DEMO_PIDS+=("$!")
wait_for_url pisama-api "http://127.0.0.1:$DEMO_API_PORT/healthz"

"$DEMO_PYTHON" "$DEMO_ROOT/scripts/bootstrap_closed_loop_demo.py" \
  --root "$DEMO_ROOT" \
  --n8n-url "http://127.0.0.1:$DEMO_N8N_PORT" \
  --n8n-password "$DEMO_N8N_PASSWORD" \
  --pisama-api-url "http://127.0.0.1:$DEMO_API_PORT" \
  --pisama-api-key "$DEMO_API_KEY" \
  --holdout-key "$DEMO_HOLDOUT_KEY" \
  --baseline-revision "$DEMO_BUILD_REVISION-baseline" \
  >"$DEMO_STATE_DIR/bootstrap.json"

(
  cd "$DEMO_ROOT/dashboard"
  export NEXT_PUBLIC_SAAS=0
  export NEXT_PUBLIC_API_BASE="http://127.0.0.1:$DEMO_API_PORT"
  export NEXT_PUBLIC_API_KEY="$DEMO_API_KEY"
  npm run build
  exec npm run start -- --hostname 127.0.0.1 --port "$DEMO_DASHBOARD_PORT"
) >"$DEMO_STATE_DIR/dashboard.log" 2>&1 &
DEMO_PIDS+=("$!")
wait_for_url dashboard "http://127.0.0.1:$DEMO_DASHBOARD_PORT"

DEMO_WORKFLOW_ID="$("$DEMO_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["n8n"]["workflow_id"])' "$DEMO_STATE_DIR/bootstrap.json")"
DEMO_RUN_ID="$("$DEMO_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["pisama"]["evaluation_run_id"])' "$DEMO_STATE_DIR/bootstrap.json")"

echo
echo "Pisama closed-loop demo is ready with all 19 verified cases."
echo "  n8n workflow: http://127.0.0.1:$DEMO_N8N_PORT/workflow/$DEMO_WORKFLOW_ID"
echo "  n8n login:    demo@pisama.local"
echo "  n8n password: $DEMO_N8N_PASSWORD"
echo "  dashboard:    http://127.0.0.1:$DEMO_DASHBOARD_PORT/evaluation"
echo "  audit run:    $DEMO_RUN_ID"
echo "  state:        $DEMO_STATE_DIR"
echo
echo "The n8n data table, 19-case workflow, Pisama corpus, sealed holdout protocol,"
echo "and immutable score run were provisioned automatically. Press Ctrl-C to stop."
if [[ -z "$DEMO_N8N_LICENSE_KEY" ]]; then
  echo "Pisama's full audit loop is active. n8n's native batch Evaluations UI requires"
  echo "a registered or licensed instance. Register it in n8n, or set"
  echo "PISAMA_DEMO_N8N_LICENSE_KEY for licensed self-hosting."
fi

wait
