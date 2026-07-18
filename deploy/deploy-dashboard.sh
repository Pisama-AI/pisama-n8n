#!/usr/bin/env bash
# Deploy the two Vercel dashboards with baked git-SHA provenance, mirroring the Fly
# backend deploy scripts. Each build inlines the current HEAD SHA into
# NEXT_PUBLIC_BUILD_REVISION, so GET /api/version reports exactly which commit is
# serving — the same provenance contract the backends give via /healthz.
#
# Both Vercel projects have NO Git integration (`link: null`) by founder decision
# (2026-07-17): they deploy ONLY via this script, never on push. There is no CI here.
#
# Targets (both share this repo; the SaaS build sets NEXT_PUBLIC_SAAS=1 in Vercel env):
#   - SaaS  -> Vercel `pisama-n8n-app` (app.n8n.pisama.ai) — uses the local .vercel link.
#   - demo  -> Vercel `pisama-n8n`     (n8n.pisama.ai)     — selected via VERCEL_*_ID env.
#
# The `-b` (build-env) flag is what NEXT_PUBLIC_* inlining needs at BUILD time on Vercel;
# `-e` (runtime env) is kept too so the route can also read it server-side.
#
# Usage:  ./deploy/deploy-dashboard.sh              (both dashboards)
#         ./deploy/deploy-dashboard.sh --only saas  (SaaS only)
#         ./deploy/deploy-dashboard.sh --only demo  (demo only)
set -euo pipefail

# Demo project (`pisama-n8n`) identifiers — the local .vercel link points at the SaaS
# project, so the demo deploy selects its project explicitly via env override.
DEMO_ORG_ID="team_m6HF61lNCPj5COBu3VucPPZg"
DEMO_PROJECT_ID="prj_GyO1mpAfhYJewRQu9YmHJ04Ko1wS"

only=""
while [ $# -gt 0 ]; do
  case "$1" in
    --only)
      only="${2:-}"
      case "$only" in
        saas|demo) ;;
        *) echo "ERROR: --only takes 'saas' or 'demo', got '${only:-<empty>}'" >&2; exit 2 ;;
      esac
      shift 2
      ;;
    *) echo "ERROR: unknown argument '$1' (usage: [--only saas|demo])" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."  # repo root, so dashboard/ and ../pisama-n8n-cloud/ resolve

rev="$(git rev-parse HEAD)"
if ! git diff --quiet HEAD -- . 2>/dev/null; then
  echo "WARNING: working tree is dirty — build_revision=$rev will NOT match the deployed code." >&2
fi

# Deploy one dashboard target. $1 = human label; the remaining args are an env prefix
# (empty for SaaS = use the local .vercel link; VERCEL_*_ID for the demo project).
deploy_one() {
  label="$1"; shift
  echo "Deploying $label dashboard at build_revision=$rev"
  (cd dashboard && env "$@" vercel deploy --prod --yes \
    -e NEXT_PUBLIC_BUILD_REVISION="$rev" \
    -b NEXT_PUBLIC_BUILD_REVISION="$rev")
  echo "Deploy complete: $label is now build_revision ${rev:0:7}."
}

if [ "$only" != "demo" ]; then
  deploy_one "SaaS (pisama-n8n-app)"
fi
if [ "$only" != "saas" ]; then
  deploy_one "demo (pisama-n8n)" "VERCEL_ORG_ID=$DEMO_ORG_ID" "VERCEL_PROJECT_ID=$DEMO_PROJECT_ID"
fi

# The deploy just changed a dashboard's live SHA, so the RUNBOOK snapshot may now be
# stale. Run the drift checker (never fatal — the deploy already succeeded); the `if`
# consumes its non-zero exit and turns the verdict into an actionable reminder.
checker="../pisama-n8n-cloud/deploy/check-live-revisions.sh"
if [ -x "$checker" ]; then
  echo
  echo "Post-deploy RUNBOOK snapshot check:"
  if "$checker"; then
    echo "RUNBOOK snapshot matches live — nothing to update."
  else
    echo "REMINDER: update the RUNBOOK 'Currently deployed' snapshot (dashboards -> ${rev:0:7}),"
    echo "then re-run $checker to confirm."
  fi
fi
