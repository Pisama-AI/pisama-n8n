# Loop M3 — dashboard outcome metrics

## Goal

The shared dashboard renders the corrected canonical metrics (M1 SaaS `8920532`, M2
OSS `4416558`) in both modes, and the detail view records the "seen" denominator.
Every new type field is OPTIONAL and every new cell renders only when present, so any
server/dashboard vintage combination stays safe during the deploy window.

## Verification command

```bash
cd ~/pisama-n8n/dashboard && npx tsc --noEmit && npm run build
```

Pass = both clean. Fail = fix and re-run.
(Corrected mid-loop: this dashboard has NO lint script — the original command's
`npm run lint` failed with "missing script" and a pipe masked the exit. The honest
gate is tsc + build, both verified with unmasked exit codes.)

## Do NOT touch

- fetchApi/postApi semantics (the seen ping is a separate bare fetch BY DESIGN —
  postApi's 401 handler redirects the whole page in SaaS mode).
- The fail-soft overview pattern (operations query stays optional-chained).
- Servers (M1/M2 are committed).

## Tasks

- [x] operations.ts: optional type extensions (diagnosis seen/acceptance_of_seen/
      review_coverage/by_detector; time_to_verified_control; durable_controls
      proposed/applied/durable/by_kind/harness; share widens null → number|null).
- [x] detections.ts: seen_at on ServerDetection; markDetectionSeen as a bare fetch
      with catch (silent on 401 AND on an old server's 404).
- [x] DetectionDetailClient.tsx: ref-guarded one-shot seen ping (SSE invalidation
      refetches the detail query on every ingest event — an unguarded effect would
      re-ping per event; StrictMode double-mount absorbed by ref + idempotent server).
- [x] OverviewClient.tsx ReliabilityLearning: verified-time, durable-share, and
      seen-denominator cells, each guarded on field presence; label seen as
      "detail opens" (it measures opens, not list views).

## DONE gate

Output DONE only when every box is checked and the verification command passes.

## Notes

- The seen ping keys the effect on detection?.id with a useRef<Set> guard — the SSE
  handler invalidates the detail query per ingest event; without the guard every
  event would re-ping.
- All new cells guard on field presence, so the card renders correctly against
  pre-2026-07-20 servers (deploy-window safety matrix in the master plan).

## Final Status

DONE — tsc exit 0, build exit 0 (exit codes checked unmasked).
