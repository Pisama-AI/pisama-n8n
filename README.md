# Pisama for n8n

[![CI](https://github.com/Pisama-AI/pisama-n8n/actions/workflows/ci.yml/badge.svg)](https://github.com/Pisama-AI/pisama-n8n/actions/workflows/ci.yml)

Failure detection for n8n workflows. Fair-code and self-hostable; the paid tier (fix
suggestions and auto-fixing) runs in the Pisama cloud.

> **Status: early release (fair-code).** The engine (structural detection), the
> self-host server (webhook + API-polling ingestion, SQLite, live SSE), and the
> dashboard all work and are verified end-to-end against a real n8n. The n8n community
> node ships separately on npm (`n8n-nodes-pisama`). The paid cloud tier (fix
> suggestions + auto-apply) is gated behind a cloud key.
>
> **Honest about quality:** detector *precision* is measured on real n8n templates and is
> solid. *Recall* was validated in 2026-07 against failures mined from real community
> workflows: error and resource detection reached 1.00/1.00 on that corpus after fixes
> (in-sample, disclosed); timeout recall remains open. The cycle detector fires only on
> genuinely unbounded cycles, and true infinite loops are rare in real workflows. See
> the engine README and `eval/campaigns/2026-07-guard-campaign.md` for the full
> methodology, funnels, and every disclosed limitation.

## Quickstart (self-host)

Docker (server on `:8400`, SQLite persisted in a volume):

```bash
git clone https://github.com/Pisama-AI/pisama-n8n.git
cd pisama-n8n/deploy
PISAMA_API_KEY=choose-a-secret docker compose up --build
# or, with the dashboard on :3000
PISAMA_API_KEY=choose-a-secret docker compose --profile ui up --build
```

Then connect your n8n. Either channel works; neither requires the other.

- **Polling** (Pisama reaches your n8n): set `PISAMA_N8N_URL` and `PISAMA_N8N_API_KEY`
  in the server environment (n8n API keys are minted under Settings, n8n API), then
  trigger a sync from the dashboard's Settings page or with
  `curl -X POST -H "Authorization: Bearer $PISAMA_API_KEY" http://localhost:8400/api/v1/n8n/sync`.
- **Push** (your n8n reaches Pisama, works behind firewalls): install the
  [`n8n-nodes-pisama`](https://www.npmjs.com/package/n8n-nodes-pisama) community node
  in n8n, create a Pisama API credential with API URL
  `http://<server-host>:8400/api/v1` and your `PISAMA_API_KEY` as the API key
  (set `PISAMA_WEBHOOK_SECRET` on the server and in the credential to use HMAC
  signatures instead), and add the Pisama node to the workflows you want watched.

Without Docker (Python 3.11 or newer):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e engine -e server
PISAMA_API_KEY=choose-a-secret uvicorn pisama_n8n_server.app:app --port 8400
```

Dashboard without Docker (Node 20 or newer): `cd dashboard && npm ci && npm run dev`,
with `NEXT_PUBLIC_API_BASE` pointing at the server (default `http://localhost:8400`).

### Supported n8n versions

The end-to-end guardrail lifecycle gate passes against pinned n8n **1.70.0** and
**2.32.0** (the current stable at the time of writing); the dogfood stack runs
**1.91.3**, and a live n8n Cloud instance tracks the current release. Ingestion is
payload-format based and works across this range. One
behavioral difference that matters for the error-route repair: current n8n versions
only invoke error workflows that are **active**, while older versions (1.70.0) also
invoke inactive ones. When Pisama points a workflow at an error handler, activate the
handler workflow; the repair UI warns when the chosen target is inactive.

## What's here

```
engine/     pisama-n8n-engine: the detection engine (PyPI target). Pure Python, the
            structural detectors import with ZERO config (no DB, no settings). Fair-code.
server/     FastAPI self-host server: single-tenant, SQLite default, webhook ingest
            (bearer-token auth, plus the community node's HMAC signatures via
            PISAMA_WEBHOOK_SECRET, falling back to PISAMA_API_KEY), API-polling
            ingestion, live SSE. Working; e2e-tested.
dashboard/  Next.js dashboard (overview, detections list + detail, settings). Working;
            typechecks, builds, Playwright-smoked.
deploy/     docker-compose + Dockerfile for `docker compose up` self-host.
benchmarks/ parity_check.py + fixtures/ + golden.json: the engine regression gate CI runs
            (engine verdicts vs a committed golden corpus; no monorepo needed).
scripts/    extract_from_monorepo.py: the detector vendoring/sync tool.
```

The **n8n community node** (`n8n-nodes-pisama`, MIT) lives in its own repo,
[Pisama-AI/n8n-nodes-pisama](https://github.com/Pisama-AI/n8n-nodes-pisama), and on
[npm](https://www.npmjs.com/package/n8n-nodes-pisama), not here. It is not required for
ingestion: the webhook and API-polling channels work without any node install.

## The engine works today

```python
from pisama_n8n_engine.orchestrator import analyze
report = analyze(workflow_json=my_n8n_workflow)      # structural lane
for d in report.fired:
    print(d.detector, d.confidence, d.explanation)
```

Evidence-gated detector suite: cycle, resource, timeout, classified error, complexity,
runtime data contracts, AI output truncation, and missing error workflows, surfaced only
when execution evidence supports them. (The old static schema detector
ships in the package, but its static path is deliberately disabled because it cannot be
made precise against n8n's dynamic JSON data model; it never fires.) Runtime detectors
run only on parsed execution evidence via
`analyze(turns=...)`, the runtime-observed product.

## Licensing (the fair-code/paid boundary)

- `engine/`, `server/`, `dashboard/`, `deploy/` are **fair-code** (Sustainable Use License,
  like n8n itself). Source-available, free for internal use, no competing commercial
  hosting. NOT OSI "open source"; call it "fair-code". See [LICENSE](LICENSE).
- The **n8n community node** (`n8n-nodes-pisama`, MIT) is published separately, in its
  own repo and on npm, not in this repository (n8n's verified-node program requires MIT).
- **Fix suggestions and auto-fixing** are NOT in this repo. They run in the Pisama cloud
  and are the paid tier. The self-host server calls the cloud with an API key; the user's
  n8n credentials never leave their network. A suggestion is stored as a server-owned,
  reviewable repair record. When auto-apply is enabled, Pisama refuses to overwrite a
  workflow changed since the proposal and preserves a guarded rollback point.

## Single source of truth

Shared detectors originate in the Pisama monorepo, where the golden data, judges, and
calibration harness live. This repository also carries n8n-only runtime extensions that
operate on execution evidence unavailable in the multi-platform path. CI runs
`benchmarks/parity_check.py`, which freezes the standalone engine's verdicts on a committed
corpus (`benchmarks/fixtures/` vs `benchmarks/golden.json`). Shared-detector changes are
still re-extracted from the monorepo; n8n-only extensions are validated against dedicated
dogfood execution evidence.

## Roadmap

- **Detection recall**: validating against mined real-world n8n failures (the current
  precision numbers are trustworthy; recall is the open work). This is the priority.
- **n8n community node**: `n8n-nodes-pisama` (MIT, dependency-free) is published on npm
  and installable on self-hosted n8n today. n8n Cloud's *verified* listing is a later
  step, not a blocker: the webhook and API-polling ingestion channels need no node
  install and work on both self-hosted and Cloud.
- **AI-agent detectors**: loop/hallucination/derailment on n8n AI Agent nodes, as a paid
  cloud capability (they need embeddings and don't belong in the dependency-free engine).

## Honest state of detection quality

Structural precision is real and verified (Complexity/Resource: 0 false positives on
real n8n templates after tuning; the static schema path fired at near-zero precision on
real community workflows and is permanently disabled). Recall is not yet validated against
real-world n8n failures: current positive fixtures are synthetic. The Cycle detector
works: it recognizes n8n's intentional bounded loops (Loop Over Items, iteration caps,
explicit break conditions) and fires only on genuinely unbounded cycles. True infinite
loops are rare in real workflows, which is exactly why recall there is hard to measure.
Validating recall needs mined real-world failure data. Do not publish recall/F1 claims
until then.
