# Runtime-lane detector eval

Measures per-detector **precision / recall / F1** for the execution-lane detectors —
`timeout`, `error`, `resource` — the ones that read real n8n execution `runData`. (The
structural detectors `cycle` / `complexity` / `schema` are evaluated separately against
mined workflow JSON; this harness is specifically for the runtime lane, which can't be
measured from static workflows.)

```bash
# controlled corpus (default): real number today, both classes + adversarial near-misses
python eval/runtime_eval.py --json baseline.json

# real executions from a connected n8n (ground truth = n8n's own status/errors)
N8N_HOST=https://you.app.n8n.cloud N8N_API_KEY=... python eval/runtime_eval.py --source mine
```

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
  finding: over-fire = precision loss, under-fire = recall loss. Building this corpus
  surfaced (and fixed) one genuine precision bug — the parser dropped the workflow-level
  status, so the error detector flagged *every* visibly-failed workflow as a hidden
  "success-despite-failure." See `trace/execution.py` (`workflow_status`).
- It also corrected three of the author's own labels — the timeout detector was *more*
  correct than first assumed (a 45s httpRequest node, and a 90s webhook, are genuine
  timeouts even when the workflow total is under 5 minutes).
- `mine` measures the **error** lane only against real data — n8n's status gives a clean
  label for node errors, but there is no clean n8n label for "this timeout/resource
  pattern was a real problem," so those are not fabricated on real data.
