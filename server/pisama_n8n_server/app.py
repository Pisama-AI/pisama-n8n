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

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from pisama_n8n_engine.orchestrator import DetectionReport, analyze
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata

from pisama_n8n_server.storage import Storage

logger = logging.getLogger("pisama_n8n_server")

app = FastAPI(
    title="Pisama n8n Server",
    description="Self-host detection server for n8n workflow executions.",
    version="0.1.0",
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

def require_auth(authorization: Optional[str] = Header(default=None)) -> None:
    """Static bearer-token auth. If ``PISAMA_API_KEY`` is unset, dev mode: allow.

    TODO: additionally accept the community node's HMAC signature header.
    """
    expected = os.environ.get("PISAMA_API_KEY")
    if not expected:
        logger.warning("PISAMA_API_KEY unset — running open (dev mode).")
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")


# --- payload handling -----------------------------------------------------

def _extract_workflow_and_runtime(payload: Dict[str, Any]):
    """Pull the workflow JSON and whether runData is present from a payload.

    A captured execution export carries the workflow under ``workflow`` (or
    ``workflowData``) plus ``data.resultData.runData``. A bare workflow POST
    (e.g. a complexity case) IS the workflow itself (``nodes``/``connections``).
    """
    workflow_json = payload.get("workflow") or payload.get("workflowData")
    if workflow_json is None and ("nodes" in payload or "connections" in payload):
        workflow_json = payload

    run_data = (
        payload.get("data", {}).get("resultData", {}).get("runData")
        if isinstance(payload.get("data"), dict)
        else None
    )
    return workflow_json, bool(run_data)


# --- routes ---------------------------------------------------------------

@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/n8n/webhook", dependencies=[Depends(require_auth)])
async def n8n_webhook(
    request: Request,
    storage: Storage = Depends(get_storage),
) -> Dict[str, Any]:
    """Receive an n8n execution payload, run both lanes, persist, return report."""
    payload = await request.json()
    workflow_json, has_runtime = _extract_workflow_and_runtime(payload)

    workflow_id = payload.get("workflowId")
    if workflow_json and isinstance(workflow_json, dict):
        workflow_id = workflow_id or workflow_json.get("id")

    report: DetectionReport = DetectionReport(workflow_id=workflow_id)

    # Structural lane — from the static workflow JSON.
    if workflow_json:
        structural = analyze(workflow_json=workflow_json, workflow_id=workflow_id)
        report.detections.extend(structural.detections)

    # Runtime lane — from the execution's runData.
    if has_runtime:
        turns, metadata = execution_to_turns_and_metadata(payload)
        runtime = analyze(turns=turns, metadata=metadata, workflow_id=workflow_id)
        report.detections.extend(runtime.detections)

    storage.save_report(payload, report)
    return report.to_dict()


@app.get("/api/v1/detections", dependencies=[Depends(require_auth)])
async def list_detections(
    storage: Storage = Depends(get_storage),
) -> List[Dict[str, Any]]:
    return storage.list_detections()
