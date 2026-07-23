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
- **Repair safety**: deterministic and cloud-generated proposals are persisted
  server-side. Apply and rollback accept a repair id, never client-supplied workflow
  JSON or snapshots. Both reject a stale workflow rather than overwriting an
  operator's later edit.

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

The node's own docs assume the hosted platform (pisama.ai). In the node's **Pisama API**
credential (field names below are verbatim from `n8n-nodes-pisama@0.3.0` on npm), set:

- **API URL**: your server base **with the `/api/v1` suffix**, e.g.
  `http://your-host:8400/api/v1`. The node's default is `https://api.pisama.ai/api/v1`
  and it appends `/n8n/webhook`; drop the `/api/v1` and the POST 404s. (This is also the
  base the credential's **Test** button GETs `/health` against — the server aliases
  `/api/v1/health` to its health check so Test validates green.)
- **API Key**: the value of `PISAMA_API_KEY`. The node always sends it as
  `X-Pisama-API-Key`, which this server accepts on its own.
- **Webhook Secret**: leave **empty** to authenticate by the API key alone (the node then
  sends no signature). Set it to HMAC-sign every POST — it must equal the server's
  `PISAMA_WEBHOOK_SECRET`, or `PISAMA_API_KEY` if you didn't set a separate secret. When
  set, the server enforces the signature plus replay protection.

No node changes needed; the node as published on npm works unmodified.

## Endpoints

Ingestion + detections:

- `POST /api/v1/n8n/webhook`: ingest one execution (push channel).
- `POST /api/v1/n8n/sync`: poll the configured n8n and ingest new executions.
- `GET /api/v1/detections`: every stored detection (each carries the ingest timestamp).
- `GET /api/v1/detections/{id}`: one enriched detection.
- `GET /api/v1/detections/{id}/trace`: the per-node execution trace behind a detection.
- `POST /api/v1/detections/{id}/seen`: mark a detection reviewed (feeds the
  review-coverage metric).
- `POST /api/v1/detections/{id}/feedback`: operator verdict (accept/reject) on a
  detection.
- `GET /api/v1/stream`: SSE stream of live detection events (token via `?token=`).

Deterministic repairs (free, no model involved):

- `POST /api/v1/n8n/guardrail`: propose an input-schema guardrail from a data-contract
  detection.
- `POST /api/v1/n8n/repairs/{id}/destination`: choose the guardrail's rejection
  destination (required before apply).
- `POST /api/v1/n8n/error-route`: propose an error-route repair from a
  missing-error-workflow detection.
- `GET /api/v1/n8n/repairs/{id}/error-targets`: candidate target workflows, each with
  eligibility and an activation warning when needed.
- `POST /api/v1/n8n/repairs/{id}/error-target`: choose the target error workflow
  (required before apply).
- `POST /api/v1/n8n/apply`: apply any configured repair by `repair_id` through the
  guarded state machine (claim, freshness check, snapshot, bounded diff). Free for
  deterministic repairs; the same endpoint also applies paid fix proposals.
- `POST /api/v1/n8n/rollback`: restore the pre-repair workflow; refused if the
  workflow changed since apply.

Reliability cases (the evidence trail behind every applied repair):

- `GET /api/v1/reliability-cases`, `GET /api/v1/reliability-cases/{id}`: observation
  state, success counts, recurrence, probe evidence.
- `GET /api/v1/reliability-cases/{id}/candidate-executions`: executions eligible as
  probe evidence.
- `POST /api/v1/reliability-cases/{id}/guard-verification`: record a guardrail probe
  (malformed rejected / valid passed).
- `POST /api/v1/reliability-cases/{id}/route-verification`: record a delivered
  routed-incident probe for an error-route repair.
- `POST /api/v1/reliability-cases/{id}/outcome`: a human concludes the case; refused
  until the evidence bar is met.

Operations + metrics:

- `GET /api/v1/operations/summary`: dashboard rollup (executions, detections, repairs).
- `GET /api/v1/reliability/metrics`: the five outcome metrics with honest denominators
  (diagnosis acceptance, verified remediation, recurrence reduction, time to control,
  durable-control share).

Paid tier (cloud key required):

- `GET /api/v1/paid/status`: paid-tier availability, gated on `PISAMA_CLOUD_KEY`.
- `POST /api/v1/n8n/fix`: generate and persist a read-only paid repair proposal
  (applied and rolled back via the shared `/n8n/apply` + `/n8n/rollback` above).

Liveness:

- `GET /healthz` (alias `GET /api/v1/health`): liveness; the alias is the community
  node's credential-Test path.

## Status

Implemented + tested (no mocks): both ingestion channels, both detection lanes, SQLite
persistence with dedup, all three auth forms (bearer, API-key header, HMAC with replay
protection), CORS, live SSE, background polling, and a guarded repair lifecycle. The
webhook + storage + auth path is covered by e2e tests including a contract suite that
signs exactly like the published node; the polling channel has a live e2e gated on
`PISAMA_HARNESS_N8N=1` + a real n8n.
