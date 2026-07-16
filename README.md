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
> solid; *recall* is not yet validated against real-world failures (current positive
> fixtures are synthetic) and the cycle detector is unsolved. We do not publish recall/F1
> claims yet. See the engine README.

## What's here

```
engine/     pisama-n8n-engine: the detection engine (PyPI target). Pure Python, the 6
            structural detectors import with ZERO config (no DB, no settings). Fair-code.
server/     FastAPI self-host server: single-tenant, SQLite default, HMAC webhook,
            API-polling ingestion, live SSE, bearer auth. Working; e2e-tested.
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

Six structural detectors: cycle, schema, resource, timeout, error, complexity. The
execution-lane detectors (timeout/error/resource) also run on parsed runtime data via
`analyze(turns=...)`, the runtime-observed product.

## Licensing (the OSS/paid boundary)

- `engine/`, `server/`, `dashboard/`, `deploy/` are **fair-code** (Sustainable Use License,
  like n8n itself). Source-available, free for internal use, no competing commercial
  hosting. NOT OSI "open source"; call it "fair-code". See [LICENSE](LICENSE).
- The **n8n community node** (`n8n-nodes-pisama`, MIT) is published separately, in its
  own repo and on npm, not in this repository (n8n's verified-node program requires MIT).
- **Fix suggestions and auto-fixing** are NOT in this repo. They run in the Pisama cloud
  and are the paid tier. The self-host server calls the cloud with an API key; the user's
  n8n credentials never leave their network.

## Single source of truth

The detectors live in the Pisama monorepo (where the golden data, judges, and calibration
harness are). This repo VENDORS them via `scripts/extract_from_monorepo.py`. CI runs
`benchmarks/parity_check.py`, which freezes the vendored engine's verdicts on a committed
corpus (`benchmarks/fixtures/` vs `benchmarks/golden.json`), so a regression or a botched
re-extraction fails the build. Maintainers additionally run `parity_check.py --monorepo
<path>` at re-extraction time to confirm the golden still matches the monorepo source of
truth. Detector fixes land in the monorepo and are re-extracted here, not edited in place.

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

Structural precision is real and verified (Schema/Complexity/Resource: 0 false positives
on real n8n templates after tuning). Recall is not yet validated against real-world n8n
failures: current positive fixtures are synthetic, and the Cycle detector is unsolved
(n8n workflows are DAGs; their "loops" are behavioral, not graph cycles). Validating
recall needs mined real-world failure data. Do not publish recall/F1 claims until then.
