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
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from pisama_n8n_engine import (
    FAILURE_MODES,
    TAXONOMY_VERSION,
    analyze_execution,
    score_labeled_executions,
)
from pisama_n8n_server.events import broadcaster, fired_event
from pisama_n8n_server.n8n_client import client_from_env
from pisama_n8n_server.poller import poll_once
from pisama_n8n_server.processing import evaluation_response, process_execution
from pisama_n8n_server.storage import (
    DuplicateEvaluationCase,
    Storage,
    build_revision,
)

logger = logging.getLogger("pisama_n8n_server")

_SOURCE_REPOSITORY = "https://github.com/Pisama-AI/pisama-n8n"
_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _installed_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


_SERVER_VERSION = _installed_version("pisama-n8n-server")
_ENGINE_VERSION = _installed_version("pisama-n8n-engine")
_DEFAULT_MAX_REQUEST_BYTES = 10 * 1024 * 1024


def production_mode() -> bool:
    return os.environ.get("PISAMA_ENV", "development").strip().lower() == "production"


def _max_request_bytes() -> int:
    configured = os.environ.get(
        "PISAMA_MAX_REQUEST_BYTES", str(_DEFAULT_MAX_REQUEST_BYTES)
    )
    try:
        value = int(configured)
    except ValueError as exc:
        raise RuntimeError("PISAMA_MAX_REQUEST_BYTES must be an integer.") from exc
    if value <= 0:
        raise RuntimeError("PISAMA_MAX_REQUEST_BYTES must be greater than zero.")
    return value


def _rate_limit_per_minute() -> int:
    configured = os.environ.get(
        "PISAMA_RATE_LIMIT_PER_MINUTE", "600" if production_mode() else "0"
    )
    try:
        value = int(configured)
    except ValueError as exc:
        raise RuntimeError("PISAMA_RATE_LIMIT_PER_MINUTE must be an integer.") from exc
    if value < 0:
        raise RuntimeError("PISAMA_RATE_LIMIT_PER_MINUTE cannot be negative.")
    return value


def _validate_runtime_config() -> None:
    _max_request_bytes()
    _rate_limit_per_minute()
    if production_mode() and not os.environ.get("PISAMA_API_KEY"):
        raise RuntimeError("PISAMA_API_KEY is required when PISAMA_ENV=production.")


