# n8n dogfooding

Pisama dogfooding uses real n8n instances and their actual execution records. Do not
substitute mock HTTP servers, fabricated traces, or customer data. The Docker targets
in this repository own disposable internal data only.

## Supported lanes

| Lane | Target | What it proves |
| --- | --- | --- |
| Docker SQLite | `deploy/docker-compose.dogfood.yml` | Default self-host n8n install, webhook execution, and API polling. |
| Docker Postgres | Base compose plus `docker-compose.dogfood.postgres.yml` | n8n backed by Postgres, including restart and data persistence. |
| Version sweep | Set `N8N_VERSION` before startup | Compatibility with each explicitly supported n8n release. |
| n8n Cloud | A dedicated non-production Cloud project | API polling and webhook ingestion over the hosted API. Set `PISAMA_N8N_PROJECT_ID` so polling never reads another project. |

Start a disposable SQLite n8n target:

```bash
docker compose -p pisama-n8n-dogfood -f deploy/docker-compose.dogfood.yml up -d n8n
```

Create an owner and an API key in that instance, then start the Pisama server lane:

```bash
export PISAMA_DOGFOOD_N8N_API_KEY='your-disposable-n8n-key'
export PISAMA_DOGFOOD_API_KEY='local-pisama-key'
docker compose -p pisama-n8n-dogfood -f deploy/docker-compose.dogfood.yml \
  --profile server up -d
```

For Postgres, add `-f deploy/docker-compose.dogfood.postgres.yml`. Use a distinct
Compose project name for every lane so volumes, ports, and upgrade evidence cannot
cross-contaminate.

## Cloud lane

Create a dedicated project first, then issue a time-bound API key with only the
**Workflow and executions** scope group. Do not use an account's Personal project or
an unscoped server for this lane: n8n API-key scopes control capabilities, not which
project's executions may be read.

Set all four values before starting the server, and verify the project query returns
only the dedicated workflows before calling `/api/v1/n8n/sync`:

```bash
export PISAMA_N8N_URL='https://your-instance.app.n8n.cloud'
export PISAMA_N8N_API_KEY='your-time-bound-dogfood-key'
export PISAMA_N8N_PROJECT_ID='your-dedicated-project-id'
export PISAMA_API_KEY='local-pisama-key'
```

With `PISAMA_N8N_PROJECT_ID` set, the poller lists that project's workflows and then
fetches executions one workflow at a time. It never sends a broad executions request.

To run the Compose server against Cloud rather than the local n8n service, map those
values through the dogfood environment names and start only the server service:

```bash
export PISAMA_DOGFOOD_N8N_URL="$PISAMA_N8N_URL"
export PISAMA_DOGFOOD_N8N_API_KEY="$PISAMA_N8N_API_KEY"
export PISAMA_DOGFOOD_N8N_PROJECT_ID="$PISAMA_N8N_PROJECT_ID"
export PISAMA_DOGFOOD_API_KEY="$PISAMA_API_KEY"
docker compose -p pisama-n8n-cloud-dogfood -f deploy/docker-compose.dogfood.yml \
  --profile server up -d --build --no-deps server
```

## Evidence required from every run

1. A healthy execution and controlled executions for error, timeout, payload growth,
   retry/recovery, invalid credentials, broken expression, and bounded/unbounded loop.
2. The raw execution returned by that real n8n instance, retained only when it contains
   no credentials or customer information.
3. A webhook-ingestion result and an API-polling result from the same instance.
4. A repair record showing review, safe apply, a subsequent observed execution, rollback,
   and rejection after a deliberate human workflow edit.
5. The operations summary, including latest ingestion, poll result, detector counts,
   failed repairs, stale repair blocks, and operator feedback.

## Installation and upgrade gates

Run `scripts/verify_selfhost.sh` for every release. It uses an isolated Compose project,
fresh volume, and port `8402` by default, so it measures a clean installation without
touching an existing deployment.

For an upgrade check, retain the volume from a prior release, start the next image against
that volume, verify `/healthz`, detections, feedback, repair records, and operational
summary, then restore a backup into a second isolated project and repeat the same checks.

## External-readiness rule

Dogfood results are internal evidence, not a recall claim. Do not claim detector recall
or autonomous repair success until design partners supply independently adjudicated
incidents and repeated observed repair outcomes.

## Current internal evidence

2026-07-16:

- The isolated clean-install check (`scripts/verify_selfhost.sh`) passed against a freshly
  built server and a captured n8n failure execution.
- Docker n8n `1.91.3` is healthy in both the SQLite lane (`5681`) and the Postgres 16
  lane (`5682`), with separate projects and volumes.
- The SQLite companion Pisama server is running with a 60-second polling interval.
- A real n8n `1.91.3` webhook execution that deliberately raises an error has been created
  and polled through Pisama. The live polling E2E passed, including real n8n deduplication
  on the second poll and an `error` detection.
- Compatibility detail: create Webhook-node test workflows with a `webhookId` matching the
  configured path. Without it, n8n registers a workflow-scoped URL instead of the expected
  short production URL. This is covered by the live polling test.
- The poller now fetches the associated workflow for an execution before analysis because
  the n8n executions API omits that node context. The persistent Pisama dogfood database is
  the internal regression corpus; it contains only disposable internal executions.
- An n8n Cloud project-scoped lane passed a real webhook failure and polling run: one
  controlled execution was ingested, deduplication returned zero new executions on the
  next sync, and the error detector fired `F14`. The local Cloud-lane database was reset
  after an earlier unscoped startup, then verified to contain only the dedicated workflow.
- Cloud apply and rollback mechanics were exercised against that controlled workflow. A
  code-node repair applied and the workflow was restored; a deliberate post-apply human
  edit was rejected as stale before rollback. The next Cloud execution could not be
  observed because this Cloud instance reported its execution quota was exhausted.
- A fresh SQLite n8n `1.70.0` volume with an active controlled-failure workflow was
  backed up, started successfully on `1.91.3`, then restored from that pre-upgrade backup
  into a fresh `1.91.3` start. The workflow remained active and its webhook returned the
  expected controlled `500` after both the upgrade and restore.
- The disposable local `1.91.3` lane captured new real HTTP executions for a provider
  `429` and a `401` authentication rejection. The standalone detector classified them as
  `n8n_rate_limit` and `n8n_credential`, respectively. A real Code-node missing-field
  execution also fired the runtime-only `n8n_data_contract` detector.
- A retry-enabled unsafe HTTP write returned a real provider `502`, but this n8n release
  recorded one attempt. Pisama therefore reports `n8n_retry_not_observed`, rather than
  falsely claiming that a retry budget was exhausted. Duplicate-side-effect detection is
  deliberately held until a real execution records repeated unsafe action attempts.
- Repair verification now has a tenant-local case record. In the disposable SQLite lane,
  a real controlled failure was safely changed through the stale-workflow guard, a later
  successful execution was ingested by API polling, and the case remained `observing`.
  Pisama correctly refused to label a single success as prevention, then restored the
  original workflow and retained the rolled-back audit record.
- No real LLM token-limit or AI-agent tool/output-validation execution has yet been
  captured in this lane. The associated detectors remain evidence-gated and must not be
  described as validated until those captures exist.
