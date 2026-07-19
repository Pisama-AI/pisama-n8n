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
from pisama_n8n_server.storage import Storage, build_revision

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
    return {"status": "ok", "build_revision": build_revision()}


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


@app.get("/api/v1/reliability/metrics", dependencies=[Depends(require_read_auth)])
async def reliability_metrics(
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Evidence scorecard for this tenant. No cross-tenant or raw trace data."""
    return storage.operational_summary()["reliability_metrics"]


@app.get("/api/v1/reliability-cases", dependencies=[Depends(require_read_auth)])
async def list_reliability_cases(
    storage: Storage = Depends(get_storage),
) -> List[Dict[str, Any]]:
    """Tenant-local repair verification cases, newest first."""
    return storage.list_reliability_cases()


@app.get(
    "/api/v1/reliability-cases/{case_id}", dependencies=[Depends(require_read_auth)]
)
async def get_reliability_case(
    case_id: int, storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    case = storage.get_reliability_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Unknown reliability case id.")
    return case


@app.post(
    "/api/v1/reliability-cases/{case_id}/outcome", dependencies=[Depends(require_auth)]
)
async def conclude_reliability_case(
    case_id: int,
    body: Dict[str, Any],
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Record a reviewed outcome. Prevention requires the configured evidence bar."""
    outcome = body.get("outcome")
    note = body.get("note")
    if outcome not in {"prevented", "inconclusive"}:
        raise HTTPException(
            status_code=422, detail="outcome must be prevented or inconclusive."
        )
    if note is not None and not isinstance(note, str):
        raise HTTPException(
            status_code=422, detail="note must be a string when provided."
        )
    try:
        case = storage.conclude_reliability_case(case_id, outcome, note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if case is None:
        raise HTTPException(status_code=404, detail="Unknown reliability case id.")
    return case


@app.get(
    "/api/v1/reliability-cases/{case_id}/candidate-executions",
    dependencies=[Depends(require_read_auth)],
)
async def list_candidate_executions(
    case_id: int, storage: Storage = Depends(get_storage)
) -> List[Dict[str, Any]]:
    """Recent executions of the guarded workflow, annotated with how each routed through
    this guard, so the dashboard can offer a probe picker rather than a raw-id field. The
    guard-verification endpoint still re-verifies the routing when a probe is recorded."""
    rows = storage.list_candidate_executions(case_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Unknown reliability case id.")
    return rows


@app.post(
    "/api/v1/reliability-cases/{case_id}/guard-verification",
    dependencies=[Depends(require_auth)],
)
async def record_guard_verification(
    case_id: int,
    body: Dict[str, Any],
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Record one guardrail prevention probe against a REAL ingested execution.

    kind = 'malformed_rejected' | 'valid_passed'. The server verifies the execution's
    routing (rejection destination ran / consumer skipped for malformed; consumer ran for
    valid), turning the reliability case into verified prevention evidence."""
    kind = body.get("kind")
    execution_id = body.get("execution_id")
    source_execution_id = body.get("source_execution_id")
    if kind not in {"malformed_rejected", "valid_passed"}:
        raise HTTPException(
            status_code=422,
            detail="kind must be 'malformed_rejected' or 'valid_passed'.",
        )
    # Accept either the internal execution id or the n8n execution id (which a caller
    # naturally has right after firing a probe webhook).
    if not isinstance(execution_id, int) and source_execution_id is not None:
        execution_id = storage.execution_id_for_source(str(source_execution_id))
        if execution_id is None:
            raise HTTPException(
                status_code=409,
                detail="No ingested execution for that source id — run /n8n/sync first.",
            )
    if not isinstance(execution_id, int):
        raise HTTPException(
            status_code=422,
            detail="execution_id (int) or source_execution_id is required.",
        )
    try:
        return storage.record_guard_verification(case_id, kind, execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.post(
    "/api/v1/reliability-cases/{case_id}/route-verification",
    dependencies=[Depends(require_auth)],
)
async def record_route_verification(
    case_id: int,
    body: Dict[str, Any],
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Record the routed-incident probe for an error-route case: an execution of the
    TARGET error workflow, produced after the repair was applied. One probe, not the
    guardrail's two — an error route has no valid-path regression to disprove."""
    execution_id = body.get("execution_id")
    source_execution_id = body.get("source_execution_id")
    if not isinstance(execution_id, int) and source_execution_id is not None:
        execution_id = storage.execution_id_for_source(str(source_execution_id))
        if execution_id is None:
            raise HTTPException(
                status_code=409,
                detail="No ingested execution for that source id — run /n8n/sync first.",
            )
    if not isinstance(execution_id, int):
        raise HTTPException(
            status_code=422,
            detail="execution_id (int) or source_execution_id is required.",
        )
    try:
        return storage.record_route_verification(case_id, execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


# --- error-route repair: the second deterministic, operator-gated primitive ---

_ERROR_ROUTE_MODES = {
    "n8n_error_workflow_target_missing",
    "n8n_error_workflow_missing_trigger",
    "n8n_missing_error_workflow",
}


@app.post("/api/v1/n8n/error-route", dependencies=[Depends(require_auth)])
async def n8n_error_route(
    body: Dict[str, Any], storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """Propose an ERROR-ROUTE repair from a broken-error-workflow detection.

    Pure derivation, no model call, so it is FREE like the input-schema guardrail: the
    detector already established that the configured error workflow is missing,
    un-triggered, or absent, and the repair re-points ``settings.errorWorkflow`` at a
    target the operator picks from their own workflows.

    Deliberately NOT in scope: creating a new error workflow. That needs POST /workflows
    (absent from the client) plus a notification node whose credentials we cannot invent.
    """
    detection_id = body.get("detection_id")
    if not isinstance(detection_id, int):
        raise HTTPException(status_code=422, detail="detection_id (int) is required.")
    ctx = storage.get_detection_context(detection_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Unknown detection_id.")
    detection = ctx["detection"]
    if detection.get("failure_mode") not in _ERROR_ROUTE_MODES:
        raise HTTPException(
            status_code=422,
            detail="Error-route repairs apply only to error-workflow detections.",
        )
    exec_workflow = ctx.get("workflow")
    workflow_id = ctx.get("workflow_id")
    if not isinstance(exec_workflow, dict) or not workflow_id:
        raise HTTPException(
            status_code=422,
            detail="The detection has no associated workflow to repair.",
        )
    client = client_from_env()
    if client is None:
        raise HTTPException(
            status_code=400, detail="n8n API not configured (PISAMA_N8N_URL/KEY)."
        )
    # Baseline must be the LIVE workflow: an execution's embedded copy carries n8n-injected
    # defaults absent from the API response, which would trip the apply-time stale guard.
    try:
        workflow = await client.get_workflow(str(workflow_id))
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not read the workflow from n8n: {exc}"
        ) from None
    finally:
        await client.aclose()

    guard_config = {
        "kind": "error_route",
        "target_workflow_id": None,
        "previous_error_workflow": (workflow.get("settings") or {}).get("errorWorkflow"),
        "source_failure_mode": detection.get("failure_mode"),
    }
    proposal = storage.create_guardrail_proposal(
        detection_id=detection_id,
        workflow_id=workflow_id,
        baseline_workflow=workflow,
        guard_config=guard_config,
        explanation=(
            "Point this workflow's error route at a working error workflow; choose the "
            "target to apply."
        ),
    )
    return {"repair": proposal}


@app.get(
    "/api/v1/n8n/repairs/{repair_id}/error-targets",
    dependencies=[Depends(require_read_auth)],
)
async def list_error_route_targets(
    repair_id: int, storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """The instance's workflows as error-route targets, each marked eligible or not.

    n8n's workflow LIST response carries no node arrays, so eligibility (does it have an
    Error Trigger?) needs a per-candidate fetch. Ineligible candidates are RETURNED with
    the reason rather than filtered out — an operator who sees "No Error Trigger node"
    learns what to add, where a silently short list just looks broken."""
    from pisama_n8n_engine.guardrails import has_error_trigger

    existing = storage.get_repair(repair_id, include_workflows=True)
    if existing is None:
        raise HTTPException(status_code=404, detail="Unknown repair_id.")
    if (existing.get("guard_config") or {}).get("kind") != "error_route":
        raise HTTPException(
            status_code=422, detail="Repair is not an error-route proposal."
        )
    client = client_from_env()
    if client is None:
        raise HTTPException(
            status_code=400, detail="n8n API not configured (PISAMA_N8N_URL/KEY)."
        )
    try:
        listed = await client.list_workflows()
        targets: List[Dict[str, Any]] = []
        for item in listed:
            candidate_id = str(item.get("id"))
            if candidate_id == str(existing["workflow_id"]):
                continue  # a workflow cannot be its own error handler
            try:
                full = await client.get_workflow(candidate_id)
            except Exception:
                targets.append(
                    {
                        "id": candidate_id,
                        "name": item.get("name"),
                        "eligible": False,
                        "reason": "Could not read this workflow from n8n.",
                    }
                )
                continue
            eligible = has_error_trigger(full)
            targets.append(
                {
                    "id": candidate_id,
                    "name": item.get("name"),
                    "eligible": eligible,
                    "reason": None if eligible else "No Error Trigger node.",
                }
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not list workflows from n8n: {exc}"
        ) from None
    finally:
        await client.aclose()
    return {"targets": targets}


@app.post(
    "/api/v1/n8n/repairs/{repair_id}/error-target", dependencies=[Depends(require_auth)]
)
async def set_error_route_target(
    repair_id: int, body: Dict[str, Any], storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """Record the operator's chosen error-workflow target and build the mutated workflow.

    The apply-time PRECONDITION is asserted here against live n8n: the target must resolve
    and must contain an Error Trigger. That proves the route is well-formed. It does NOT
    prove an incident was delivered — that is what the routed-incident probe is for."""
    from pisama_n8n_engine.guardrails import (
        ErrorRouteError,
        build_error_route_repair,
        has_error_trigger,
    )

    target_id = body.get("target_workflow_id")
    if not target_id:
        raise HTTPException(status_code=422, detail="target_workflow_id is required.")
    existing = storage.get_repair(repair_id, include_workflows=True)
    if existing is None:
        raise HTTPException(status_code=404, detail="Unknown repair_id.")
    guard = existing.get("guard_config") or {}
    if guard.get("kind") != "error_route":
        raise HTTPException(
            status_code=422, detail="Repair is not an error-route proposal."
        )
    if existing["status"] != "proposed":
        raise HTTPException(
            status_code=409, detail=f"Repair is already {existing['status']}."
        )
    client = client_from_env()
    if client is None:
        raise HTTPException(
            status_code=400, detail="n8n API not configured (PISAMA_N8N_URL/KEY)."
        )
    try:
        try:
            target = await client.get_workflow(str(target_id))
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Target workflow {target_id!r} could not be read from n8n: {exc}",
            ) from None
    finally:
        await client.aclose()
    if not has_error_trigger(target):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Target workflow {target_id!r} has no Error Trigger node, so n8n would "
                "never invoke it. Add one, then choose it again."
            ),
        )

    try:
        built = build_error_route_repair(existing["baseline_workflow"], str(target_id))
    except ErrorRouteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    guard = {
        **guard,
        "target_workflow_id": str(target_id),
        "target_workflow_name": target.get("name"),
        "previous_error_workflow": built["previous_error_workflow"],
    }
    try:
        updated = storage.set_guardrail_destination(repair_id, built["workflow"], guard)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"repair": updated}


# --- input-schema guardrail: a deterministic, operator-gated repair -------


@app.post("/api/v1/n8n/guardrail", dependencies=[Depends(require_auth)])
async def n8n_guardrail(
    body: Dict[str, Any], storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """Propose a deterministic input-schema guardrail from a data-contract detection.

    Derives the required paths from evidence (the recorded property-read error + the
    failing consumer's own code, confirmed against its recorded input). No model call.
    Returns the proposal plus the path options and destination choices; the operator
    then picks a rejection destination via /n8n/repairs/{id}/destination before apply."""
    from pisama_n8n_engine.guardrails import (
        observed_consumer_input,
        observed_required_paths,
    )

    detection_id = body.get("detection_id")
    if not isinstance(detection_id, int):
        raise HTTPException(status_code=422, detail="detection_id (int) is required.")
    ctx = storage.get_detection_context(detection_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Unknown detection_id.")
    detection = ctx["detection"]
    if detection.get("failure_mode") != "n8n_data_contract":
        raise HTTPException(
            status_code=422,
            detail="Guardrails apply only to n8n_data_contract detections.",
        )
    exec_workflow = ctx.get("workflow")
    workflow_id = ctx.get("workflow_id")
    if not isinstance(exec_workflow, dict) or not workflow_id:
        raise HTTPException(
            status_code=422,
            detail="The detection has no associated workflow to guard.",
        )
    # Baseline must be the LIVE workflow: an execution's embedded workflow carries
    # n8n-injected defaults absent from the API response, which would trip the apply-time
    # stale guard. Path derivation still uses the execution (for the failing node's
    # recorded input). Fall back to the execution workflow when no n8n is configured.
    workflow = exec_workflow
    client = client_from_env()
    if client is not None:
        try:
            workflow = await client.get_workflow(str(workflow_id))
        finally:
            await client.aclose()
    issues = (detection.get("evidence") or {}).get("issues") or []
    if not issues:
        raise HTTPException(status_code=422, detail="Detection carries no failing node.")
    failing_node = issues[0].get("node")
    error_message = issues[0].get("message") or ""
    node_def = next(
        (n for n in workflow.get("nodes", []) if n.get("name") == failing_node), None
    )
    if node_def is None:
        raise HTTPException(
            status_code=422,
            detail=f"Failing node {failing_node!r} is not in the workflow.",
        )
    failing_code = (node_def.get("parameters") or {}).get("jsCode") or ""
    observed_input = observed_consumer_input(ctx.get("execution"), failing_node)
    paths = observed_required_paths(failing_code, error_message, observed_input)

    # Client-supplied paths are allowed only to CONFIRM/extend candidates the operator
    # reviewed — never to invent a path the evidence does not mention.
    chosen = list(paths["confirmed"]) or list(paths["candidates"])
    supplied = body.get("paths")
    if isinstance(supplied, list) and supplied:
        allowed = set(paths["confirmed"]) | set(paths["candidates"])
        invalid = [p for p in supplied if p not in allowed]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=f"paths {invalid} are not among the evidence-derived options.",
            )
        chosen = supplied
    if not chosen:
        raise HTTPException(
            status_code=422,
            detail="No required path could be derived from the recorded failure.",
        )

    guard_config = {
        "kind": "input_schema",
        "paths": chosen,
        "path_options": paths,
        "failing_node": failing_node,
        "destination": None,
        "alert_url": None,
    }
    proposal = storage.create_guardrail_proposal(
        detection_id=detection_id,
        workflow_id=ctx["workflow_id"],
        baseline_workflow=workflow,
        guard_config=guard_config,
        explanation=(
            f"Install an input-schema guard before {failing_node!r} requiring "
            f"{', '.join(chosen)}; choose a rejection destination to apply."
        ),
    )
    return {
        "repair": proposal,
        "path_options": paths,
        "destinations": _guardrail_destination_options(workflow),
    }


def _guardrail_destination_options(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The rejection destinations, each with whether it is available for this workflow."""
    from pisama_n8n_engine.guardrails import (
        GuardrailDestinationError,
        validate_destination_compatibility,
    )

    options = []
    for kind, label in (
        ("error_workflow", "Stop and fire the workflow's error workflow"),
        ("alert", "POST the rejection to an alert URL"),
        ("respond_422", "Respond 422 to the webhook caller"),
    ):
        available, reason = True, None
        try:
            validate_destination_compatibility(workflow, kind)
        except GuardrailDestinationError as exc:
            available, reason = False, str(exc)
        options.append(
            {"kind": kind, "label": label, "available": available, "reason": reason}
        )
    return options


@app.post(
    "/api/v1/n8n/repairs/{repair_id}/destination", dependencies=[Depends(require_auth)]
)
async def set_guardrail_destination(
    repair_id: int, body: Dict[str, Any], storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """Record the operator's chosen rejection destination and build the guarded workflow."""
    from pisama_n8n_engine.guardrails import (
        GuardrailDestinationError,
        GuardrailInsertionError,
        insert_guard_into_workflow,
    )

    destination = body.get("destination")
    alert_url = body.get("alert_url")
    existing = storage.get_repair(repair_id, include_workflows=True)
    if existing is None:
        raise HTTPException(status_code=404, detail="Unknown repair_id.")
    guard = existing.get("guard_config")
    if not guard:
        raise HTTPException(status_code=422, detail="Repair is not a guardrail proposal.")
    if existing["status"] != "proposed":
        raise HTTPException(
            status_code=409, detail=f"Repair is already {existing['status']}."
        )
    try:
        built = insert_guard_into_workflow(
            existing["baseline_workflow"],
            guard["paths"],
            guard["failing_node"],
            destination,
            alert_url=alert_url,
        )
    except (GuardrailDestinationError, GuardrailInsertionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    guard = {
        **guard,
        "destination": destination,
        "alert_url": alert_url,
        "fragment_node_names": built["fragment_node_names"],
        "destination_node_name": built["destination_node_name"],
        "entry_node": built["entry_node"],
        "validated_node": built["validated_node"],
        "rejected_node": built["rejected_node"],
    }
    try:
        updated = storage.set_guardrail_destination(
            repair_id, built["workflow"], guard
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"repair": updated}


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
        commit_apply,
        is_paid_configured,
        prepare_apply,
    )

    repair_id = body.get("repair_id")
    if not isinstance(repair_id, int):
        raise HTTPException(status_code=422, detail="repair_id is required.")
    existing = storage.get_repair(repair_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Unknown repair_id.")
    guard = existing.get("guard_config")
    # A deterministic guardrail is a FREE repair (no model call), so it does not require
    # the paid cloud. Only model-generated fixes gate on PISAMA_CLOUD_KEY.
    if guard is None and not is_paid_configured():
        raise HTTPException(
            status_code=402, detail="Auto-fix is a paid feature — set PISAMA_CLOUD_KEY."
        )
    # A guardrail cannot be applied until the operator has chosen a rejection destination.
    # Check BEFORE claiming so a null-destination guardrail is never stuck in 'applying'.
    kind = (guard or {}).get("kind")
    if kind == "input_schema" and guard.get("destination") is None:
        raise HTTPException(
            status_code=409,
            detail="Choose a rejection destination for this guardrail before applying it.",
        )
    if kind == "error_route" and guard.get("target_workflow_id") is None:
        raise HTTPException(
            status_code=409,
            detail="Choose a target error workflow before applying this error-route repair.",
        )
    repair = storage.claim_repair_apply(repair_id)
    if repair is None:
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
        # Phase 1 — validate against the live workflow. No mutation happens, so every
        # failure here leaves the live workflow untouched.
        try:
            snapshot = await prepare_apply(
                client,
                repair["workflow_id"],
                repair["baseline_workflow"],
                repair["proposed_workflow"],
            )
        except StaleRepairProposal as exc:
            storage.mark_repair_stale(repair_id, "applying", str(exc))
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except InvalidRepairProposal as exc:
            storage.mark_repair_failed(repair_id, "applying", str(exc))
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception as exc:
            storage.mark_repair_failed(repair_id, "applying", str(exc))
            raise

        # Guardrail defense in depth: even though the proposal is server-generated, the
        # mutated workflow may only ADD the guard fragment nodes — never remove/retype an
        # existing node. Refuse (and leave the live workflow untouched) otherwise.
        if kind == "error_route":
            # Bound by assert_safe_settings_diff, NOT assert_safe_guardrail_diff — the
            # latter inspects node deltas only and never looks at settings, so it would
            # pass a settings-only mutation VACUOUSLY.
            from pisama_n8n_engine.guardrails import (
                ErrorRouteError,
                assert_safe_settings_diff,
            )

            try:
                assert_safe_settings_diff(
                    repair["baseline_workflow"],
                    repair["proposed_workflow"],
                    allowed_keys={"errorWorkflow"},
                )
            except ErrorRouteError as exc:
                storage.mark_repair_failed(repair_id, "applying", str(exc))
                raise HTTPException(status_code=422, detail=str(exc)) from None
        elif guard is not None:
            from pisama_n8n_engine.guardrails import (
                GuardrailInsertionError,
                assert_safe_guardrail_diff,
            )

            try:
                assert_safe_guardrail_diff(
                    repair["baseline_workflow"],
                    repair["proposed_workflow"],
                    guard.get("fragment_node_names") or [],
                )
            except GuardrailInsertionError as exc:
                storage.mark_repair_failed(repair_id, "applying", str(exc))
                raise HTTPException(status_code=422, detail=str(exc)) from None

        # Durably record the restore point BEFORE mutating the live workflow. This is the
        # fix for the strand-on-failure bug: if the PUT lands but any later step raises,
        # the snapshot is already persisted, so the repair stays rollback-eligible.
        storage.record_repair_snapshot(
            repair_id, snapshot, repair["proposed_workflow"]
        )

        # Phase 2 — the point of no return: the live PUT. If it raises, the mutation may
        # already have landed, so keep the repair rollback-eligible, never 'failed'.
        try:
            applied = await commit_apply(
                client, repair["workflow_id"], repair["proposed_workflow"]
            )
        except Exception as exc:
            storage.mark_repair_apply_unverified(repair_id, str(exc))
            raise HTTPException(
                status_code=502,
                detail="Applied the fix to n8n but could not confirm the result; "
                "the repair is left rollback-eligible.",
            ) from None

        # Phase 3 — the PUT succeeded. Bookkeeping must not strand a live mutation: the
        # snapshot is already persisted, so on failure keep it rollback-eligible.
        try:
            return {
                "repair": storage.mark_repair_applied(
                    repair_id, snapshot=snapshot, applied_workflow=applied
                )
            }
        except Exception as exc:
            storage.mark_repair_apply_unverified(
                repair_id, f"apply bookkeeping failed after n8n write: {exc}"
            )
            raise HTTPException(
                status_code=502,
                detail="Applied the fix to n8n but could not record it; "
                "the repair is left rollback-eligible.",
            ) from None
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
