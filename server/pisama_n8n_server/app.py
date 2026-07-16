"""pisama_n8n_server.app — single-tenant self-host detection server.

Runs the Pisama n8n detection engine as a small FastAPI service a user can
self-host next to their own n8n instance:

  - ``POST /api/v1/n8n/webhook`` ingests an n8n execution export, runs BOTH
    detection lanes via the engine (structural from the workflow JSON, runtime
    from the execution runData), persists the merged report to SQLite, and
    returns it.
  - ``GET /api/v1/detections`` reads every stored detection back.
  - ``GET /healthz`` liveness.

Auth is a static bearer token from ``PISAMA_API_KEY``; if unset we log a warning
and allow (dev mode). Storage is real SQLite via SQLAlchemy 2.x (``DATABASE_URL``
override for Postgres later). No mocks anywhere.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from pisama_n8n_server.events import broadcaster, fired_event
from pisama_n8n_server.n8n_client import client_from_env
from pisama_n8n_server.poller import poll_once
from pisama_n8n_server.processing import process_execution
from pisama_n8n_server.storage import Storage

logger = logging.getLogger("pisama_n8n_server")

# The self-driving poll task (armed at startup when PISAMA_POLL_INTERVAL > 0 and n8n is
# configured). Off by default — /api/v1/n8n/sync stays available for external cron.
_poll_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _poll_task
    interval = float(os.environ.get("PISAMA_POLL_INTERVAL", "0") or "0")
    if interval > 0 and client_from_env() is not None:
        _poll_task = asyncio.create_task(_poll_loop(interval))
        logger.info("background n8n poll loop started (every %ss)", interval)
    try:
        yield
    finally:
        if _poll_task is not None:
            _poll_task.cancel()


app = FastAPI(
    title="Pisama n8n Server",
    description="Self-host detection server for n8n workflow executions.",
    version="0.1.0",
    lifespan=lifespan,
)

# The dashboard is a separate origin (its own port/host), so it needs CORS to read the
# detections API from the browser. Configurable via PISAMA_CORS_ORIGINS (comma-separated);
# defaults to "*" for zero-config self-host since auth is the bearer token, not the origin.
_cors_origins = os.environ.get("PISAMA_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- storage wiring -------------------------------------------------------

_storage: Optional[Storage] = None


def get_storage() -> Storage:
    """Lazily build the process-wide Storage. Overridable in tests via
    ``app.dependency_overrides[get_storage]``."""
    global _storage
    if _storage is None:
        _storage = Storage()
    return _storage


# --- auth -----------------------------------------------------------------

def public_read_enabled() -> bool:
    """PISAMA_PUBLIC_READ=1 opens the read-only GETs (detections, stream, paid status)
    while every POST stays key-gated. This is what makes a hosted public dashboard safe:
    the browser needs no key to view, and no write/paid capability ships to the client."""
    return os.environ.get("PISAMA_PUBLIC_READ", "").lower() in ("1", "true", "yes")


# The community node (n8n-nodes-pisama, published v0.3.0 — contract verified
# against the actual npm tarball, NOT a local checkout, which diverged) signs
# each POST body as "sha256=" + hex(HMAC-SHA256(secret, "{timestamp}.{body}"))
# sent in X-Pisama-Signature, alongside X-Pisama-Timestamp (unix seconds) and
# X-Pisama-Nonce (sent, but NOT part of the signature base). Its secret is the
# credential's separate "Webhook Secret" field, so verify against
# PISAMA_WEBHOOK_SECRET when set, falling back to PISAMA_API_KEY. The node
# also always sends its apiKey credential as X-Pisama-API-Key; accept that as
# equivalent to Bearer so a node with no Webhook Secret can still authenticate.
#
# Semantics mirror the hosted backend's verify_webhook_if_configured
# (backend/app/api/v1/provider_base.py): same signature base and freshness
# window, and a signed request is single-use — the nonce is consumed on
# success, which is the actual replay defense (the timestamp window alone
# would let a captured request be re-posted, and webhook ingests have no
# upstream execution id to dedup on). The backend keys the secret per
# registered workflow; this server is single-tenant, so one env secret is
# the whole keyspace.
_HMAC_FRESHNESS_SECONDS = 300  # reject signatures older/newer than 5 minutes

# Nonces live in memory: single-tenant, single-process server. Kept for twice
# the freshness window (a timestamp up to +300s in the future stays verifiable
# until +600s), pruned inline so the dict stays bounded without a sweeper.
_seen_nonces: Dict[str, float] = {}


def _consume_nonce(nonce: str) -> bool:
    """Mark a nonce used; False if it was already used inside its lifetime."""
    now = time.time()
    for stale in [n for n, expiry in _seen_nonces.items() if expiry <= now]:
        del _seen_nonces[stale]
    if nonce in _seen_nonces:
        return False
    _seen_nonces[nonce] = now + 2 * _HMAC_FRESHNESS_SECONDS
    return True


async def require_read_auth(request: Request) -> None:
    """Auth for read-only endpoints: open when PISAMA_PUBLIC_READ=1, else same as write."""
    if public_read_enabled():
        return
    await require_auth(request)


async def require_auth(request: Request) -> None:
    """Bearer/X-Pisama-API-Key auth (PISAMA_API_KEY) OR the node's HMAC signature.

    If ``PISAMA_API_KEY`` is unset, dev mode: allow.
    """
    expected = os.environ.get("PISAMA_API_KEY")
    if not expected:
        logger.warning("PISAMA_API_KEY unset — running open (dev mode).")
        return
    authorization = request.headers.get("authorization")
    if authorization is not None and hmac.compare_digest(
        authorization.encode(), f"Bearer {expected}".encode()
    ):
        return
    api_key_header = request.headers.get("x-pisama-api-key")
    if api_key_header is not None and hmac.compare_digest(
        api_key_header.encode(), expected.encode()
    ):
        return
    signature = request.headers.get("x-pisama-signature")
    timestamp = request.headers.get("x-pisama-timestamp")
    if signature and timestamp:
        nonce = request.headers.get("x-pisama-nonce")
        if not nonce:
            raise HTTPException(status_code=401, detail="Webhook nonce required.")
        if not _valid_hmac_signature(await request.body(), signature, timestamp):
            raise HTTPException(status_code=401, detail="Invalid or stale webhook signature.")
        # Only a request that proved knowledge of the secret may consume a
        # nonce — otherwise unauthenticated garbage could burn future nonces.
        if not _consume_nonce(nonce):
            raise HTTPException(status_code=401, detail="Replay attack detected.")
        return
    raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")


def _valid_hmac_signature(body: bytes, signature: str, timestamp: str) -> bool:
    """Verify "sha256=" + hex(HMAC-SHA256(secret, "{timestamp}.{body}")) within freshness."""
    secret = os.environ.get("PISAMA_WEBHOOK_SECRET") or os.environ.get("PISAMA_API_KEY")
    if not secret:
        return False
    try:
        signed_at = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - signed_at) > _HMAC_FRESHNESS_SECONDS:
        return False
    payload = f"{timestamp}.".encode() + body
    computed = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed.encode(), signature.encode())


# --- routes ---------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/n8n/webhook", dependencies=[Depends(require_auth)])
async def n8n_webhook(
    request: Request,
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Webhook / community-node / error-workflow push channel: receive one n8n
    execution payload, run both lanes, persist, return the report."""
    payload = await request.json()
    report = process_execution(payload, storage)
    if report.get("detections"):
        await broadcaster.publish(fired_event(report))
    return report


