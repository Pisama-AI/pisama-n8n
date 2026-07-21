# Runtime-lane detector eval

Measures per-detector **precision / recall / F1** for the execution-lane detectors —
`timeout`, `error`, `resource` — the ones that read real n8n execution `runData`. (The
structural detectors `cycle` / `complexity` / `schema` are evaluated separately against
mined workflow JSON; this harness is specifically for the runtime lane, which can't be
measured from static workflows.)

```bash
# controlled corpus (default): both classes + adversarial near-misses, a regression baseline
python eval/runtime_eval.py --json baseline.json

# REAL executions generated against a local n8n (by-design labels, real engine + runData)
N8N_EVAL_KEY=... N8N_EVAL_EMAIL=owner@x N8N_EVAL_PASSWORD=... \
  python eval/generate_real_corpus.py          # writes eval/baseline_real.json
#   REUSE=1 re-scores the last run without re-executing the 65s timeout workflow

# real executions from an ALREADY-connected n8n (ground truth = n8n's own status/errors)
N8N_HOST=https://you.app.n8n.cloud N8N_API_KEY=... python eval/runtime_eval.py --source mine

# REAL-WORLD: run real community workflows (third-party logic) on a local n8n and score
# recall against independent ground truth computed from n8n's own record
python eval/mine_real_world.py --scan            # corpus stats only
python eval/mine_real_world.py --limit 76 --report eval/baseline_realworld.json
python eval/mine_real_world.py --rescore         # re-score saved executions (no n8n)
```

## Real-world recall validation (mined third-party failures)

`mine_real_world.py` closes the gap the paragraphs above disclose: it runs REAL community
workflows (the same 10,826-doc GitHub corpus the precision validation used; 76 are
runnable after the safe-node/no-credentials filter) on a real n8n engine, captures the
executions, and scores the runtime detectors against **independent ground truth computed
from n8n's own record** (status / node error objects / executionTime / payload sizes —
no engine imports). The failures are authored by other people: their throws, their
loops, their data explosions. A parallel sweep mined 31 **wild executions** (execution
JSONs strangers committed to GitHub, 8 recording genuine production failures).

Corpus: `eval/data/realworld/` (70 committed executions mined from public GitHub
workflow repos). These embed third-party workflow definitions and demo data as they
appeared upstream; a demo RSA private key that rode along in one tutorial fixture
(`rw_6c1c2e6a80.json`) has been redacted, and detection never reads key bytes. Do not
treat these fixtures as scrubbed of all upstream data. Baselines:
`baseline_realworld.json` (main corpus) + `baseline_realworld_holdout.json`.

### What the mining found (and fixed)

The first pass scored error P0.88/R0.88 and resource P0.08/R0.33. A 16-case adversarial
triage classified every disagreement (12 detector bugs / 2 gt artifacts / 2 both):

1. **Resource over-fire (9 FPs, one root cause)**: the growth checks were pure RATIO
   tests — 45 -> 115 chars counted as a "2.6x explosion". Fixed with an absolute floor
   (`min_explosion_chars`, = `max_content_size` so the detector has one scale line).
2. **Resource recall bug**: item counts were re-derived from the rendered content string,
   which leads with a "Node: ..." header — the JSON parse never engaged, so every count
   collapsed to 1 and real 1 -> 10 amplification was invisible. The parser now emits a
   structured `items_out` per turn.
3. **Loud failures could yield ZERO detections**: a terminal single-node failure tripped
   none of the hidden-error checks (no continueOnFail, no downstream turns, rate under
   15%, and success-despite-failures suppresses itself once the workflow is marked
   failed) — invisible to dashboards and healing. New `execution_failure` branch; the
   controlled corpus's `error_low_rate_visible` adversarial case is now a positive of
   that type (semantic decision documented at the case).
4. **Legacy `continueOnFail: true` swallowed failures were invisible**: the parser set
   the flag but passed no onError MODE to the swallowed-error check. Found on a real
   community workflow whose Code node crashed, was continued, and n8n marked the run
   successful — the exact hidden-failure class the product exists to catch.
5. **Structured error objects**: wild production executions record swallowed failures as
   an error OBJECT (`{message, name, ...}`) on the item json, not a string. The detector
   caught three such hidden failures in a stranger's production workflow that both the
   gt and the parser initially missed. Both now accept dict-with-message.

### The numbers (after fixes)

