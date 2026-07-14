# pisama-n8n dashboard — real Pisama FE, wired to the self-host server

**Goal:** A minimal 3-view dashboard (overview, detections list, detection detail) that
REUSES the Pisama frontend's design and components (already copied) and renders REAL
detections fetched from the pisama-n8n server. Do NOT reinvent styling — the broadsheet
theme (globals.css / tailwind.config.ts) and the shadcn ui + detection components are
copied verbatim from the monorepo; compose them, don't restyle them.

**Verification command (run after every change):**
```bash
cd /Users/tuomonikulainen/pisama-n8n/dashboard && npm run build
```
Pass = exit 0, `next build` compiles + typechecks clean, all 3 routes build
(`/`, `/detections`, `/detections/[id]`).
Fail = keep working. Do NOT open a browser, do NOT ask the user — fix and re-run.
(Live-render against the running server is verified separately by the main session after
the build is green — you do not need a server running to pass this gate.)

**What already exists (built + committed — USE it, don't redo):**
- Foundation builds green: `package.json` (Next 16.1/React 19.2/Tailwind 3.4),
  `next.config.js`, `tsconfig.json` (`@/*`→`./src/*`), `src/app/layout.tsx` (Inter Tight +
  Newsreader + JetBrains Mono wiring), `src/app/providers.tsx` (QueryClient), a smoke
  `src/app/page.tsx` (REPLACE it with the real overview).
- Design tokens copied verbatim: `tailwind.config.ts`, `src/app/globals.css`,
  `src/lib/utils.ts` (`cn`, `normalizeConfidence`, `formatConfidencePct`),
  `src/lib/severity-config.ts`.
- UI primitives copied: `src/components/ui/{Button,Card,Badge,Skeleton,EmptyState,Input,Tooltip,Motion}.tsx`
  + a trimmed `index.ts` barrel.
- Detection leaves copied: `src/components/detection/{DetectionListItem,StatCard,DetectionTypeConfig}.tsx`,
  `src/components/dashboard/StatsCard.tsx`.
- `src/components/common/PisamaMark.tsx` (the logo, extracted).

**The server contract (real data source):**
- Base URL from `NEXT_PUBLIC_API_BASE` (default `http://localhost:8400`).
- `GET /api/v1/detections` → array of rows:
  `{ id:int, execution_id:int, detector:str, detected:bool, confidence:float,
     failure_mode:str|null, explanation:str }`.
  `detector` ∈ {cycle, schema, resource, timeout, error, complexity}.
- `GET /healthz` → `{status:"ok"}`.
- Auth: a `Bearer <PISAMA_API_KEY>` header if the server has a key. The dashboard reads the
  key from `localStorage['pisama_n8n_key']` client-side (a Settings field) OR from
  `NEXT_PUBLIC_API_KEY` at build time; if neither, send no header (dev mode).

**Do NOT touch:**
- The engine at `/Users/tuomonikulainen/pisama-n8n/engine/` — not part of this.
- `globals.css` / `tailwind.config.ts` — copied verbatim; do not restyle the theme.
- Do NOT add auth/tenancy/analytics. This is single-tenant self-host: no next-auth, no
  zustand tenancy, no ScopeFilter, no BFF proxy, no Sentry/PostHog.

---

## Tasks

- [x] **Baseline** — run the verification command (currently green on the smoke page).
  Confirm, note under "## Baseline run".

- [x] **Data layer** — create:
  - `src/lib/api/client.ts`: a plain `fetchApi(path)` doing `GET` against
    `NEXT_PUBLIC_API_BASE` (default `http://localhost:8400`), adding the Bearer header from
    `localStorage['pisama_n8n_key']` (guard for SSR: only read localStorage in the browser)
    or `NEXT_PUBLIC_API_KEY`. NO `/api/backend` proxy, NO `{tenant_id}` templating.
  - `src/lib/api/detections.ts`: the `ServerDetection` type (server shape above), a
    `Detection` type matching what `DetectionListItem` expects
    (`{id, detection_type, trace_id, confidence, method, business_impact?, validated,
    false_positive?, created_at, details?:{severity?, affected_agents?}}`), and an
    `adaptDetection(row: ServerDetection): Detection` mapping:
    `id→String(id)`, `detection_type→row.detector`, `trace_id→String(execution_id)`,
    `confidence→confidence`, `method→'n8n'`, `business_impact→explanation`,
    `validated→false`, `created_at→row.received_at ?? new Date().toISOString()`,
    `details.severity→` derive from confidence (`>=0.8 'high'`, `>=0.5 'medium'`, else
    `'low'`). Plus `getDetections(): Promise<Detection[]>` = fetch + map + filter/keep all.

- [x] **Extend DetectionTypeConfig for n8n** — the copied `DetectionTypeConfig.ts` has no
  keys for the 6 n8n detectors. Add entries for `cycle, schema, resource, timeout, error,
  complexity` to `detectionTypeConfig` (and `plainEnglishLabels`) with sensible
  `{ label, color, icon (a lucide-react icon), category }` — e.g. cycle→"Workflow Cycle"
  (RefreshCw), schema→"Schema Mismatch" (FileWarning), resource→"Resource Explosion"
  (Zap/Activity), timeout→"Timeout" (Clock), error→"Node Error" (AlertTriangle),
  complexity→"Excess Complexity" (GitBranch). Match the existing entries' shape exactly.

- [x] **Server: timestamp on detections** — in the pisama-n8n SERVER (allowed — it is not
  the engine), extend `GET /api/v1/detections` to include the execution's `received_at`
  on each row (join `detections.execution_id → executions.received_at`), so the adapter
  has a real timestamp. Files:
  `/Users/tuomonikulainen/pisama-n8n/server/pisama_n8n_server/storage.py` (list_detections)
  + keep the 8 server tests green:
  `PYTHONPATH="engine:server" /Users/tuomonikulainen/pisama/backend/.venv/bin/python -m pytest server/tests -q`.

- [x] **Shell** — copy + TRIM the monorepo `src/components/common/{Layout,Sidebar,Header}.tsx`
  from `/Users/tuomonikulainen/pisama-worktrees/n8n-eval-harness/frontend/src/components/common/`.
  Strip: Sidebar's `next-auth` (signOut/useSession), `useSafeAuth`, the super-admin gate,
  and the sign-out footer; Header's `ScopeFilter` + the search/notification/store bits.
  Point `PisamaMark` import at `@/components/common/PisamaMark`. Rewrite `navItems` to just:
  Overview (`/`), Detections (`/detections`). Keep the broadsheet look (amber active
  border, serif title, hairline rules). `Layout` stays as the sidebar+main shell.

- [x] **Views** —
  - `src/app/page.tsx` (Overview): a `StatsCard`/`StatCard` KPI row (executions analyzed,
    detections fired, detectors reporting) computed from `getDetections()`, inside `Layout`.
    Use a client component that calls a `useDetections` TanStack hook.
  - `src/app/detections/page.tsx` + a `DetectionsClient.tsx` (`'use client'`): fetch via
    `useDetections`, render fired detections as a `Card` containing `DetectionListItem`
    rows (pass the props it needs; `showSimplifiedView=true`, no-op `onInlineValidate`),
    an `EmptyState` when none, all inside `Layout`. RETARGET `DetectionListItem`'s hrefs so
    they point at `/detections/[id]` (not `/traces` or `/healing`) — pass a prop or edit the
    copied component's href.
  - `src/app/detections/[id]/page.tsx`: a simple detail view of one detection (detector,
    confidence, failure_mode, explanation, execution ref) using `Card` + `Badge` +
    `ConfidenceTierBadge`, inside `Layout`.
  - Add a small `useDetections` hook (`src/hooks/useDetections.ts`) wrapping
    `useQuery({queryKey:['detections'], queryFn: getDetections})`.

- [x] **Verify the gate** — `npm run build` green with all 3 routes. Record the route table
  in "## Final Status".

- [x] **Commit** — in `/Users/tuomonikulainen/pisama-n8n` (git identity
  user.name=tn-pisama, user.email=tuomo@pisama.ai), message:
  `feat(dashboard): overview + detections views reusing Pisama FE, wired to the server`.
  Do NOT push.

Output `DONE` once ALL boxes are checked AND `npm run build` passes with the 3 routes. Do
not output `DONE` for any other reason. If reusing a monorepo component genuinely requires
a heavy dep you cannot trim, STOP and record it as BLOCKED rather than pulling in
auth/tenancy/analytics.

---

## Baseline run

`npm run build` → exit 0. Next.js 16.2.10, compiled + typechecked clean. Routes at
baseline: `/` (smoke page) + `/_not-found`. Green.

## Notes

- Data layer: `src/lib/api/{client,detections}.ts`. `fetchApi` is SSR-safe (localStorage
  only read in the browser), no proxy / no tenant templating. `adaptDetection` maps the
  server shape and derives severity from confidence. Added two additive fields to the
  `Detection` type — `detected` and `failure_mode` — which `DetectionListItem` ignores but
  the overview (to count fired) and detail view (to show raw fields) need. `getDetections`
  keeps all rows; views filter on `detected`.
- DetectionTypeConfig: added the 6 n8n detectors (cycle/schema/resource/timeout/error/
  complexity) to both `detectionTypeConfig` and `plainEnglishLabels`, category "Workflow".
- Server: `list_detections` now joins `executions.received_at` onto each row. All 8 server
  tests pass (`server/tests`).
- Shell: trimmed Sidebar (no next-auth/useSafeAuth/super-admin/sign-out; navItems =
  Overview + Detections), Header (no ScopeFilter/search/notifications/demo store; static
  "Self-host" badge), Layout unchanged shell. PisamaMark points at `@/components/common`.
- Views: `page.tsx`→`OverviewClient` (KPI row via `useDetections`), `detections/page.tsx`→
  `DetectionsClient` (fired detections as `DetectionListItem` rows in a `Card`, EmptyState
  when none), `detections/[id]/page.tsx`→`DetectionDetailClient` (finds the detection from
  the cached list, renders `Card`+`Badge`+`ConfidenceTierBadge`). `useDetections` hook added.
  Retargeted `DetectionListItem` hrefs to `/detections/[id]`.
- No auth/tenancy/analytics pulled in. Nothing BLOCKED.

## Final Status

`npm run build` → exit 0, compiled + typechecked clean. Routes:

| Route               | Type    |
|---------------------|---------|
| `/`                 | Static  |
| `/_not-found`       | Static  |
| `/detections`       | Static  |
| `/detections/[id]`  | Dynamic |

All 3 target routes (`/`, `/detections`, `/detections/[id]`) build. Server tests: 8 passed.
