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
```

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
