# pisama-n8n-dashboard (planned)

Minimal Next.js dashboard for the self-host server. Not a fork of the main
Pisama monorepo frontend (97 routes) — this is a small, focused app with
roughly 10 routes:

- `/` — overview
- `/executions` — execution list
- `/executions/[id]` — execution / trace detail
- `/detections` — detection list
- `/detections/[id]` — detection detail, with a paid "get fix" upsell
- `/workflows` — workflow list
- `/workflows/[id]` — workflow detail
- `/settings` — server + auth settings
- `/stream` — live detection stream (SSE)

## Relationship to the monorepo frontend

This app copies presentational leaf components from `pisama/frontend`
(shadcn-based UI kit, the trace viewer, detection cards) rather than
depending on it directly — no shared build, no shared routing. Business
logic (fetching, auth, state) is written fresh against the self-host
server's API.

## Status

Not yet scaffolded beyond `package.json`. This README describes the
intended structure only; no pages or components exist yet.
