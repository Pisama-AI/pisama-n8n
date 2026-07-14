# pisama-n8n server — runnable self-host server over the engine

**Goal:** A single-tenant FastAPI self-host server that ingests an n8n execution, runs BOTH
detection lanes via the engine (structural from the workflow JSON, runtime from the
execution runData), persists the detections to SQLite, and serves them back — proven by a
no-mocks test that POSTs REAL captured execution fixtures and asserts the right detections
come back stored.

**Verification command (run after every change):**
```bash
cd /Users/tuomonikulainen/pisama-n8n && \
  PYTHONPATH="engine:server" \
  /Users/tuomonikulainen/pisama/backend/.venv/bin/python -m pytest server/tests -q
```

Pass = exit 0, all server tests green. The tests MUST include (no mocks — real engine, real
SQLite, FastAPI TestClient):
1. POST each of a timeout / error / resource captured execution fixture to
   `/api/v1/n8n/webhook` (with the workflow def in the payload) → response contains the
   matching fired detection; a healthy fixture fires none of timeout/error/resource.
2. A structural case: POST a complexity fixture (workflow JSON) → schema/complexity
   structural detections are present in the response.
3. `GET /api/v1/detections` returns the stored detections after ingestion (persisted, not
   just echoed).
4. Auth: with `PISAMA_API_KEY` set, a request without the bearer header → 401; with it → 200.
5. `GET /healthz` → 200.
Fail = keep working. Do NOT open a browser, do NOT ask the user — fix and re-run.

**Fixtures to use (real, committed):** the captured executions live in the monorepo at
`/Users/tuomonikulainen/pisama-worktrees/n8n-eval-harness/n8n-workflows/executions/<lane>/`
and complexity workflows at `.../n8n-workflows/complexity/`. The test may read them from
there by absolute path (they are real data). Do NOT copy golden datasets into this repo.

**Do NOT touch:**
- `engine/` — it is the vendored source of truth and is parity-locked. USE it
  (`from pisama_n8n_engine.orchestrator import analyze`,
  `from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata`); do not
  edit it. If the engine seems to need a change, STOP and note it — do not patch it here.
- The captured execution fixtures — real data, read-only.
- `benchmarks/parity_check.py`, `scripts/extract_from_monorepo.py`.

**In scope to build:** everything under `server/pisama_n8n_server/` (storage models, the
webhook + detections + healthz routes, bearer auth) and `server/tests/`.

**Design constraints:**
- SQLite by default via SQLAlchemy 2.x (a `DATABASE_URL` env override for Postgres later).
  Two tables are enough: `executions` (id, workflow_id, received_at, raw) and `detections`
  (id, execution_id FK, detector, detected, confidence, failure_mode, explanation).
- Single-tenant: NO tenant_id anywhere.
- Auth: a static bearer token from `PISAMA_API_KEY`. If unset, log a warning and allow
  (dev mode). The webhook may additionally accept the node's HMAC later — leave a TODO,
  do not block on it.
- The webhook handler: parse the payload → if it carries a workflow def, run the structural
  lane `analyze(workflow_json=...)`; if it carries execution runData, also run the runtime
  lane via `execution_to_turns_and_metadata` + `analyze(turns=..., metadata=...)`; merge
  both into one stored report. A captured execution fixture carries BOTH (it has
  `data.resultData.runData` AND a `workflow` key), so both lanes fire.
- No mocks anywhere (repo rule). Real engine, real SQLite (a temp file or `:memory:` per
  test is fine — that is real SQLite, not a mock).

---

## Tasks

- [x] **Baseline** — run the verification command; it will fail (no tests yet / server is a
  skeleton). Record what exists under "## Baseline run".

- [x] **Storage** — add `server/pisama_n8n_server/storage.py`: SQLAlchemy models + a
  session/engine factory (SQLite default from `DATABASE_URL` or a local file), and a
  `save_report(execution_data, report)` + `list_detections()` helper.

- [x] **Webhook + routes** — flesh out `app.py`: `POST /api/v1/n8n/webhook` running both
  lanes and persisting; `GET /api/v1/detections` reading from storage; `GET /healthz`.
  Bearer auth dependency from `PISAMA_API_KEY`.

- [x] **Tests** — `server/tests/test_server.py` implementing the 5 assertions above with
  FastAPI TestClient + real fixtures. Add `server/tests/__init__.py`.

- [x] **Verify the gate** — run the verification command until green. Record results in
  "## Final Status".

- [x] **Commit** — in `/Users/tuomonikulainen/pisama-n8n` (git identity
  user.name=tn-pisama, user.email=tuomo@pisama.ai), message:
  `feat(server): runnable self-host server — both lanes, SQLite, no-mocks e2e test`.
  Do NOT push.

Output `DONE` once ALL boxes are checked AND the verification command passes. Do not output
`DONE` for any other reason. If the engine genuinely needs a change to make this work, STOP
and record it as a BLOCKED note rather than editing the engine or faking the test.

---

## Baseline run

Verification command (`pytest server/tests -q`) → **fail**: `ERROR: file or directory not
found: server/tests` / `no tests ran in 0.00s`. There is no `server/tests/` dir yet.

What exists: `server/pisama_n8n_server/app.py` is a skeleton FastAPI app — `/healthz`,
a `POST /api/v1/n8n/webhook` that runs only the structural lane (`analyze(workflow_json=...)`,
no runtime lane, no persistence), and `GET /api/v1/detections` returning `[]`. No storage,
no auth. Engine deps (fastapi 0.120.4, sqlalchemy 2.0.25, pytest, httpx) all present in the
venv. Engine smoke test confirms both lanes fire on real fixtures: timeout→timeout(0.95),
error→error(0.9), resource→resource(0.7), healthy→(none), complexity→schema(0.8)+complexity(0.85).
Fixture shapes: execution fixtures carry `workflow` + `data.resultData.runData`; complexity
fixtures are raw workflow JSON (`name`/`nodes`/`connections`, no wrapper).

## Notes

<agent writes findings here>

## Final Status

Verification command → **PASS**: `8 passed in 0.55s` (exit 0).

Built:
- `server/pisama_n8n_server/storage.py` — SQLAlchemy 2.x models (`executions`,
  `detections` FK), SQLite by default (`DATABASE_URL` override), `Storage.save_report()`
  + `Storage.list_detections()`. Real SQLite, temp file per test.
- `server/pisama_n8n_server/app.py` — `POST /api/v1/n8n/webhook` runs BOTH lanes
  (structural `analyze(workflow_json=...)`; runtime via `execution_to_turns_and_metadata`
  + `analyze(turns=..., metadata=...)`), merges into one report, persists, returns it.
  `GET /api/v1/detections` reads from storage. `GET /healthz`. Static bearer auth from
  `PISAMA_API_KEY` (unset → dev-mode allow with a warning; HMAC left as a TODO).
- `server/tests/test_server.py` + `__init__.py` — 8 no-mocks e2e tests covering the 5
  required assertions: runtime timeout/error/resource fixtures fire their detector,
  healthy fires none, complexity workflow yields schema+complexity structural detections,
  detections persist and list back with DB id + execution_id FK, auth 401/200 with key set,
  healthz 200.

Engine untouched (used, not edited). No BLOCKED notes — nothing in the engine needed a
change. No golden datasets copied; fixtures read by absolute path from the monorepo worktree.
