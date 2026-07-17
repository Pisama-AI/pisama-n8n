# n8n dogfooding

Pisama dogfooding uses real n8n instances and their actual execution records. Do not
substitute mock HTTP servers, fabricated traces, or customer data. The Docker targets
in this repository own disposable internal data only.

## Supported lanes

| Lane | Target | What it proves |
| --- | --- | --- |
| Docker SQLite | `deploy/docker-compose.dogfood.yml` | Default self-host n8n install, webhook execution, and API polling. |
| Docker Postgres | Base compose plus `docker-compose.dogfood.postgres.yml` | n8n backed by Postgres, including restart and data persistence. |
| Version sweep | Set `N8N_VERSION` before startup | Compatibility evidence for explicitly supported releases, currently `1.70.0` and `1.91.3`. |
| n8n Cloud | A dedicated non-production Cloud project | API polling and webhook ingestion over the hosted API. Set `PISAMA_N8N_PROJECT_ID` so polling never reads another project. |

Start a disposable SQLite n8n target:

```bash
docker compose -p pisama-n8n-dogfood -f deploy/docker-compose.dogfood.yml up -d n8n
```

Create an owner and an API key in that instance, then start the Pisama server lane:

```bash
export PISAMA_DOGFOOD_N8N_API_KEY='your-disposable-n8n-key'
export PISAMA_DOGFOOD_API_KEY='local-pisama-key'
export PISAMA_BUILD_REVISION="$(git rev-parse --short HEAD)"
docker compose -p pisama-n8n-dogfood -f deploy/docker-compose.dogfood.yml \
  --profile server up -d --build
```

For Postgres, add `-f deploy/docker-compose.dogfood.postgres.yml`. Use a distinct
Compose project name for every lane so volumes, ports, and upgrade evidence cannot
cross-contaminate.

Keep a separate Pisama server sidecar for each retained lane. Never point a shared
server database at two n8n targets. The sidecar gets its own `dogfood_pisama_data`
volume, a unique bearer key, and a unique n8n API key. Bind the local server port to
`127.0.0.1` and start it with `--no-deps` so the n8n target is neither recreated nor
restarted. n8n `1.91.3` keys must use only Workflow and execution read scopes. n8n
`1.70.0` has no scoped-key endpoint, so its short-lived legacy key is safe only inside
the dedicated disposable lane. The Compose services use `restart: unless-stopped` so
the retained lanes resume after a Docker restart.

The intended sustained matrix is a current SQLite lane, a current Postgres lane, a
`1.70.0` SQLite lane, and the dedicated Cloud lane. The upgrade/restore harness is an
ephemeral scheduled gate rather than a permanent polling target: it proves a real
persisted-database transition without mixing pre-upgrade evidence into a long-lived
corpus.

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
   retry/recovery, invalid credentials, broken expression, error-workflow routing, and
   bounded/unbounded loop.
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
The reproducible real-data gate does this end to end for n8n `1.70.0` to `1.91.3`:

```bash
python scripts/verify_n8n_upgrade_restore.py
```

It creates uniquely named temporary Compose projects, provisions a controlled failing
webhook, copies the complete SQLite volume, upgrades the original lane, restores the
backup into a second target lane, provisions fresh API keys after each image transition,
and verifies Pisama polling plus second-sync deduplication. It emits only a redacted
manifest and removes its temporary containers and volumes unless `--keep` is requested.

## External-readiness rule

Dogfood results are internal evidence, not a recall claim. Do not claim detector recall
or autonomous repair success until design partners supply independently adjudicated
incidents and repeated observed repair outcomes.

## Corpus audit

The current database, rather than this document, is the source of truth for whether a
failure class has retained real evidence. Run the aggregate-only audit before a detector
rollout or release decision:

```bash
export PISAMA_DOGFOOD_API_KEY='your-local-read-key'
python scripts/audit_dogfood_corpus.py
```

It reads only `/healthz`, the operations summary, and detection metadata. It never
fetches workflow JSON, traces, node output, or credentials. The report lists every
fired `detector:failure_mode`, the first and latest retained observation, and the
source-controlled coverage catalog. An uncatalogued fingerprint is a signal to inspect
the running image or detector contract, not evidence to silently relabel.

