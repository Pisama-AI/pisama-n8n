# First-class input-schema guardrail repair

Goal: close the gap between "we can recommend a guardrail" and "Pisama safely installs and
verifies one." Promote `engine/pisama_n8n_engine/guardrails.py::input_schema_guardrail`
(today: a template + docs recommendation) into a reviewable, operator-gated, verified n8n
repair with prevention evidence.

## Verification command (the whole game)

```bash
~/pisama-n8n-cloud/.venv/bin/python -m pytest server/tests -q \
  && (cd engine && ~/pisama-n8n-cloud/.venv/bin/python -m pytest tests -q) \
  && ~/pisama-n8n-cloud/.venv/bin/python benchmarks/parity_check.py
```

Pass = all green + parity 7/7. Plus the E2E gate (needs a local n8n via docker):
`~/pisama-n8n-cloud/.venv/bin/python scripts/run_guardrail_lifecycle.py` exits 0 with every
lifecycle stage asserted. Fail = keep working; do not ask the user; fix and re-run.

## Design (decided BEFORE the loop)

1. **Deterministic repair, no LLM.** The guard subgraph is generated from observed
   evidence only — this repair never calls a model. That is its selling point.
2. **Observed-path extraction** (`engine/pisama_n8n_engine/guardrails.py`):
   `observed_required_paths(execution, failing_node_name, leaf)` — from the
   n8n_data_contract finding's error message take the leaf (`reading 'value'`), find
   property chains ending in that leaf in the failing node's jsCode/expressions, then
   CONFIRM against the recorded input item of the failing turn (prefix exists, leaf
   missing/null). Returns `{confirmed: [...], candidates: [...]}`. No confirmable path →
   candidates only → the UI requires the operator to pick/enter one. Never invent paths.
3. **Destination is a server-enforced operator choice.** Proposal rows carry
   `guard_config` JSON `{paths, destination: null}`; `claim_repair_apply` REFUSES a
   guardrail proposal whose destination is null (403-style 409), so the choice cannot be
   bypassed by a client. Destinations v1:
   - `error_workflow`: rejected -> `n8n-nodes-base.stopAndError` (message lists missing
     paths). Compatibility note surfaced when the workflow has no
     `settings.errorWorkflow` configured (still allowed — it marks the run failed).
   - `alert`: rejected -> `n8n-nodes-base.httpRequest` POST of the rejection record
     (missing paths only, never payload values) to an operator-supplied URL. URL is
     validated http(s) and stored in guard_config.
   - `respond_422`: rejected -> `n8n-nodes-base.respondToWebhook` (422 + validation
     body). Offered ONLY when the workflow's trigger is a webhook already in
     `responseMode: responseNode` (flipping responseMode would change valid-path
     behavior; out of scope v1 — option disabled with the honest reason).
4. **Insertion point**: on the edge INTO the failing node (single edge rewire:
   `source -> guard entry`, `validated -> failing node`). Multi-input consumers: v1
   refuses (409 with reason) rather than guessing.
5. **Apply safety**: new `assert_safe_guardrail_diff(baseline, mutated, fragment)` in the
   server — additions must be EXACTLY the fragment nodes (name+type match), connection
   changes limited to the single insertion + rejected->destination edge, nothing else
   (no node removals, no type/credential changes elsewhere). Defense in depth even though
   the proposal is server-generated. The existing snapshot/rollback path is reused
   unchanged (whole-workflow snapshot; `apply_unverified` state on post-PUT failure).
6. **Reliability case = prevention evidence.** New nullable fields on reliability_cases:
   `guard_malformed_rejected_execution_id/at`, `guard_valid_passed_execution_id/at`.
   `POST /api/v1/reliability-cases/{id}/guard-verification` records each probe outcome
   with its REAL execution id (server verifies the execution exists and its routing:
   rejected probe must show the rejected branch ran and the consumer did NOT; valid
   probe the inverse). `outcome=prevented` remains operator-concluded but the API
   refuses `prevented` on a guardrail case unless both probes are recorded.
7. **UI** (dashboard, SaaS + OSS): on `n8n_data_contract` detection detail, a
   "Strict input-schema guard" panel: extracted paths (confirmed vs candidates),
   destination selector (with server-provided compatibility/disabled reasons), subgraph
   preview (node list + wiring), Apply via existing flow, verification outcomes in
   RepairVerificationPanel.
8. **Dogfood lifecycle** (`scripts/run_guardrail_lifecycle.py`): against a local n8n:
   create dogfood webhook workflow (consumer reads `body.required.value`) -> POST
   malformed -> baseline n8n_data_contract detection -> propose guard -> assert apply
   REFUSED without destination -> set destination (stop_and_error) -> apply -> POST
   malformed (assert rejected branch, consumer skipped, guard-verification recorded) ->
   POST valid (assert business path ran + output unchanged shape) -> observe -> rollback
   -> assert workflow restored byte-identical to snapshot. Every stage asserts or the
   script exits non-zero. Wire as a lane in the existing fail-closed dogfood gate.

## Do NOT touch

- `fix_patch_guard.py` whitelist semantics for the MODEL-generated fix path (the cloud
  repo). The guardrail is a separate deterministic path with its own stricter validator.
