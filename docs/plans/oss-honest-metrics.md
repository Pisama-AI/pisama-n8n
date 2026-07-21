# Loop M2 — OSS honest metric corrections

## Goal

The self-host server's reliability metrics converge to the canonical shape Loop M1
shipped on the SaaS (master plan: `~/.claude/plans/i-want-to-build-soft-treehouse.md`):
seen-tracking with a sound acceptance denominator, a REAL durable-control share
(replacing the hardcoded `"share": None` that also counted rolled-back and drifted
repairs), time_to_verified_control, and per-detector diagnosis.

## Verification command

```bash
cd ~/pisama-n8n && ~/pisama-n8n-cloud/.venv/bin/python -m pytest server/tests -q && \
  (cd engine && ~/pisama-n8n-cloud/.venv/bin/python -m pytest tests -q) && \
  ~/pisama-n8n-cloud/.venv/bin/python benchmarks/parity_check.py && \
  /Users/tuomonikulainen/pisama/backend/.venv/bin/ruff check server/
```

Pass = server + engine green, parity 7/7, ruff clean. Fail = fix and re-run.

## Do NOT touch

- The engine (parity-locked; zero changes).
- applied_at/rolled_back_at state-machine semantics.
- The conclude gates / probe semantics.
- The SaaS repo (M1 is committed; keep the shapes identical by mirroring, not editing).

## Tasks

- [x] DetectionRow.seen_at + `_ADDED_COLUMNS["detections"]` catch-up + to_dict.
- [x] mark_detection_seen (first-wins) + POST /api/v1/detections/{id}/seen (require_auth).
- [x] _diagnosis_metrics: seen (detected+seen_at), acceptance_of_seen, review_coverage,
      by_detector — same key set as SaaS.
- [x] time_to_verified_control (prevented cases, received_at → outcome_at) + key in
      _reliability_metrics.
- [x] Rewrite _durable_control_metrics: mirror the SaaS module-level pure helpers
      (_percentile stays; _repair_kind + _classify_durable_controls) over one
      outerjoin; keep applied_workflow_controls; drop hardcoded share None.
- [x] tests server/tests/test_reliability_metrics.py: seen idempotency + payload +
      404; diagnosis numbers (two detectors, partial seen); durable one-fixture-per-
      cell incl. applied-repair-with-NO-case (NULL trap) + legacy no-kind guard_config;
      time_to_verified incl. prevented-then-rolled-back; frozen key-set matching M1's.

## DONE gate

Output DONE only when every box is checked and the verification command passes.

## Notes

- One pre-existing test (test_server.py:test_feedback_and_operations_summary...)
  pinned the OLD diagnosis shape exactly; updated to the canonical shape — the shape
  change IS the feature, not gate-weakening.
- _classify_durable_controls / _repair_kind mirrored byte-for-byte from the SaaS
  (module-level pure functions in both).
- The durable test seeds repair rows directly (each classification cell needs an
  exact lifecycle state); everything else drives the real webhook/API path.

## Final Status

DONE — server 70 passed / engine 113 passed / parity 7/7 / ruff clean.
