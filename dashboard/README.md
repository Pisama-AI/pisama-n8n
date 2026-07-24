# pisama-n8n-dashboard

Focused Next.js dashboard for the self-host Pisama n8n server. It is intentionally
separate from the main Pisama frontend: no shared build, no shared routing, and no
need to run the larger multi-platform application.

## Available pages

- `/overview` — executions analyzed, fired detections, failure breakdown, and recent activity.
- `/detections` — fired detection list with filtering.
- `/detections/[id]` — explanation, execution trace, and a reviewable paid fix proposal.
- `/settings` — server connection, polling, and cloud-fix status.
- `/onboarding` and `/sign-in` — connection and hosted-account flows.

The detection detail defaults to guidance only. One-click apply is feature-flagged off by
default. When enabled, it uses a server-owned repair id and the server rejects stale
workflow updates or unsafe rollback attempts.

## Relationship to the monorepo frontend

This app copies presentational leaf components from `pisama/frontend`
(shadcn-based UI kit, the trace viewer, detection cards) rather than
depending on it directly — no shared build, no shared routing. Business
logic (fetching, auth, state) is written fresh against the self-host
server's API.

## Status

Implemented. The dashboard typechecks, production-builds, and has Playwright coverage for
the public hosted journey. Its self-host checks run against a real FastAPI server, the
published engine interfaces, and a fresh SQLite database. They cover overview, detection
filtering, trace detail, deep links, settings, onboarding routing, and authenticated API
boundaries.