- Vendored/locally-owned detector logic (schema_detector's detection behavior).
- Golden parity fixtures, committed eval baselines.
- The repair state machine's existing transitions (extend with guard-specific guards only).

## Tasks

- [x] Audit: read current repair endpoints/storage/reliability fields; record exact shapes in Notes.
- [x] Engine: `observed_required_paths` + destination builders + `insert_guard_into_workflow` + tests (19 guardrail tests; generated JS executed under real node: Object.hasOwn semantics, zero-preserved, all-missing flagged).
- [x] Server: guardrail proposal endpoint + destination endpoint + apply integration + `assert_safe_guardrail_diff` + reliability-case guard-verification endpoint + tests (all no-mocks, per repo convention).
- [x] Dashboard: guard panel + destination selector + verification display; tsc + build green.
- [x] Harness: `scripts/run_guardrail_lifecycle.py` run GREEN against a real local n8n (docker n8nio/n8n:1.70.0), all 8 stages passed, exit 0.
- [x] Verify: server 50 passed/9 skipped + engine 97 + parity 7/7 + dashboard tsc/build clean + lifecycle exit 0.

## Notes

**Audit (from review inventory):** repair endpoints POST /api/v1/n8n/fix (app.py:368,
proposal at :415), /n8n/apply :430, /n8n/rollback :526; reliability-cases GET :309/:317 +
POST .../outcome :329. RepairAttempt fields storage.py:149-207; lifecycle fns :708,
:1015-1108. ReliabilityCase :233-277. Dashboard FixPanel.tsx / RepairVerificationPanel.tsx;
API routes lib/api/fixes.ts:44-46. Schema detector emits n8n_data_contract at
schema_detector.py:141-195 with evidence.issues=[{node,turn,message}] (note: dead code
:197-280 after return, pre-existing).

**Engine layer DONE (this commit):** guardrails.py gained property_read_leaf /
observed_required_paths (evidence-grounded; confirmed vs candidates; never invents),
rejection_destination (error_workflow=stopAndError, alert=httpRequest to operator URL
carrying ONLY the rejection record, respond_422=respondToWebhook gated on
responseMode=responseNode), validate_destination_compatibility, and
insert_guard_into_workflow (single-main-edge splice upstream of the failing consumer —
consumer-observed paths verbatim, no boundary translation; collision-free prefixing;
refuses multi-input/unknown nodes). Fragment hardened: Object.hasOwn (fixes __proto__
bypass — review P3), per-condition IF id (live-import shape). PII redacted from
CLOUD-112117 fixture (founder IPv6, live webhook URL, resumeToken — review P2; history
scrub pending founder approval). Verified: engine 97, server 45+9s, parity 7/7, ruff
clean; generated JS exercised under real node.

## Final status

Output DONE only when every box is checked and the verification command passes.


**Server layer DONE:** storage — guard_config on repair_attempts + 4 guard-verification
fields on reliability_cases (+ _ADDED_COLUMNS catch-up), create_guardrail_proposal /
set_guardrail_destination / record_guard_verification (real routing check vs runData) /
conclude gate (prevented refused on a guardrail without both probes). app — POST
/n8n/guardrail (derives paths from evidence + confirms vs recorded input; free repair, no
paid gate), POST /n8n/repairs/{id}/destination (server-enforced choice; builds guarded
workflow), apply refuses null-destination guardrail + runs assert_safe_guardrail_diff,
POST /reliability-cases/{id}/guard-verification. engine — assert_safe_guardrail_diff +
observed_consumer_input. Verifier GREEN: server 50 passed/9 skipped (5 new guardrail
tests), engine 97, parity 7/7, ruff clean. Fixed a stale paid-gate test (apply gate now
keys on guard_config, not the endpoint).

## Final Status

DONE. All four tasks checked; the verification command is green and the E2E lifecycle
proves the whole loop on a real n8n.

- **Cheap verifier (every change):** server 50 passed / 9 skipped (guardrail suite is 5
  no-mock tests), engine 97 passed, parity 7/7, dashboard `tsc --noEmit` + `npm run build`
  clean, ruff clean.
- **E2E gate (real n8n via docker):** `scripts/run_guardrail_lifecycle.py` -> exit 0, all
  8 stages: create+activate, baseline data-contract failure detected, propose (path
  `body.required.value` confirmed from evidence), apply refused without a destination
  (409), choose destination + apply (guard live in n8n), malformed input rejected
  (destination ran, consumer skipped -> malformed_rejected probe recorded), valid input
  passed (consumer ran, destination skipped -> valid_passed probe recorded), rollback
  restored the workflow to the pre-guard baseline.
- **The gap is closed:** a data-contract finding now yields a reviewable, operator-gated,
  deterministically-generated guardrail that Pisama installs into the live workflow and
  verifies with two real executions, recorded on the reliability case as prevention
  evidence (the case cannot be concluded `prevented` until both probes exist).

Deferred (flagged, out of the loop's scope): the dogfood-gate *lane* wiring
(`run_dogfood_pipeline.sh`) and porting the guardrail endpoints to the SaaS server
(`saas_server`) so the SaaS dashboard is not self-host-only. The lifecycle script is the
gate; wiring it into the weekly CI job is a one-line addition once the founder decides the
cadence.