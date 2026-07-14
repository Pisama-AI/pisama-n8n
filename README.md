# Pisama for n8n

Failure detection for n8n workflows. Fair-code and self-hostable; the paid tier (fix
suggestions and auto-fixing) runs in the Pisama cloud.

> **Status: local scaffold.** This repo is not published. It is an extraction of the
> detection engine from the Pisama monorepo, laid out to show the shape of the standalone
> product. The engine is real and parity-verified; the server and dashboard are skeletons.

## What's here

```
engine/     pisama-n8n-engine — the detection engine (PyPI target). Pure Python, the 6
            structural detectors import with ZERO config (no DB, no settings). Fair-code.
server/     FastAPI self-host server — single-tenant, SQLite default, HMAC webhook, SSE.
            SKELETON: the webhook route calls the engine; storage/auth/SSE are TODO.
dashboard/  Minimal Next.js dashboard (~10 routes). README only — not yet scaffolded.
node/       n8n-nodes-pisama — the n8n community node. MIT (n8n verified-node requirement).
deploy/     docker-compose + Dockerfile skeletons for `docker compose up` self-host.
benchmarks/ parity_check.py — proves the extracted engine matches the monorepo.
scripts/    extract_from_monorepo.py — the vendoring/sync tool + CI drift gate.
```

## The engine works today

```python
from pisama_n8n_engine.orchestrator import analyze
report = analyze(workflow_json=my_n8n_workflow)      # structural lane
for d in report.fired:
    print(d.detector, d.confidence, d.explanation)
```

Six structural detectors: cycle, schema, resource, timeout, error, complexity. The
execution-lane detectors (timeout/error/resource) also run on parsed runtime data via
`analyze(turns=...)` — the runtime-observed product.

## Licensing (the OSS/paid boundary)

- `engine/`, `server/`, `dashboard/`, `deploy/` — **fair-code** (Sustainable Use License,
  like n8n itself). Source-available, free for internal use, no competing commercial
  hosting. NOT OSI "open source"; call it "fair-code". See [LICENSE](LICENSE) (placeholder).
- `node/` — **MIT** (n8n's verified-community-node program requires it). See node/LICENSE.
- **Fix suggestions and auto-fixing** are NOT in this repo. They run in the Pisama cloud
  and are the paid tier. The self-host server calls the cloud with an API key; the user's
  n8n credentials never leave their network.

## Single source of truth

The detectors live in the Pisama monorepo (where the golden data, judges, and calibration
harness are). This repo VENDORS them via `scripts/extract_from_monorepo.py`, and
`benchmarks/parity_check.py` fails CI if the vendored copy ever diverges. Detector fixes
land in the monorepo and are re-extracted — never edited here (files carry a VENDORED
banner). This prevents the two-copy drift that has already bitten the project once.

## Before this can go public (founder actions)

1. Finalize the Sustainable Use License text (replace the LICENSE placeholder).
2. Confirm relicensing the n8n detector subset out of the monorepo's BSL-1.1 package
   (sole-authorship verified — legally clean).
3. Choose the repo name/org and create the GitHub repo.
4. Submit the node to n8n's verified-community-node program.

## Honest state of detection quality

Structural precision is real and verified (Schema/Complexity/Resource: 0 false positives
on real n8n templates after tuning). Recall is not yet validated against real-world n8n
failures — current positive fixtures are synthetic, and the Cycle detector is unsolved
(n8n workflows are DAGs; their "loops" are behavioral, not graph cycles). Validating
recall needs mined real-world failure data. Do not publish recall/F1 claims until then.