class RequestSizeLimitMiddleware:
    """Reject oversized fixed-length and streamed request bodies before parsing."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = _max_request_bytes()
        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > limit:
                    await self._reject(scope, receive, send, limit)
                    return
            except ValueError:
                await JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header."},
                )(scope, receive, send)
                return
        received = 0

        async def limited_receive() -> Any:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLarge:
            await self._reject(scope, receive, send, limit)

    @staticmethod
    async def _reject(scope: Any, receive: Any, send: Any, limit: int) -> None:
        await JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds the {limit}-byte limit."},
        )(scope, receive, send)


class _RequestBodyTooLarge(Exception):
    pass


def _verified_source_revision_url(revision: str) -> Optional[str]:
    expected = f"{_SOURCE_REPOSITORY}/commit/{revision}"
    configured = os.environ.get("PISAMA_SOURCE_REVISION_URL", "").strip()
    if _FULL_GIT_SHA.fullmatch(revision) and configured == expected:
        return configured
    return None


def _deployment_provenance() -> Dict[str, Any]:
    revision = build_revision()
    return {
        "service": "pisama-n8n-server",
        "version": _SERVER_VERSION,
        "engine_version": _ENGINE_VERSION,
        "build_revision": revision,
        "source_repository": _SOURCE_REPOSITORY,
        "source_revision_url": _verified_source_revision_url(revision),
    }


# The self-driving poll task (armed at startup when PISAMA_POLL_INTERVAL > 0 and n8n is
# configured). Off by default — /api/v1/n8n/sync stays available for external cron.
_poll_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _poll_task, _storage
    _validate_runtime_config()
    interval = float(os.environ.get("PISAMA_POLL_INTERVAL", "0") or "0")
    if interval > 0 and client_from_env() is not None:
        _poll_task = asyncio.create_task(_poll_loop(interval))
        logger.info("background n8n poll loop started (every %ss)", interval)
    try:
        yield
    finally:
        if _poll_task is not None:
            _poll_task.cancel()
        if _storage is not None:
            _storage.close()
            _storage = None


app = FastAPI(
    title="Pisama n8n Server",
    description="Self-host detection server for n8n workflow executions.",
    version=_SERVER_VERSION,
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
app.add_middleware(RequestSizeLimitMiddleware)


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

async def require_read_auth(
    request: Request, storage: Storage = Depends(get_storage)
) -> None:
    """Auth for read-only endpoints: open when PISAMA_PUBLIC_READ=1, else same as write."""
    if public_read_enabled():
        principal = _public_principal(request)
        request.state.auth_principal = principal
        _enforce_rate_limit(storage, principal)
        return
    await require_auth(request, storage)


async def require_auth(
    request: Request, storage: Storage = Depends(get_storage)
) -> None:
    """Bearer/X-Pisama-API-Key auth (PISAMA_API_KEY) OR the node's HMAC signature.

    If ``PISAMA_API_KEY`` is unset, dev mode: allow.
    """
    expected = os.environ.get("PISAMA_API_KEY")
    if not expected:
        if production_mode():
            raise HTTPException(
                status_code=503,
                detail="Server authentication is not configured.",
            )
        logger.warning("PISAMA_API_KEY unset — running open (dev mode).")
        _accept_principal(request, storage, "self-host:development")
        return
    principal = _api_key_principal(request, expected)
    if principal is None:
        principal = await _signed_webhook_principal(request, storage, expected)
    if principal is None:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")
    _accept_principal(request, storage, principal)


def _api_key_principal(request: Request, expected: str) -> Optional[str]:
    authorization = request.headers.get("authorization")
    if authorization is not None and hmac.compare_digest(
        authorization.encode(), f"Bearer {expected}".encode()
    ):
        return _credential_principal("api-key", expected)
    api_key_header = request.headers.get("x-pisama-api-key")
    if api_key_header is not None and hmac.compare_digest(
        api_key_header.encode(), expected.encode()
    ):
        return _credential_principal("api-key", expected)
    return None


async def _signed_webhook_principal(
    request: Request, storage: Storage, expected: str
) -> Optional[str]:
    signature = request.headers.get("x-pisama-signature")
    timestamp = request.headers.get("x-pisama-timestamp")
    if not signature or not timestamp:
        return None
    nonce = request.headers.get("x-pisama-nonce")
    if not nonce:
        raise HTTPException(status_code=401, detail="Webhook nonce required.")
    if not _valid_hmac_signature(await request.body(), signature, timestamp):
        raise HTTPException(
            status_code=401, detail="Invalid or stale webhook signature."
        )
    # Consume only after the signature proves knowledge of the secret. Otherwise
    # unauthenticated requests could burn a legitimate sender's future nonce.
    if not storage.consume_webhook_nonce(
        nonce, lifetime_seconds=2 * _HMAC_FRESHNESS_SECONDS
    ):
        raise HTTPException(status_code=401, detail="Replay attack detected.")
    secret = os.environ.get("PISAMA_WEBHOOK_SECRET") or expected
    return _credential_principal("webhook", secret)


def _accept_principal(request: Request, storage: Storage, principal: str) -> None:
    request.state.auth_principal = principal
    _enforce_rate_limit(storage, principal)


def _credential_principal(kind: str, secret: str) -> str:
    """Return a stable audit identity without storing credential material."""
    fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]
    return f"self-host:{kind}:{fingerprint}"


def _public_principal(request: Request) -> str:
    address = request.client.host if request.client else "unknown"
    fingerprint = hashlib.sha256(address.encode("utf-8")).hexdigest()[:12]
    return f"self-host:public:{fingerprint}"


def _enforce_rate_limit(storage: Storage, principal: str) -> None:
    limit = _rate_limit_per_minute()
    if not storage.consume_rate_limit(principal, limit):
        raise HTTPException(
            status_code=429,
            detail="Request rate limit exceeded.",
            headers={"Retry-After": "60"},
        )


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
@app.get("/api/v1/health")  # the published community node's credential-test path
async def healthz() -> Dict[str, Any]:
    # /api/v1/health is where n8n-nodes-pisama's credential "Test" button GETs
    # (baseURL {apiUrl} + "/health"); aliasing it here makes the credential
    # validate green against a self-hosted server. Unauthenticated, like /healthz.
    return {"status": "ok", **_deployment_provenance()}


@lru_cache(maxsize=1)
def _product_capabilities() -> Dict[str, Any]:
    path = Path(__file__).with_name("product_capabilities.generated.json")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/v1/capabilities")
async def product_capabilities(response: Response) -> Dict[str, Any]:
    """Public license, deployment, allowance, and capability contract."""

    provenance = _deployment_provenance()
    response.headers["X-Pisama-Build-Revision"] = provenance["build_revision"]
    response.headers["X-Pisama-Source-Repository"] = provenance["source_repository"]
    if provenance["source_revision_url"]:
        response.headers["X-Pisama-Source-Revision-URL"] = provenance[
            "source_revision_url"
        ]
    return _product_capabilities()


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
        report = await run_in_threadpool(process_execution, payload, storage)
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


@app.post("/api/v1/n8n/evaluate", dependencies=[Depends(require_auth)])
async def n8n_evaluate(payload: Any = Body(...)) -> Dict[str, Any]:
    """Analyze one real n8n execution without retaining or broadcasting it."""
    try:
        analysis = await run_in_threadpool(analyze_execution, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    provenance = _deployment_provenance()
    return evaluation_response(
        analysis,
        build_revision=provenance["build_revision"],
        engine_version=provenance["engine_version"],
    )


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
    "/api/v1/detections/{detection_id}/seen", dependencies=[Depends(require_auth)]
)
async def mark_detection_seen(
    detection_id: int, storage: Storage = Depends(get_storage)
) -> Dict[str, Any]:
    """Record that an operator opened this detection's detail view (first timestamp
    wins; idempotent). The sound denominator for diagnosis acceptance — accepted/seen
    instead of the self-selected accepted/reviewed sample. On a PISAMA_PUBLIC_READ
    demo, anonymous viewers' pings 401 by design: only authed operators record seen."""
    seen = storage.mark_detection_seen(detection_id)
    if seen is None:
        raise HTTPException(status_code=404, detail="Unknown detection id.")
    return seen


