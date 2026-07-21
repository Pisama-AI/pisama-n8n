# FE provenance + drift check + scripted dashboard deploy

## Goal

Make the two Vercel dashboard deployments (demo `pisama-n8n` → n8n.pisama.ai, SaaS
`pisama-n8n-app` → app.n8n.pisama.ai) provenance-checked exactly like the Fly backends:
a baked build SHA served at `/api/version`, a deploy script that injects it, and the
existing drift checker extended to cover both dashboards. Fix the RUNBOOK's false
"frontends auto-deploy on push" claim (both Vercel projects have `link: null` — CLI
deploys only, permanently, per founder decision 2026-07-17).

## Verification command

Run after every change, from `~/pisama-n8n`:

```bash
bash -n deploy/deploy-dashboard.sh \
  && bash -n ../pisama-n8n-cloud/deploy/check-live-revisions.sh \
  && (cd dashboard && npx tsc --noEmit && npm run build) \
  && (cd ../pisama-n8n-cloud && ./deploy/check-live-revisions.sh; test $? -le 1)
```

Pass = all four parts succeed AND the checker's output lists FIVE rows: the three Fly
apps each `-> MATCH`, plus rows for `pisama-n8n` and `pisama-n8n-app` (their status may
be FETCH-FAILED or MISMATCH before the next scripted deploy — that is EXPECTED; the
post-deploy exit-0 acceptance happens outside this loop). Fail = keep working. Do NOT
open a browser, do NOT ask the user — fix and re-run.

## Do NOT touch

- Any Vercel deploy/env mutation — the loop writes SCRIPTS ONLY; it never runs
  `vercel deploy`, never sets env vars, never touches Fly.
- `~/pisama-n8n-cloud/saas_server/`, `migrations/`, `tests/` (Loop 2/3 territory).
- The three existing Fly deploy scripts and their RUNBOOK sections' semantics.
- `dashboard/src/lib/`, `dashboard/src/components/` (no app-code changes beyond the
  new route file).
- Do not commit anything outside the files this plan names.

## Tasks

- [x] **Audit**: read `~/pisama-n8n/deploy/deploy-demo-api.sh` (the pattern),
      `~/pisama-n8n-cloud/deploy/check-live-revisions.sh` (row regex line ~20, URL
      line ~31, exit codes 0/1/2), `~/pisama-n8n-cloud/RUNBOOK.md` (topology lines
      ~10-18, snapshot table lines ~30-34), `dashboard/next.config.js`,
      `dashboard/src/app/api/backend/[...path]/route.ts` (route-handler convention).
      Write findings in `## Notes` BEFORE editing.
- [x] **Fix 1 — version route**: `dashboard/src/app/api/version/route.ts` returning
      JSON `{"build_revision": process.env.NEXT_PUBLIC_BUILD_REVISION ?? (process.env.VERCEL_GIT_COMMIT_SHA ?? "unknown")}`
      with `export const dynamic = 'force-static'` OMITTED (env is baked at build; a
      plain handler is fine). Same JSON key as the backends' /healthz. Verify tsc+build.
- [x] **Fix 2 — deploy script**: `deploy/deploy-dashboard.sh` (chmod 755) mirroring
      `deploy-demo-api.sh`: `set -euo pipefail`; cd to repo root; `rev=$(git rev-parse HEAD)`;
      dirty-tree warning; then for each target — SaaS: `(cd dashboard && vercel deploy --prod --yes -e NEXT_PUBLIC_BUILD_REVISION="$rev" -b NEXT_PUBLIC_BUILD_REVISION="$rev")`
      using the local `.vercel` link; demo: same but with
      `VERCEL_ORG_ID=team_m6HF61lNCPj5COBu3VucPPZg VERCEL_PROJECT_ID=prj_GyO1mpAfhYJewRQu9YmHJ04Ko1wS`
      env override. IMPORTANT: `-b` (build-env) is what NEXT_PUBLIC_* inlining needs at
      build time on Vercel; keep `-e` too for runtime route reads. Accept an optional
      `--only saas|demo` arg. End with a best-effort
      `../pisama-n8n-cloud/deploy/check-live-revisions.sh` call (never fatal), like
      deploy-saas.sh does.
- [x] **Fix 3 — checker extension**: edit `~/pisama-n8n-cloud/deploy/check-live-revisions.sh`:
      add a `url_for(app)` case — `pisama-n8n` → `https://n8n.pisama.ai/api/version`,
      `pisama-n8n-app` → `https://app.n8n.pisama.ai/api/version`, default
      `https://${app}.fly.dev/healthz`. Keep the row regex compatible (app names both
      match `pisama-[a-z0-9-]+` already — verify the repo cell: FE rows' repo is
      `pisama-n8n`, fine). Keep exit-code semantics (0/1/2) byte-identical.
- [x] **Fix 4 — RUNBOOK truth**: in `~/pisama-n8n-cloud/RUNBOOK.md`: (a) replace the
      "Frontends auto-deploy on push to `main` via Vercel — nothing to run by hand"
      sentence with the truth (CLI-scripted via `deploy-dashboard.sh` in the pisama-n8n
      repo; both Vercel projects have no Git integration by decision); (b) add two rows
      to the "Currently deployed" table: `pisama-n8n` and `pisama-n8n-app`, repo
      `pisama-n8n`, SHA = current HEAD short SHA of `~/pisama-n8n` (fill the real
      value); (c) add a short "Dashboards (Vercel)" section with the deploy command +
      verify curl (`/api/version`).
