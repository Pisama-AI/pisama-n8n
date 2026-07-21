#!/usr/bin/env bash
# Corpus guard campaign — LOCAL full-corpus run.
#
# Stands up a THROWAWAY docker n8n (the guardrail-gate pattern: pinned version,
# fresh volume-less container, owner + API-key mint) plus a fresh local Pisama
# server (SQLite in a workdir, NO background poll interval — the campaign driver is
# the single ingestion writer, which is what makes the success-count audit clean),
# then drives guard lifecycles across ALL manifest workflows and persists the
# artifacts. Containers are torn down; artifacts survive in eval/campaigns/.
#
# Honesty note: this stack exists because the founder's n8n Cloud has a shared
# execution quota (exhausted once before). Nothing here touches the Cloud instance.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PISAMA_PY:-python3}"
_free_port() { "$PY" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()"; }
N8N_PORT="${CAMPAIGN_N8N_PORT:-$(_free_port)}"
SRV_PORT="${CAMPAIGN_SERVER_PORT:-$(_free_port)}"
# Same pin as the lifecycle gate: the version the webhookId registration is proven on.
N8N_VERSION="${CAMPAIGN_N8N_VERSION:-1.70.0}"
CONTAINER="n8n-corpus-campaign-$$-$(date +%s)"
WORKDIR="${CAMPAIGN_WORKDIR:-$(mktemp -d)}"
OUT_DIR="eval/campaigns"
SRV_PID=""

cleanup() {
  if [ -n "$SRV_PID" ]; then
    kill "$SRV_PID" 2>/dev/null || true
    wait "$SRV_PID" 2>/dev/null || true
  fi
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  echo "[campaign] workdir kept for audit: $WORKDIR"
}
trap cleanup EXIT

echo "[campaign] manifest determinism check"
"$PY" scripts/corpus_campaign_prepare.py --check

echo "[campaign] starting throwaway n8n ${N8N_VERSION} (port $N8N_PORT)"
docker run -d --rm --name "$CONTAINER" -p "$N8N_PORT:5678" \
  -e N8N_ENCRYPTION_KEY=corpuscampaign0123456789 \
  -e N8N_SECURE_COOKIE=false \
  "n8nio/n8n:$N8N_VERSION" >/dev/null
for _ in $(seq 1 60); do
  curl -sf "http://localhost:$N8N_PORT/healthz" >/dev/null 2>&1 && break
  sleep 2
done
curl -sf "http://localhost:$N8N_PORT/healthz" >/dev/null || {
  echo "[campaign] n8n did not become healthy" >&2; exit 1; }
sleep 3

echo "[campaign] provisioning n8n owner + API key"
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
        return status, {}
owner = {"email": "corpus-campaign@pisama.test", "firstName": "Pisama",
         "lastName": "Campaign", "password": "CorpusCampaign123!"}
for _ in range(30):
    st, _ = req("/rest/owner/setup", owner)
    if st in (200, 201, 400):
        break
    time.sleep(1)
if not any(c.name == "n8n-auth" for c in cj):
    req("/rest/login", {"email": owner["email"], "password": owner["password"]})
st, existing = req("/rest/api-keys", method="GET")
for k in (existing.get("data") or []):
    req(f"/rest/api-keys/{k.get('id')}", method="DELETE")
st, made = req("/rest/api-keys", {"label": "corpus-campaign", "expiresAt": None})
data = made.get("data") or {}
print(data.get("apiKey") or data.get("rawApiKey") or "")
PROVISION
)"
[ -n "$N8N_KEY" ] || { echo "[campaign] failed to provision an n8n API key" >&2; exit 1; }

echo "[campaign] starting a fresh Pisama server (single-writer: no poll interval)"
PISAMA_API_KEY=corpus-campaign-key \
PISAMA_N8N_URL="http://localhost:$N8N_PORT" \
PISAMA_N8N_API_KEY="$N8N_KEY" \
DATABASE_URL="sqlite:///$WORKDIR/campaign.db" \
  "$PY" -m uvicorn pisama_n8n_server.app:app --host 127.0.0.1 --port "$SRV_PORT" \
  >"$WORKDIR/server.log" 2>&1 &
SRV_PID=$!
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$SRV_PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:$SRV_PORT/healthz" >/dev/null || {
  echo "[campaign] server did not start:" >&2; cat "$WORKDIR/server.log" >&2; exit 1; }

OUT_FILE="${CAMPAIGN_OUT:-$OUT_DIR/local_results_2026-07.jsonl}"
echo "[campaign] running the campaign driver (out: $OUT_FILE)"
PISAMA_N8N_URL="http://localhost:$N8N_PORT" PISAMA_N8N_API_KEY="$N8N_KEY" \
PISAMA_SERVER_URL="http://127.0.0.1:$SRV_PORT" PISAMA_API_KEY=corpus-campaign-key \
PISAMA_CAMPAIGN_DB="$WORKDIR/campaign.db" \
  "$PY" scripts/run_corpus_guard_campaign.py \
    --tier local \
    --max-executions "${CAMPAIGN_MAX_EXECUTIONS:-2000}" \
    --out "$OUT_FILE" "$@"

echo "[campaign] dup-source integrity check (must be empty)"
DUPS="$(sqlite3 "$WORKDIR/campaign.db" \
  "SELECT source_execution_id, COUNT(*) c FROM executions WHERE source_execution_id IS NOT NULL GROUP BY 1 HAVING c>1;")"
if [ -n "$DUPS" ]; then
  echo "[campaign] DUPLICATE SOURCE IDS FOUND — success counts are not trustworthy:" >&2
  echo "$DUPS" >&2
  exit 1
fi

if [ "$OUT_FILE" = "$OUT_DIR/local_results_2026-07.jsonl" ]; then
  cp "${OUT_FILE%.jsonl}.summary.json" eval/baseline_guard_campaign.json
  echo "[campaign] baseline written to eval/baseline_guard_campaign.json"
fi
echo "[campaign] PASS — results at $OUT_FILE"