| corpus | n | error P/R | resource P/R | timeout P/R |
|---|---|---|---|---|
| real-world community (in-sample*) | 69 | 1.00 / 1.00 | 1.00 / 1.00 | n/a (0 positives) |
| wild (strangers' production) | 17 | 1.00 / 1.00 | 1.00 / 1.00** | n/a (0 positives) |
| holdout (fresh, larger workflows) | 1 | 1.00 / 1.00 | n/a | n/a |
| controlled (regression guard) | 19 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |

\* **In-sample disclosure**: the 69-execution corpus drove the fixes, so its post-fix
numbers are in-sample. Out-of-sample evidence: the wild set (only 2 of its 17 cases
informed a fix), the n=1 holdout, the unchanged controlled corpus (incl. adversarial
negatives), and 41 unit tests locking each fix as a contract.

\** Wild "resource positives" are the >10k-char oversized semantic firing on production
payloads; whether each was an operational INCIDENT is unknowable from the record. It
measures agreement with the documented size semantic, not incident truth.

### Honest limits

- **Timeout recall is still unvalidated on real-world data** — zero >60s nodes appeared
  in 87 real executions (rare event). It remains validated only on the real-engine
  authored corpus (`generate_real_corpus.py`, a genuine 65s node).
- **The failure distribution is not production**: community workflows run once with an
  empty standardized input over-represent input-shape errors. This validates pipeline
  recall on organically diverse real executions, not the production failure mix.
- **Selection bias, disclosed**: only credential-free workflows whose executing nodes
  can't reach the network run (76 + 2 of 10,826 docs) — data-shaping workflows, which is
  also where the runtime lane's failure modes live. 8 workflows n8n itself refuses to
  execute (required params left empty in the shared template) are skipped; they are
  unrunnable for anyone.
- **Wild-format gap (product finding)**: wild n8n execution data comes in three formats —
  plain API export, flatted DB arrays, and partially-dereferenced dumps. The adapter
  handles only the first; 6 of the 8 genuine wild failures are locked in the flatted
  format. Raw wild files stay OUT of the repo (third-party PII/keys); only derived
  labels are used.
- Cycle (structural lane) recall was already validated separately: 85/85 real unbounded
  cycles via independent graph ground truth (2,348-workflow corpus, 2026-07-14).
  Complexity has no independent "failure" fact to recall against (it is a smell), and
  schema's static path is disabled by design.

## The real-world number (finally available)

`generate_real_corpus.py` spins up genuine n8n executions on a local instance — one workflow
per failure mode plus healthy and **adversarial** negatives — captures the real `runData` via
the public API, labels each **by design** (we control each workflow's failure mode), and scores
all three runtime detectors on **both classes**. This is the real-world number the controlled
corpus stood in for. Latest run (10 real executions, 5 failure / 5 healthy):

| detector | precision | recall | F1 |
|---|---|---|---|
| timeout  | 1.00 | 1.00 | 1.00 |
| error    | 1.00 | 1.00 | 1.00 |
| resource | 1.00 | 1.00 | 1.00 |

Zero false positives, including on the two adversarial negatives (a continue-on-fail node that
did **not** fail; a healthy node whose output legitimately carries a field named `error`). This
is real-engine correctness on a controlled distribution — **not** a production false-positive
rate, which still needs live tenant traffic with both healthy and failing runs.

## What the number means — and what it doesn't

**Controlled corpus.** Realistic n8n executions *constructed* with known labels: genuine
node errors, hidden continue-on-fail failures, 60s+ slow nodes and slow webhooks, payload
explosions — plus healthy runs and **adversarial near-misses** (slow-but-under-threshold,
large-but-stable payloads, an error only *mentioned* in output content, a background AI
node that's expected to be slow). It gives a real precision/recall for the detector
**logic**, with both classes, and a regression baseline.

It is **not** a real-world distribution. A perfect score here means "the logic classifies
the clean and boundary cases correctly," **not** "the detectors are accurate on messy
production traffic." The real-world false-positive rate needs live `runData`.

**Real-mining (`--source mine`).** Fetches real executions and labels them by n8n's own
ground truth (execution status + node-level error objects). It **refuses to report a
number for any class with zero samples** (the degenerate-corpus guard) rather than
fabricating one. As of this writing every reachable test instance is all-failures with no
healthy runs, so the real-world number is still pending a genuine n8n with both healthy
and failing production traffic.

## Honesty notes

- The controlled labels are threshold-derived *expectations*. A disagreement is a real
  finding: over-fire = precision loss, under-fire = recall loss. Building the corpora
  surfaced (and fixed) **three** genuine parser bugs in `trace/execution.py`, all against
  real n8n `runData` shapes the synthetic corpus had wrong:
  1. **workflow status dropped** — the parser lost the workflow-level status, so the error
     detector flagged *every* visibly-failed workflow as a hidden "success-despite-failure"
     (precision loss). Fixed; now also falls back to `finished` when the API omits `status`
     (real polled/manual executions return `status: null`).
  2. **`onError` read from the wrong place** — real n8n stores `onError` at the **node**
     level, but the parser read it from `parameters`, so `continue_on_fail` was *always
     false on real data* and every hidden failure went undetected (recall loss). Fixed to
     read node-level `onError` plus legacy `settings.continueOnFail`.
  3. **swallowed failures leave no `run.error`** — a continue-on-fail node that actually
     fails keeps `executionStatus: "success"` and records **no** `error`; the failure is
     only visible as items on the error-output branch (`main[1]`, `continueErrorOutput`) or
     an `error` key inside the regular output item (`continueRegularOutput`). The parser now
     surfaces both, **gated on the node's own `onError` config** so a healthy node whose
     data merely contains a field named `error` is never flagged (verified by an adversarial
     negative). Without this, the product would miss *every* real silent failure — the single
     highest-value n8n detection.
- It also corrected three of the author's own labels — the timeout detector was *more*
  correct than first assumed (a 45s httpRequest node, and a 90s webhook, are genuine
  timeouts even when the workflow total is under 5 minutes).
- `mine` measures the **error** lane only against real data — n8n's status gives a clean
  label for node errors, but there is no clean n8n label for "this timeout/resource
  pattern was a real problem," so those are not fabricated on real data.

## Corpus guard campaign (2026-07)

Real guard lifecycles across the 70 committed community workflows on a throwaway
local n8n, through the product's own endpoints: 67 imported, 19 real failures
detected, **17 guards applied and verified by real routed-incident probes** — and
0 reaching the full 30-success prevention bar, for a reason the report explains
rather than papers over. Funnel, disclosures, and provenance:
[campaigns/2026-07-guard-campaign.md](campaigns/2026-07-guard-campaign.md);
machine summary: [baseline_guard_campaign.json](baseline_guard_campaign.json);
harness: `scripts/corpus_campaign_prepare.py` + `scripts/run_corpus_guard_campaign.py`
+ `scripts/run_corpus_campaign_local.sh` (deterministic manifest, `--check` in CI
spirit; no outcome is ever concluded by a script).