- [x] **Commit** (both repos, ONLY these files): pisama-n8n → route + script + this
      plan file; pisama-n8n-cloud → checker + RUNBOOK. Clear commit messages. Do NOT
      push (the operator pushes after review).

## Terminal gate

Output the single word DONE on its own line ONLY when every box is checked and the
verification command passes as defined above (five rows listed, three Fly MATCHes,
both scripts lint, tsc+build green, commits made). Do not stop for any other reason.

## Baseline run

`cd ~/pisama-n8n-cloud && ./deploy/check-live-revisions.sh` (2026-07-18):

```
  pisama-n8n-api     table=9d3540f  live=9d3540ff06b5  -> MATCH
  pisama-n8n-saas    table=f0b132d  live=f0b132dd1528  -> MATCH
  pisama-n8n-cloud   table=01a4be6  live=01a4be6b093b  -> MATCH
==> ALL MATCH — RUNBOOK snapshot is accurate
EXIT=0
```

3 Fly rows, all MATCH, exit 0. `~/pisama-n8n` HEAD short SHA = `9d3540f`.

## Notes

Audit findings (2026-07-18):

- **`deploy-demo-api.sh`** (the pattern): `set -euo pipefail`; `cd "$(dirname "$0")/.."`
  to repo root; `rev="$(git rev-parse HEAD)"`; dirty-tree warning via
  `git diff --quiet HEAD -- .`; `flyctl deploy` with `--build-arg PISAMA_BUILD_REVISION="$rev"`
  and `"$@"` passthrough; closing echo reminder using `${rev:0:7}`.
- **`deploy-saas.sh`** best-effort post-deploy check pattern (to mirror): `echo`,
  `if ./deploy/check-live-revisions.sh; then echo "...matches..."; else echo "REMINDER..."; fi`
  — the `if` consumes the checker's non-zero exit so it is never fatal.
- **`check-live-revisions.sh`**: `set -uo pipefail` (deliberately NOT -e). Row regex
  (line 15): `\| \`pisama-[a-z0-9-]+\` \| \`[a-z0-9-]+\` \| \`[0-9a-f]{7,40}\` \|` — app in
  first backtick cell, repo in 2nd, short SHA (hex 7-40) in 3rd. URL hardcoded (line 27):
  `https://${app}.fly.dev/healthz`; parses `"build_revision":"..."` via sed. Exit codes:
  **2** = no table rows found; **1** = any fetch-fail/mismatch (`fail=1`); **0** = all match.
  FE app names `pisama-n8n` / `pisama-n8n-app` both already satisfy `pisama-[a-z0-9-]+`, and
  their repo cell is `pisama-n8n` (matches `[a-z0-9-]+`), so new rows parse without regex change.
- **RUNBOOK.md**: topology table lines 10-16 (already lists both Vercel dashboards); the
  false claim is line 18-19 ("Frontends auto-deploy on push to `main` via Vercel — nothing to
  run by hand."); snapshot table lines 30-34 (3 Fly rows).
- **`next.config.js`**: minimal (reactStrictMode + turbopack root). No env plumbing needed —
  Next inlines `NEXT_PUBLIC_*` at build time automatically.
- **route.ts convention**: `app/api/<name>/route.ts`, imports from `next/server`, exports
  named HTTP verbs (`export const GET = handle`). New route goes at `app/api/version/route.ts`.
- **Local `.vercel/project.json`**: linked to SaaS project — `projectId
  prj_e7MXvL53m3eIkvRUhnoh0nmYTlJ7`, `orgId team_m6HF61lNCPj5COBu3VucPPZg`, name
  `pisama-n8n-app`. So SaaS deploy uses the local link; demo deploy overrides via
  `VERCEL_PROJECT_ID=prj_GyO1mpAfhYJewRQu9YmHJ04Ko1wS` (+ same org id).

## Final Status

Done 2026-07-18. All boxes checked; verification command exits 0.

Final verification output (exact command from "Verification command"):

```
  pisama-n8n-api     table=9d3540f  live=9d3540ff06b5  -> MATCH
  pisama-n8n-saas    table=f0b132d  live=f0b132dd1528  -> MATCH
  pisama-n8n-cloud   table=01a4be6  live=01a4be6b093b  -> MATCH
  pisama-n8n         table=9d3540f  live=FETCH-FAILED  -> ERROR
  pisama-n8n-app     table=9d3540f  live=FETCH-FAILED  -> ERROR
==> DRIFT — update the RUNBOOK 'Currently deployed' table (or investigate the deploy)
OVERALL_EXIT=0
```

Five rows: three Fly `-> MATCH`, plus the two dashboards. The FE rows are `FETCH-FAILED`
because `/api/version` is not deployed yet (no scripted dashboard deploy has run) — EXPECTED
per the plan; checker exit 1 is `<= 1`, so the overall command exits 0. `npm run build` shows
`/api/version` as a route; `bash -n` clean on both scripts; `tsc --noEmit` green.

Delivered:
- `dashboard/src/app/api/version/route.ts` — build_revision provenance endpoint.
- `deploy/deploy-dashboard.sh` (755) — SHA-baking Vercel deploy for both dashboards, `--only`.
- `pisama-n8n-cloud/deploy/check-live-revisions.sh` — `url_for()` maps the two FE apps to
  `/api/version` on their custom domains; exit-code semantics unchanged.
- `pisama-n8n-cloud/RUNBOOK.md` — corrected the auto-deploy claim, added two snapshot rows,
  added a "Dashboards (Vercel)" section.

Committed to both repos (not pushed — operator pushes after review).
