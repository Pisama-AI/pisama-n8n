# pisama-n8n-server

Single-tenant self-host server for the Pisama n8n detection engine. Run this next to your
own n8n instance to get detection reports without sending workflow data to Pisama's hosted
platform.

## Design

- **Storage**: real SQLite by default (`pisama_n8n.db`); set `DATABASE_URL` for Postgres.
- **Auth**: a static bearer token (`PISAMA_API_KEY`); unset = dev mode (open, logs a warning).
- **CORS**: `PISAMA_CORS_ORIGINS` (comma-separated, default `*`) so the separate-origin
  dashboard can read the API.
- Both detection lanes run per execution: structural (from the workflow JSON) + runtime
  (from the execution's runData), merged into one stored report.

## Ingestion channels

1. **Community node / webhook push** — `POST /api/v1/n8n/webhook` with an n8n execution
   payload (the `n8n-nodes-pisama` node, or an n8n error-workflow HTTP node, posts here).
2. **API polling (zero-setup)** — `POST /api/v1/n8n/sync` pulls recent executions from your
   n8n and ingests the new ones, deduping on the upstream execution id. Configure with
   `PISAMA_N8N_URL` + `PISAMA_N8N_API_KEY`. No workflow edits, no node install. Call it on a
   cron or from a scheduler.

## Endpoints

- `POST /api/v1/n8n/webhook` — ingest one execution (push channel).
- `POST /api/v1/n8n/sync` — poll the configured n8n and ingest new executions.
- `GET /api/v1/detections` — every stored detection (each carries the ingest timestamp).
- `GET /healthz` — liveness.

## Status

Implemented + tested (no mocks): both ingestion channels, both detection lanes, SQLite
persistence with dedup, bearer auth, CORS. The webhook + storage + auth path has 8 e2e
tests; the polling channel has a live e2e gated on `PISAMA_HARNESS_N8N=1` + a real n8n.

TODO: an SSE stream for live dashboard updates; a built-in background poll loop (today
`/sync` is triggered externally); the community node's HMAC signature as an auth option.