Build each server image with `PISAMA_BUILD_REVISION` set as above. New execution and
detection rows retain that build revision and the detector semantic version. Historical
unversioned rows remain visible as `unknown`; they cannot be attributed to the current
source tree.

Use an explicit gate only when its required captures are expected to be present:

```bash
python scripts/audit_dogfood_corpus.py --require-profile core
```

`core` requires enabled P0/P1 catalog entries; `full` also requires enabled P2/P3.
Withheld modes remain visible in the catalog but never satisfy a release gate. Either gate exits
nonzero and lists its missing fingerprints. A fresh or recreated dogfood volume can
legitimately fail even if a historical exercise passed, so do not substitute prose or a
past CI result for this check.

For a release build, make provenance part of the gate rather than allowing an earlier
image's retained rows to satisfy it:

```bash
python scripts/audit_dogfood_corpus.py --require-profile core --require-current-build
```

This reads the running server's `/healthz` revision and requires every selected
fingerprint to have at least one observation from that revision. A server reporting
`unknown` cannot pass this form of the gate.

### Withheld detector modes

The entire `retry_recovery` detector is withheld from rollout and release gates (both
`n8n_retry_exhausted` and `n8n_retry_not_observed`). Controlled HTTP retries in both n8n
`1.70.0` and `1.91.3` made two actual requests, while each caller execution exported
exactly one node run and no authoritative retry-attempt link. Because the exported
`attempt_count` is therefore always `1`, the detector cannot distinguish "retry
configured but did not run" from "retry ran and n8n collapsed the run record": its
ambiguity gate never trips, so `n8n_retry_not_observed` fired at MODERATE/0.95 on
essentially every retry-enabled failure and told the user to "verify retry support"
regardless of the real outcome. Both fingerprints are held until a real n8n telemetry
source can prove a retry outcome without confusing it with an ordinary single node run.
The detector still exists and is documented, but `N8NRetryRecoveryDetector.release_gate`
is `False`, so it never emits `detected=True` by default. A separate real `Loop Over
Items` capture retained two normal runs of one retry-enabled node, one successful and one
failed; it must also produce no retry claim, because those are loop iterations, not
evidence about a retry budget.

`n8n_duplicate_side_effect_risk` is also withheld from rollout and release gates.
Two real, intentional `Loop Over Items` POST iterations reached a controlled receiver
twice without an `Idempotency-Key`, which the earlier heuristic could not distinguish
from one business event retried twice. Pisama therefore does not emit a generic
duplicate-side-effect finding until it can correlate durable event identity, delivered
request headers, and receiver outcomes for the same action.

`n8n_agent_tool_recovery` and `n8n_agent_output_validation` are enabled for the narrow
Claude Messages protocol exercised by the local n8n lane. Their contract is deliberately
smaller than generic n8n AI-agent coverage: n8n must retain `executionIndex`, direct
source links, an initial Claude `tool_use` ID, a matching failed `tool_result`, and a
later source-linked Claude response. Tool-recovery findings fire only when the failed
result has no such later response. Output-validation findings require the direct Claude
response to feed a Code node whose recorded `JSON.parse` error matches n8n's actual
invalid-JSON shape. Missing order, missing IDs, mismatched IDs, ordinary loops, and
successful tool calls are inconclusive.

`n8n_native_agent_tool_recovery` is enabled separately for the native
`@n8n/n8n-nodes-langchain.agent` protocol captured on n8n `1.91.3`. It is not a generic
native-Agent detector. It requires exactly one Agent run, one `intermediateSteps`
action with a tool-call ID, one direct `ai_tool` workflow edge, one direct
`ai_languageModel` edge, one failed tool run, one model run before that failure, and
the exact tool error in the Agent's recorded observation. It fires only when no later
run of that same direct model node exists. A recovered tool error is also excluded from
the broad error detector only under this exact contract. Multiple agents, tools,
models, repeated runs, missing indexes, shared nodes, and native output parsers are
inconclusive. Run the live corpus refresh with:

```bash
export ANTHROPIC_API_KEY='your-dogfood-only-key'
export PISAMA_N8N_API_KEY='your-disposable-n8n-key'
export PISAMA_API_KEY='your-local-pisama-key'
python scripts/capture_native_agent_evidence.py
```

