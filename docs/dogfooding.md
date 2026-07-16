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
| n8n Cloud | A dedicated non-production Cloud workspace | API polling and webhook ingestion over the hosted API. This must be run by an operator with that workspace; do not use a customer workspace. |

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
- **Open compatibility finding:** on this n8n version, `POST /api/v1/workflows/{id}/activate`
  returns `200` and the workflow reads back as `active: true`, yet a production webhook
  immediately returns `404` as unregistered. No execution evidence has been promoted from
  that workflow path. Resolve this with a real n8n execution mechanism before claiming the
  webhook-trigger dogfood lane passes.
