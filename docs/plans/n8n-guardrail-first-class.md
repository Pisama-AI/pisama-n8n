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

- [ ] Audit: read current repair endpoints/storage/reliability fields; record exact shapes in Notes.
- [ ] Engine: `observed_required_paths` + destination terminal builders + fragment wiring helper (`attach_destination`) + tests (incl. injection: path segments with quotes/backslashes must be safely JSON-encoded into jsCode).
- [ ] Server: guardrail proposal endpoint + destination endpoint + apply integration + `assert_safe_guardrail_diff` + reliability-case guard-verification endpoint + tests (all no-mocks, per repo convention).
- [ ] Dashboard: guard panel + destination selector + verification display; tsc + build green.
- [ ] Harness: `scripts/run_guardrail_lifecycle.py` + dogfood-gate lane; run it against a real local n8n and paste the stage results into Notes.
- [ ] Verify: full verification command green; record numbers in Notes.

## Notes

(accumulating state — fill during the loop)

## Final status

Output DONE only when every box is checked and the verification command passes.
