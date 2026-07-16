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
- **Repair safety**: cloud-generated proposals are persisted server-side. Apply and rollback
  accept a repair id, never client-supplied workflow JSON or snapshots. Both reject a stale
  workflow rather than overwriting an operator's later edit.

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
- `POST /api/v1/n8n/fix` — generate and persist a read-only paid repair proposal.
- `POST /api/v1/n8n/apply` — apply a reviewed proposal by `repair_id`, after a live
  workflow freshness check.
- `POST /api/v1/n8n/rollback` — roll back an applied proposal by `repair_id`, only when
  the workflow still matches Pisama's applied version.
- `GET /healthz` — liveness.

## Status

Implemented + tested (no mocks): both ingestion channels, both detection lanes, SQLite
persistence with dedup, bearer and community-node HMAC auth, CORS, SSE live updates,
an optional background polling loop, and a guarded repair lifecycle. The polling channel's
live e2e remains gated on `PISAMA_HARNESS_N8N=1` and a real n8n instance.
