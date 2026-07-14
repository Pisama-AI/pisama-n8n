# pisama-n8n-server

Single-tenant self-host server for the Pisama n8n detection engine. Run this
next to your own n8n instance to get detection reports without sending
workflow data to Pisama's hosted platform.

## Design

- **Storage**: SQLite by default (`pisama_n8n.db`), Postgres optional for
  larger deployments.
- **Auth**: a static bearer token, checked on every route.
- **Live updates**: an SSE stream for pushing new detections to the
  dashboard as they happen.
- **Ingestion channels** (three planned):
  1. Community n8n node posts execution payloads to `/api/v1/n8n/webhook`.
  2. n8n's built-in error-workflow mechanism, as an alternate trigger.
  3. Polling the n8n REST API directly for executions (no node install
     required).

## Status

Implemented:
- `POST /api/v1/n8n/webhook` — parses the workflow out of the payload and
  runs it through `pisama_n8n_engine.orchestrator.analyze`.
- `GET /healthz`

TODO:
- Storage (SQLAlchemy + SQLite/Postgres) — nothing is persisted yet.
- Bearer token auth.
- Execution-turn parsing via `pisama_n8n_engine.trace.n8n_parser`.
- SSE stream for live detections.
- Error-workflow and API-polling ingestion channels.
- `GET /api/v1/detections` currently returns `[]` unconditionally.
