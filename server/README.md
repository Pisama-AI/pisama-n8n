# pisama-n8n-server

Single-tenant self-host server for the Pisama n8n detection engine. Run this next to your
own n8n instance to get detection reports without sending workflow data to Pisama's hosted
platform.

## Design

- **Storage**: real SQLite by default (`pisama_n8n.db`); set `DATABASE_URL` for Postgres.
- **Auth**: `PISAMA_API_KEY` gates every write. Three accepted forms (unset = dev mode,
  open with a logged warning); see the auth section below.
- **CORS**: `PISAMA_CORS_ORIGINS` (comma-separated, default `*`) so the separate-origin
  dashboard can read the API.
- Both detection lanes run per execution: structural (from the workflow JSON) + runtime
  (from the execution's runData), merged into one stored report.

## Ingestion channels

1. **Community node / webhook push**: `POST /api/v1/n8n/webhook` with an n8n execution
   payload (the `n8n-nodes-pisama` node, or an n8n error-workflow HTTP node, posts here).
2. **API polling (zero-setup)**: `POST /api/v1/n8n/sync` pulls recent executions from your
   n8n and ingests the new ones, deduping on the upstream execution id. Configure with
   `PISAMA_N8N_URL` + `PISAMA_N8N_API_KEY`. No workflow edits, no node install. Call it on
   a cron, or set `PISAMA_POLL_INTERVAL` (seconds) and the server polls by itself.

## Auth: three ways in

Every POST requires one of the following when `PISAMA_API_KEY` is set:

1. `Authorization: Bearer <PISAMA_API_KEY>` (curl, error-workflow HTTP nodes, scripts).
2. `X-Pisama-API-Key: <PISAMA_API_KEY>` (the community node always sends this header).
3. The community node's HMAC signature: `X-Pisama-Signature: sha256=<hex>` where the
   digest is HMAC-SHA256 over `{timestamp}.{body}`, plus `X-Pisama-Timestamp` (unix
   seconds, accepted within a 5 minute window) and `X-Pisama-Nonce` (single-use; a
   replayed request is rejected with 401). The signing secret is
   `PISAMA_WEBHOOK_SECRET` when set, else `PISAMA_API_KEY`.

This matches the published `n8n-nodes-pisama` v0.3.0 wire contract exactly, and mirrors
the hosted backend's `verify_webhook_if_configured` semantics (same signature base, same
freshness window, nonce replay protection). The hosted backend keys webhook secrets per
registered workflow; this server is single-tenant, so one secret covers it.

### Pointing the published community node at this server

The node's own docs assume the hosted platform (pisama.ai). Against this server, fill
its Pisama API credential like this:

- **Base URL**: your server, e.g. `http://your-host:8400` (the docker-compose port; the
  node posts to `/api/v1/n8n/webhook` under it).
- **API Key**: the value of `PISAMA_API_KEY`.
- **Webhook Secret** (optional): the value of `PISAMA_WEBHOOK_SECRET` if you set one;
  leave both unset or both equal to the API key otherwise.

No node changes needed; v0.3.0 as published on npm works unmodified.

## Endpoints

- `POST /api/v1/n8n/webhook`: ingest one execution (push channel).
- `POST /api/v1/n8n/sync`: poll the configured n8n and ingest new executions.
- `GET /api/v1/detections`: every stored detection (each carries the ingest timestamp).
- `GET /api/v1/detections/{id}`: one enriched detection.
- `GET /api/v1/detections/{id}/trace`: the per-node execution trace behind a detection.
- `GET /api/v1/stream`: SSE stream of live detection events (token via `?token=`).
- `GET /api/v1/paid/status`, `POST /api/v1/n8n/fix|apply|rollback`: paid tier
  (cloud-backed fix suggestions and auto-apply), gated on `PISAMA_CLOUD_KEY`.
- `GET /healthz`: liveness.

## Status

Implemented + tested (no mocks): both ingestion channels, both detection lanes, SQLite
persistence with dedup, all three auth forms (bearer, API-key header, HMAC with replay
protection), CORS, live SSE, background polling. The webhook + storage + auth path is
covered by e2e tests including a contract suite that signs exactly like the published
node; the polling channel has a live e2e gated on `PISAMA_HARNESS_N8N=1` + a real n8n.