The harness creates a real successful tool call, a real recovered tool error, and a
real unhandled tool error using native n8n nodes. It validates their retained n8n
execution shapes and the detector's positive and negative controls, then deletes its
temporary workflow and credential. The raw executions remain in n8n and Pisama's
internal corpus.

The catalog separately labels `cycle:F11` as static workflow-configuration evidence.
The current n8n orchestrator does not yet feed runtime turns to its cycle detector, so
it must never be presented as proof of observed runtime-loop coverage.

## Error-workflow route evidence

For a real failed execution with an `errorWorkflow` setting, the polling server resolves
the configured target through n8n's API before classifying it. It reports a distinct
finding only when n8n can prove the route is wrong:

- no configured ID: `n8n_missing_error_workflow`;
- a target that returns n8n's authoritative `404`:
  `n8n_error_workflow_target_missing`;
- an existing target with no `n8n-nodes-base.errorTrigger` node:
  `n8n_error_workflow_missing_trigger`.

An unavailable target, permission failure, polling delay, or absent handler execution is
inconclusive. Pisama does not turn those absences into a broken-route finding. It also
does not require the target to be active, because n8n accepts an Error Trigger workflow
as the error route without that condition.

Each fired route finding retains a small, authenticated local audit record: source n8n
execution ID and mode, target ID, resolver outcome, failed node names, and trigger count
when relevant. This supports review without returning the full raw n8n execution to the
detection API.

## Reliability evidence definitions

The local `/api/v1/reliability/metrics` scorecard is a measurement aid, not marketing
copy. Its fields have fixed meanings:

- **Diagnosis acceptance** is the latest operator verdict per detection. `useful` and
  `fixed_manually` are accepted; `not_useful` is rejected. Unreviewed detections are
  excluded from the denominator.
- **Verified remediation** is `prevented / (prevented + recurred)`. An `inconclusive`
  outcome is not silently treated as success or failure.
- **Time to applied workflow control** runs from Pisama receiving the source execution
  to a stale-guarded workflow change being applied. It does not claim that the change
  solved the issue.
- **Recurrence reduction** compares equal-sized baseline and post-change runtime windows
  for the same workflow and failure fingerprint. It remains unavailable until a case has
  at least ten real baseline executions and an equal post-change window (configurable for
  internal harness testing). It is reported as a pooled rate change across complete cases.

An outcome is retained when a repair is later rolled back. The repair's current lifecycle
state may be `rolled_back`, while its previous `prevented`, `recurred`, or `inconclusive`
outcome remains part of the local audit record.

## Current internal evidence

2026-07-16:

The following records historical internal exercises. They do not assert that each
capture remains in the currently running database. Use the corpus audit above for a
current release decision.

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
- The first Cloud apply exercise exhausted its execution quota before a post-repair run
  could be observed. A separate Fly deployment now polls the dedicated Cloud project
  with its own encrypted volume, webhook secret, n8n key, and revocable dogfood-only
  `PISAMA_CLOUD_KEY`. It detected a real controlled Code-node failure, proposed a
  reviewable one-node patch, applied it after review, ingested the next successful Cloud
  execution, and rolled the workflow back exactly to the original failure. One success
  is retained as observation evidence only; it does not claim prevention.
- A fresh SQLite n8n `1.70.0` volume with an active controlled-failure workflow was
  backed up, started successfully on `1.91.3`, then restored from that pre-upgrade backup
  into a fresh `1.91.3` start. The workflow remained active and its webhook returned the
  expected controlled `500` after both the upgrade and restore.
- The disposable local `1.91.3` lane captured new real HTTP executions for a provider
  `429` and a `401` authentication rejection. The standalone detector classified them as
  `n8n_rate_limit` and `n8n_credential`, respectively. A real Code-node missing-field
  execution also fired the runtime-only `n8n_data_contract` detector.
- A current-source isolated server, built with retained provenance, re-ingested the
  six local disposable executions and then observed live reruns plus poll deduplication.
  It retained the concrete rate-limit, credential, provider, expression/data-contract,
  retry-configuration-gap, and missing-error-workflow fingerprints under its build and
  detector versions.
