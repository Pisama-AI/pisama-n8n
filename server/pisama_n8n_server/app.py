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

from pisama_n8n_server.n8n_client import client_from_env
from pisama_n8n_server.poller import poll_once
from pisama_n8n_server.processing import process_execution
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
    return process_execution(payload, storage)


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
        return await poll_once(client, storage)
    finally:
        await client.aclose()


@app.get("/api/v1/detections", dependencies=[Depends(require_auth)])
async def list_detections(
    storage: Storage = Depends(get_storage),
) -> List[Dict[str, Any]]:
    return storage.list_detections()
