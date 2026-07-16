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
_HMAC_FRESHNESS_SECONDS = 300  # reject signatures older/newer than 5 minutes


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
        if _valid_hmac_signature(await request.body(), signature, timestamp):
            return
        raise HTTPException(
            status_code=401, detail="Invalid or stale webhook signature."
        )
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
    computed = (
        "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    )
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
    execution payload, run both lanes, persist, return the report. Accepts the plain
    API export, the flatted DB wire format (a JSON array), and partially-dereferenced
    DB dumps — normalization happens in process_execution."""
    payload = await request.json()
    try:
        report = process_execution(payload, storage)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    storage.record_operational_event(
        "webhook_ingested",
        {
            "detections_fired": sum(
                1 for d in report.get("detections", []) if d.get("detected")
            )
        },
    )
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
        storage.record_operational_event("poll_succeeded", summary)
        if summary.get("new"):
            await broadcaster.publish({"type": "poll", **summary})
        return summary
    except Exception as exc:
        storage.record_operational_event("poll_failed", {"error": type(exc).__name__})
        raise
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


@app.get(
    "/api/v1/detections/{detection_id}/trace", dependencies=[Depends(require_read_auth)]
)
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


_FEEDBACK_VERDICTS = {"useful", "not_useful", "fixed_manually"}


@app.post(
    "/api/v1/detections/{detection_id}/feedback", dependencies=[Depends(require_auth)]
)
async def submit_detection_feedback(
    detection_id: int,
    body: Dict[str, Any],
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Store an explicit local operator verdict. This never sends feedback to Pisama."""
    verdict = body.get("verdict")
    note = body.get("note")
    if verdict not in _FEEDBACK_VERDICTS:
        raise HTTPException(
            status_code=422,
            detail="verdict must be useful, not_useful, or fixed_manually.",
        )
    if note is not None and not isinstance(note, str):
        raise HTTPException(
            status_code=422, detail="note must be a string when provided."
        )
    feedback = storage.submit_detection_feedback(detection_id, verdict, note)
    if feedback is None:
        raise HTTPException(status_code=404, detail="Unknown detection id.")
    storage.record_operational_event("feedback_recorded", {"verdict": verdict})
    return feedback


@app.get("/api/v1/operations/summary", dependencies=[Depends(require_read_auth)])
async def operations_summary(storage: Storage = Depends(get_storage)) -> Dict[str, Any]:
    """Real local ingestion, detection, repair, and feedback health for operators."""
    return storage.operational_summary()


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
    from pisama_n8n_server.fixes import (
        PaidTierNotConfigured,
        is_paid_configured,
        request_fix,
    )

    detection_id = body.get("detection_id")
    if not is_paid_configured():
        raise HTTPException(
            status_code=402, detail="Auto-fix is a paid feature — set PISAMA_CLOUD_KEY."
        )
    ctx = (
        storage.get_detection_context(int(detection_id))
        if detection_id is not None
        else None
    )
    if ctx is None:
        raise HTTPException(status_code=404, detail="Unknown detection_id.")
    workflow_id = ctx.get("workflow_id")
    if not workflow_id:
        raise HTTPException(
            status_code=422, detail="No n8n workflow id stored for this detection."
        )
    client = client_from_env()
    if client is None:
        raise HTTPException(
            status_code=400, detail="n8n API not configured (PISAMA_N8N_URL/KEY)."
        )
    try:
        # Executions can contain n8n-injected defaults that are absent from the workflow
        # API response. Use a fresh API read as the repair baseline, otherwise the stale
        # guard would reject a proposal even when no human has edited the workflow.
        baseline_workflow = await client.get_workflow(str(workflow_id))
    finally:
        await client.aclose()
    try:
        suggestion = await request_fix(ctx["detection"], baseline_workflow)
    except PaidTierNotConfigured as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    try:
        repair = storage.create_repair_proposal(
            detection_id=int(detection_id),
            workflow_id=str(workflow_id),
            baseline_workflow=baseline_workflow,
            suggestion=suggestion,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    # The browser gets a reviewable preview plus an opaque, server-owned repair id.
    suggestion["workflow_id"] = workflow_id
    suggestion["repair_id"] = repair["id"]
    suggestion["repair_status"] = repair["status"]
    return suggestion


@app.post("/api/v1/n8n/apply", dependencies=[Depends(require_auth)])
async def n8n_apply(
    body: Dict[str, Any], storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """Apply one stored, reviewed proposal, refusing stale workflow writes."""
    from pisama_n8n_server.fixes import (
        InvalidRepairProposal,
        StaleRepairProposal,
        apply_fix,
        is_paid_configured,
    )

    if not is_paid_configured():
        raise HTTPException(
            status_code=402, detail="Auto-fix is a paid feature — set PISAMA_CLOUD_KEY."
        )
    repair_id = body.get("repair_id")
    if not isinstance(repair_id, int):
        raise HTTPException(status_code=422, detail="repair_id is required.")
    repair = storage.claim_repair_apply(repair_id)
    if repair is None:
        existing = storage.get_repair(repair_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Unknown repair_id.")
        raise HTTPException(
            status_code=409, detail=f"Repair is already {existing['status']}."
        )
    client = client_from_env()
    if client is None:
        storage.mark_repair_failed(repair_id, "applying", "n8n API not configured.")
        raise HTTPException(
            status_code=400, detail="n8n API not configured (PISAMA_N8N_URL/KEY)."
        )
    try:
        result = await apply_fix(
            client,
            repair["workflow_id"],
            repair["baseline_workflow"],
            repair["proposed_workflow"],
        )
        return {"repair": storage.mark_repair_applied(repair_id, **result)}
    except StaleRepairProposal as exc:
        storage.mark_repair_stale(repair_id, "applying", str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except InvalidRepairProposal as exc:
        storage.mark_repair_failed(repair_id, "applying", str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        storage.mark_repair_failed(repair_id, "applying", str(exc))
        raise
    finally:
        await client.aclose()


@app.post("/api/v1/n8n/rollback", dependencies=[Depends(require_auth)])
async def n8n_rollback(
    body: Dict[str, Any], storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """Restore a server-stored snapshot, refusing to overwrite later human edits."""
    from pisama_n8n_server.fixes import StaleRepairProposal, rollback

    repair_id = body.get("repair_id")
    if not isinstance(repair_id, int):
        raise HTTPException(status_code=422, detail="repair_id is required.")
    repair = storage.claim_repair_rollback(repair_id)
    if repair is None:
        existing = storage.get_repair(repair_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Unknown repair_id.")
        raise HTTPException(
            status_code=409, detail=f"Repair is already {existing['status']}."
        )
    if not isinstance(repair.get("snapshot"), dict) or not isinstance(
        repair.get("applied_workflow"), dict
    ):
        storage.mark_repair_failed(
            repair_id, "rolling_back", "Repair has no restorable snapshot."
        )
        raise HTTPException(
            status_code=409, detail="Repair has no restorable snapshot."
        )
    client = client_from_env()
    if client is None:
        storage.mark_repair_failed(repair_id, "rolling_back", "n8n API not configured.")
        raise HTTPException(status_code=400, detail="n8n API not configured.")
    try:
        restored = await rollback(
            client,
            repair["workflow_id"],
            repair["snapshot"],
            repair["applied_workflow"],
        )
        return {
            "restored": restored,
            "repair": storage.mark_repair_rolled_back(repair_id),
        }
    except StaleRepairProposal as exc:
        storage.mark_repair_stale(repair_id, "rolling_back", str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception as exc:
        storage.mark_repair_failed(repair_id, "rolling_back", str(exc))
        raise
    finally:
        await client.aclose()


@app.get("/api/v1/stream")
async def stream(request: Request) -> StreamingResponse:
    """SSE stream of live detection events, so the dashboard updates as executions arrive.
    Auth is via the `token` query param (EventSource can't set headers); open when
    PISAMA_PUBLIC_READ=1 (read-only stream) or when PISAMA_API_KEY is unset (dev mode)."""
    expected = os.environ.get("PISAMA_API_KEY")
    if (
        (not public_read_enabled())
        and expected
        and request.query_params.get("token") != expected
    ):
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
            get_storage().record_operational_event("poll_succeeded", summary)
            if summary.get("new"):
                await broadcaster.publish({"type": "poll", **summary})
        except Exception as exc:  # never let the loop die on a transient error
            logger.warning("background poll failed: %s", exc)
            get_storage().record_operational_event(
                "poll_failed", {"error": type(exc).__name__}
            )
        finally:
            await client.aclose()