- A real delayed HTTP request with an explicit 500 ms n8n timeout recorded n8n's
  `connection was aborted` error after 537 ms. Pisama now classifies that corroborated
  shape as `error:n8n_timeout` and `timeout:F13`; the detector contract is protected by
  a live n8n regression test.
- A separate bounded `Webhook → Code → Code` execution expanded one real item into ten
  1,500-character items. The current server retained `resource:F6`, and its live n8n
  regression test proves the runtime payload-growth path without a constructed trace.
- In n8n `1.91.3`, a retry-enabled POST to a disposable internal failure sink executed
  the sink twice, while the caller's exported `runData` retained only one node record.
  Pisama therefore reports `n8n_retry_not_observed` and deliberately withholds both
  `n8n_retry_exhausted` and duplicate-side-effect claims. This behavior is protected by
  a live n8n regression test.
- Current source revision `5ba622e` captured two controlled error-route failures in the
  isolated SQLite lane. n8n accepted a source configured to a missing target ID, and
  Pisama retained `n8n_error_workflow_target_missing` after its API returned `404`.
  A separate source targeted an existing ordinary workflow without an Error Trigger;
  n8n returned the source `500`, created no target execution, and Pisama retained
  `n8n_error_workflow_missing_trigger`. The first poll ingested both real executions;
  the second added zero. Both detections retain their resolver facts and are visible in
  the authenticated detection detail without exposing raw execution payloads.
- The same current-source lane then reran the retained provider, credential, rate-limit,
  expression/data-contract, retry, timeout, and payload workflows. It ingested nine new
  real executions, and the second poll added zero. Before retry exhaustion was withheld,
  the current-build core gate failed only for that mode and
  `truncation:n8n_truncation`; neither absence was relabeled as a passing result.
- An isolated n8n `1.70.0` lane reproduced the retry-export limitation: a retry-enabled
  POST made two real sink executions, while the caller exported one node run and no
  retry linkage. This matches `1.91.3` and is why `n8n_retry_exhausted` is withheld.
- Current source revision `768b4ef` rebuilt the retained isolated server, then reran the
  credential, expression/data-contract, rate-limit, provider, retry, timeout, payload,
  and both error-route workflows. The first sync ingested eleven real executions and the
  second added zero. Its current-build `core` gate now misses only P0
  `truncation:n8n_truncation`; retry exhaustion is visible as withheld, and an explicit
  gate for it correctly exits nonzero rather than silently passing.
- Current source revision `468ccdb` rebuilt the lane after withdrawing the unproven
  duplicate-side-effect and AI-agent modes. It reran the retained controls plus a
  two-iteration intentional POST loop to a controlled receiver. The first sync ingested
  fourteen real executions and the second added zero. The current-build `core` gate
  still misses only P0 truncation, while the four withheld fingerprints have zero
  current-build detector rows and an explicit gate for them exits nonzero.
- The automated `verify_n8n_upgrade_restore.py` gate passed against real n8n images
  `1.70.0` and `1.91.3`. Both the in-place upgraded lane and the restored lane retained
  the controlled workflow, produced a real error and `error_workflow` finding, and
  returned `initial_sync_new: 2` followed by `second_sync_new: 0`. The run left no
  temporary containers or volumes.
- Repair verification now has a tenant-local case record. In the disposable SQLite lane,
  two real workflow controls sourced from one controlled failure were safely applied
  through the stale-workflow guard. A later successful execution was ingested by API
  polling and updated both `observing` cases. Pisama correctly refused to label a single
  success as prevention, then restored the controls in reverse order and retained their
  rolled-back audit records.
- At the earlier `468ccdb` exercise, no real LLM token-limit or AI-agent
  tool/output-validation execution had been captured in this lane. Truncation still
  cannot pass its P0 gate without a real capture; any unproven AI-agent mode remains
  withheld rather than presented as validated coverage.
- Native n8n AI Agent telemetry has now been captured separately from native Agent,
  Anthropic Chat Model, and Code Tool nodes. The three real executions retained a
  healthy tool call, a failed tool followed by a later model recovery, and a failed tool
  without a later model call. The new narrow native detector is positive only on the
  last shape. The generic error detector stays silent on the recovered control under the
  same exact contract. Native output-parser, multi-tool, and multi-Agent protocols
  remain unsupported rather than generalized from these three captures.
