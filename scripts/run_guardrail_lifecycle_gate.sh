#!/usr/bin/env bash
# Self-contained guardrail-lifecycle gate for the dogfood pipeline.
#
# Stands up a THROWAWAY local n8n (docker) + a fresh local Pisama server, runs the full
# install/verify/rollback guardrail lifecycle against them, and tears everything down.
# It deliberately does NOT touch the founder's n8n Cloud or the deployed server: the
# lifecycle installs a guard into a live workflow and rolls it back, and needs a clean
# server DB for the reliability case, so isolation matters. Fail-closed: any failure to
# stand up the stack, or any lifecycle-stage failure, exits non-zero.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PISAMA_PY:-python3}"
# Auto-pick free ports unless pinned, so repeated runs never collide on a held port.
_free_port() { "$PY" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()"; }
N8N_PORT="${GUARDRAIL_GATE_N8N_PORT:-$(_free_port)}"
SRV_PORT="${GUARDRAIL_GATE_SERVER_PORT:-$(_free_port)}"
# Pin the n8n image to the version the lifecycle is proven on (webhookId registration).
N8N_VERSION="${GUARDRAIL_GATE_N8N_VERSION:-1.70.0}"
CONTAINER="n8n-guardrail-gate-$$-$(date +%s)"
WORKDIR="$(mktemp -d)"
SRV_PID=""

cleanup() {
  if [ -n "$SRV_PID" ]; then
    kill "$SRV_PID" 2>/dev/null || true
    wait "$SRV_PID" 2>/dev/null || true  # reap it quietly (no "Terminated" job message)
  fi
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

# A plain `docker run` with NO volume: a guaranteed-fresh n8n every run (owner setup
# always succeeds), rather than the compose lane's persistent dogfood volume.
echo "[guardrail-gate] starting throwaway n8n ${N8N_VERSION} (port $N8N_PORT)"
docker run -d --rm --name "$CONTAINER" -p "$N8N_PORT:5678" \
  -e N8N_ENCRYPTION_KEY=guardrailgate0123456789 \
  -e N8N_SECURE_COOKIE=false \
  "n8nio/n8n:$N8N_VERSION" >/dev/null
for _ in $(seq 1 60); do
  curl -sf "http://localhost:$N8N_PORT/healthz" >/dev/null 2>&1 && break
  sleep 2
done
curl -sf "http://localhost:$N8N_PORT/healthz" >/dev/null || {
  echo "[guardrail-gate] n8n did not become healthy" >&2; exit 1; }
sleep 3  # let n8n's REST controllers finish warming before owner setup

echo "[guardrail-gate] provisioning n8n owner + API key"
N8N_KEY="$("$PY" - "http://localhost:$N8N_PORT" <<'PROVISION'
import json, sys, time, urllib.request, http.cookiejar, urllib.error
base = sys.argv[1]
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def req(path, data=None, method="POST"):
    r = urllib.request.Request(f"{base}{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"}, method=method)
    try:
        resp = op.open(r, timeout=20)
        raw, status = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except Exception:
        return 0, {}
    try:
        return status, (json.loads(raw) if raw else {})
    except Exception:
        return status, {}  # n8n can return non-JSON while its REST layer is still warming
owner = {"email": "guard-gate@pisama.test", "firstName": "Pisama", "lastName": "Guard",
         "password": "GuardGate123!"}
# owner setup (400 = already set up on a reused volume) then login if no cookie
for _ in range(30):
    st, _ = req("/rest/owner/setup", owner)
    if st in (200, 201, 400):
        break
    time.sleep(1)
if not any(c.name == "n8n-auth" for c in cj):
    req("/rest/login", {"email": owner["email"], "password": owner["password"]})
# fresh key (delete any existing so the label/limit never blocks creation)
st, existing = req("/rest/api-keys", method="GET")
for k in (existing.get("data") or []):
    req(f"/rest/api-keys/{k.get('id')}", method="DELETE")
st, made = req("/rest/api-keys", {"label": "guardrail-gate", "expiresAt": None})
data = made.get("data") or {}
key = data.get("apiKey") or data.get("rawApiKey") or ""
print(key)
PROVISION
)"
[ -n "$N8N_KEY" ] || { echo "[guardrail-gate] failed to provision an n8n API key" >&2; exit 1; }

echo "[guardrail-gate] starting a fresh Pisama server wired to the throwaway n8n"
PISAMA_API_KEY=guardrail-gate-key \
PISAMA_N8N_URL="http://localhost:$N8N_PORT" \
PISAMA_N8N_API_KEY="$N8N_KEY" \
DATABASE_URL="sqlite:///$WORKDIR/gate.db" \
  "$PY" -m uvicorn pisama_n8n_server.app:app --host 127.0.0.1 --port "$SRV_PORT" \
  >"$WORKDIR/server.log" 2>&1 &
SRV_PID=$!
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$SRV_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:$SRV_PORT/healthz" >/dev/null || {
  echo "[guardrail-gate] server did not start:" >&2; cat "$WORKDIR/server.log" >&2; exit 1; }

echo "[guardrail-gate] running the full install -> verify -> rollback lifecycle"
PISAMA_N8N_URL="http://localhost:$N8N_PORT" PISAMA_N8N_API_KEY="$N8N_KEY" \
PISAMA_SERVER_URL="http://127.0.0.1:$SRV_PORT" PISAMA_API_KEY=guardrail-gate-key \
  "$PY" scripts/run_guardrail_lifecycle.py

echo "[guardrail-gate] PASS"
