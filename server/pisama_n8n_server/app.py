"""pisama_n8n_server.app — single-tenant self-host server.

Runs the Pisama n8n detection engine as a small FastAPI service that a user
can self-host next to their own n8n instance. Scope for this skeleton:

  - SQLite by default (Postgres optional later) — storage is a TODO below.
  - Static bearer token auth — TODO, not wired yet.
  - Three planned ingestion channels (community node webhook is the only one
    implemented here; error-workflow and API polling are TODO elsewhere).

This is a "see the shape" scaffold, not a working server.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from pisama_n8n_engine.orchestrator import analyze

# TODO: from pisama_n8n_engine.trace.n8n_parser import parse_execution_to_turns
# TODO: SQLAlchemy engine + session (SQLite file by default, e.g. pisama_n8n.db)
# TODO: static bearer token dependency (Authorization: Bearer <token>) for all routes

app = FastAPI(
    title="Pisama n8n Server",
    description="Self-host detection server for n8n workflow executions.",
    version="0.1.0",
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/n8n/webhook")
async def n8n_webhook(request: Request) -> dict[str, Any]:
    """Receive an n8n execution payload from the community webhook node.

    Expects a JSON body shaped like an n8n execution export, with a
    top-level "workflow" key holding the workflow JSON.
    """
    payload = await request.json()
    workflow_json = payload.get("workflow", {})

    # TODO: turns = parse_execution_to_turns(payload) — reconstruct per-node
    # turns from the execution's run data instead of just the static workflow.
    report = analyze(workflow_json=workflow_json)

    # TODO: persist `report` (and the raw payload) via SQLAlchemy/SQLite.

    return report.to_dict()


@app.get("/api/v1/detections")
async def list_detections() -> list[dict[str, Any]]:
    # TODO: read from storage once persistence is wired up.
    return []