@app.post(
    "/api/v1/detections/{detection_id}/feedback", dependencies=[Depends(require_auth)]
)
async def submit_detection_feedback(
    detection_id: int,
    body: Dict[str, Any],
    request: Request,
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
    feedback = storage.submit_detection_feedback(
        detection_id,
        verdict,
        note,
        actor_principal=request.state.auth_principal,
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Unknown detection id.")
    storage.record_operational_event("feedback_recorded", {"verdict": verdict})
    return feedback


_EVALUATION_SPLITS = {"regression", "holdout"}


def _evaluation_split_scores(
    cases: List[Dict[str, Any]], case_results: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    split_by_id = {item["id"]: item["split"] for item in cases}
    scores = {
        split: {"n": 0, "exact_set_matches": 0, "exact_set_accuracy": None}
        for split in sorted(_EVALUATION_SPLITS)
    }
    for result in case_results:
        split_score = scores[split_by_id[result["id"]]]
        split_score["n"] += 1
        if result["exact_match"]:
            split_score["exact_set_matches"] += 1
    for split_score in scores.values():
        if split_score["n"]:
            split_score["exact_set_accuracy"] = (
                split_score["exact_set_matches"] / split_score["n"]
            )
    return scores


def _validated_evaluation_label(
    body: Dict[str, Any],
) -> tuple[List[str], str, str]:
    modes = body.get("expected_modes")
    split = body.get("split")
    evidence = body.get("label_evidence")
    if not isinstance(modes, list) or any(
        not isinstance(mode, str) or not mode for mode in modes
    ):
        raise HTTPException(status_code=422, detail="expected_modes must be a list of strings.")
    if len(modes) != len(set(modes)):
        raise HTTPException(status_code=422, detail="expected_modes must not contain duplicates.")
    unknown = sorted(set(modes) - FAILURE_MODES)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown taxonomy v{TAXONOMY_VERSION} failure modes: {unknown}",
        )
    if split not in _EVALUATION_SPLITS:
        raise HTTPException(
            status_code=422, detail="split must be regression or holdout."
        )
    if not isinstance(evidence, str) or not evidence.strip():
        raise HTTPException(
            status_code=422, detail="label_evidence must be a non-empty string."
        )
    return modes, split, evidence


@app.post(
    "/api/v1/detections/{detection_id}/evaluation-case",
    dependencies=[Depends(require_auth)],
    status_code=201,
)
async def create_evaluation_case(
    detection_id: int,
    body: Dict[str, Any],
    request: Request,
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Freeze a feedback-reviewed real execution as an immutable labeled case."""
    modes, split, evidence = _validated_evaluation_label(body)
    try:
        result = storage.create_evaluation_case(
            detection_id,
            modes,
            split,
            evidence,
            TAXONOMY_VERSION,
            created_by_principal=request.state.auth_principal,
        )
    except DuplicateEvaluationCase as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Detection already has evaluation case {exc.existing_id}.",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown detection id.")
    storage.record_operational_event(
        "evaluation_case_created",
        {"case_id": result["id"], "split": split, "mode_count": len(modes)},
    )
    return result


@app.post(
    "/api/v1/evaluation-cases/{case_id}/revisions",
    dependencies=[Depends(require_auth)],
    status_code=201,
)
async def revise_evaluation_case(
    case_id: int,
    body: Dict[str, Any],
    request: Request,
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Append a correction after a new, explicitly recorded operator review."""
    modes, split, evidence = _validated_evaluation_label(body)
    try:
        result = storage.revise_evaluation_case(
            case_id,
            modes,
            split,
            evidence,
            TAXONOMY_VERSION,
            created_by_principal=request.state.auth_principal,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown evaluation case id.")
    storage.record_operational_event(
        "evaluation_case_revised",
        {"case_id": case_id, "revision": result["revision"]},
    )
    return result


@app.get("/api/v1/evaluation-cases", dependencies=[Depends(require_auth)])
async def list_evaluation_cases(
    storage: Storage = Depends(get_storage),
) -> List[Dict[str, Any]]:
    """List reviewed case metadata. Retained execution payloads are excluded."""
    return storage.list_evaluation_cases()


@app.get(
    "/api/v1/evaluation-cases/{case_id}/revisions",
    dependencies=[Depends(require_auth)],
)
async def list_evaluation_case_revisions(
    case_id: int,
    storage: Storage = Depends(get_storage),
) -> List[Dict[str, Any]]:
    """Return every immutable review revision for audit and correction review."""
    result = storage.list_evaluation_case_revisions(case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown evaluation case id.")
    return result


@app.get("/api/v1/evaluation-cases/export", dependencies=[Depends(require_auth)])
async def export_evaluation_cases(
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Export credential-redacted inline cases for the canonical offline scorer."""
    try:
        return storage.export_evaluation_cases(TAXONOMY_VERSION)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@app.get("/api/v1/evaluation-cases/score", dependencies=[Depends(require_auth)])
async def score_evaluation_cases(
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Score the current reviewed corpus without returning retained payloads."""
    try:
        manifest = storage.export_evaluation_cases(TAXONOMY_VERSION)
        cases = manifest["cases"]
        score = score_labeled_executions(
            (
                item["id"],
                item["payload"],
                set(item["expected_modes"]),
            )
            for item in cases
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    return {
        "evaluation_schema_version": "1",
        "taxonomy_version": TAXONOMY_VERSION,
        "build_revision": build_revision(),
        "by_split": _evaluation_split_scores(cases, score["cases"]),
        **score,
    }


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
        "previous_error_workflow": (workflow.get("settings") or {}).get(
            "errorWorkflow"
        ),
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
            # Newer n8n (observed on n8n Cloud, 2026-07-21) only INVOKES an error
            # workflow that is ACTIVE; 1.70.0 invokes it unactivated. An inactive
            # target stays eligible (activation is one click) but the operator
            # must know, or the route silently never delivers.
            active = bool(full.get("active"))
            reason = None
            if not eligible:
                reason = "No Error Trigger node."
            elif not active:
                reason = (
                    "Inactive: newer n8n versions only invoke ACTIVE error "
                    "workflows. Activate it after choosing."
                )
            targets.append(
                {
                    "id": candidate_id,
                    "name": item.get("name"),
                    "eligible": eligible,
                    "active": active,
                    "reason": reason,
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
        raise HTTPException(
            status_code=422, detail="Detection carries no failing node."
        )
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
        raise HTTPException(
            status_code=422, detail="Repair is not a guardrail proposal."
        )
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
        updated = storage.set_guardrail_destination(repair_id, built["workflow"], guard)
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
        storage.record_repair_snapshot(repair_id, snapshot, repair["proposed_workflow"])

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