@app.post("/api/v1/n8n/sync", dependencies=[Depends(require_auth)])
async def n8n_sync(
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """API-polling channel: pull recent executions from the user's n8n
    (PISAMA_N8N_URL + PISAMA_N8N_API_KEY) and ingest the new ones. No workflow edits."""
    client = client_from_env()
    if client is None:
        raise HTTPException(
            status_code=400,
            detail="Polling not configured — set PISAMA_N8N_URL and PISAMA_N8N_API_KEY.",
        )
    try:
        summary = await poll_once(client, storage)
        if summary.get("new"):
            await broadcaster.publish({"type": "poll", **summary})
        return summary
    finally:
        await client.aclose()


@app.get("/api/v1/detections", dependencies=[Depends(require_read_auth)])
async def list_detections(
    storage: Storage = Depends(get_storage),
) -> List[Dict[str, Any]]:
    return storage.list_detections()


@app.get("/api/v1/detections/{detection_id}", dependencies=[Depends(require_read_auth)])
async def get_detection(
    detection_id: int,
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """One enriched detection by id, so the detail view can deep-link without loading
    the whole list. 404 when the id is unknown."""
    row = storage.get_detection(detection_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown detection id.")
    return row


@app.get("/api/v1/detections/{detection_id}/trace", dependencies=[Depends(require_read_auth)])
async def get_detection_trace(
    detection_id: int,
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """The per-node execution trace behind a detection, so the detail view can show
    which node failed, how long it took, and what it emitted. 404 for an unknown id."""
    trace = storage.get_execution_trace(detection_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Unknown detection id.")
    return trace


# --- paid tier: fix suggestions + auto-apply (cloud-backed) ---------------

@app.get("/api/v1/paid/status", dependencies=[Depends(require_read_auth)])
async def paid_status() -> Dict[str, bool]:
    """Whether the paid tier (fix suggestions + auto-fix) is configured on this server."""
    from pisama_n8n_server.fixes import is_paid_configured
    return {"enabled": is_paid_configured()}


@app.post("/api/v1/n8n/fix", dependencies=[Depends(require_auth)])
async def n8n_fix(
    body: Dict[str, Any],
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """PAID: request a fix suggestion for a detection. Looks up the detection's workflow,
    sends it to the Pisama cloud, returns the suggestion (read-only preview)."""
    from pisama_n8n_server.fixes import PaidTierNotConfigured, request_fix

    detection_id = body.get("detection_id")
    ctx = storage.get_detection_context(int(detection_id)) if detection_id is not None else None
    if ctx is None:
        raise HTTPException(status_code=404, detail="Unknown detection_id.")
    if not ctx.get("workflow"):
        raise HTTPException(status_code=422, detail="No workflow stored for this detection.")
    try:
        suggestion = await request_fix(ctx["detection"], ctx["workflow"])
    except PaidTierNotConfigured as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    # Carry the n8n workflow id so the dashboard can target /apply.
    suggestion["workflow_id"] = ctx.get("workflow_id")
    return suggestion


@app.post("/api/v1/n8n/apply", dependencies=[Depends(require_auth)])
async def n8n_apply(body: Dict[str, Any]) -> Dict[str, Any]:
    """PAID: apply a cloud-returned mutated workflow to the live n8n (snapshot for rollback).
    Requires n8n API access (PISAMA_N8N_URL + PISAMA_N8N_API_KEY)."""
    from pisama_n8n_server.fixes import apply_fix, is_paid_configured

    if not is_paid_configured():
        raise HTTPException(status_code=402, detail="Auto-fix is a paid feature — set PISAMA_CLOUD_KEY.")
    workflow_id = body.get("workflow_id")
    mutated = body.get("mutated_workflow")
    if not workflow_id or not isinstance(mutated, dict):
        raise HTTPException(status_code=422, detail="workflow_id and mutated_workflow required.")
    client = client_from_env()
    if client is None:
        raise HTTPException(status_code=400, detail="n8n API not configured (PISAMA_N8N_URL/KEY).")
    try:
        return await apply_fix(client, workflow_id, mutated)
    finally:
        await client.aclose()


@app.post("/api/v1/n8n/rollback", dependencies=[Depends(require_auth)])
async def n8n_rollback(body: Dict[str, Any]) -> Dict[str, Any]:
    """Restore a workflow snapshot returned by /apply."""
    from pisama_n8n_server.fixes import rollback

    workflow_id = body.get("workflow_id")
    snapshot = body.get("snapshot")
    if not workflow_id or not isinstance(snapshot, dict):
        raise HTTPException(status_code=422, detail="workflow_id and snapshot required.")
    client = client_from_env()
    if client is None:
        raise HTTPException(status_code=400, detail="n8n API not configured.")
    try:
        return {"restored": await rollback(client, workflow_id, snapshot)}
    finally:
        await client.aclose()


@app.get("/api/v1/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE stream of live detection events, so the dashboard updates as executions arrive.
    Auth is via the `token` query param (EventSource can't set headers); open when
    PISAMA_PUBLIC_READ=1 (read-only stream) or when PISAMA_API_KEY is unset (dev mode)."""
    expected = os.environ.get("PISAMA_API_KEY")
    if (not public_read_enabled()) and expected and request.query_params.get("token") != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing token.")

    async def gen() -> AsyncIterator[str]:
        q = broadcaster.subscribe()
        try:
            yield ": connected\n\n"  # prelude so the client opens promptly
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # comment frame keeps the connection warm
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- background polling loop ----------------------------------------------

async def _poll_loop(interval: float) -> None:
    """Periodically poll the configured n8n and publish any new detections."""
    while True:
        await asyncio.sleep(interval)
        client = client_from_env()
        if client is None:
            continue
        try:
            summary = await poll_once(client, get_storage())
            if summary.get("new"):
                await broadcaster.publish({"type": "poll", **summary})
        except Exception as exc:  # never let the loop die on a transient error
            logger.warning("background poll failed: %s", exc)
        finally:
            await client.aclose()
