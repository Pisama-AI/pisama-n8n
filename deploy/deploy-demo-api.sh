#!/usr/bin/env bash
# Deploy the hosted pisama-n8n demo detection API (Fly app: pisama-n8n-api).
#
# Always bakes the current git SHA into PISAMA_BUILD_REVISION so GET /healthz reports
# real image provenance. Without it the Dockerfile defaults the arg to "unknown", and
# the dogfood evidence gate silently skips --require-current-build. The preflight also
# refuses dirty or unmerged trees so the public source link identifies the exact
# image contents.
#
# Usage:  ./deploy/deploy-demo-api.sh            (deploy current HEAD)
#         ./deploy/deploy-demo-api.sh --now      (any extra flags pass through to flyctl)
set -euo pipefail

cd "$(dirname "$0")/.."  # repo root, so relative --config/--dockerfile paths resolve

rev="$(git rev-parse HEAD)"
source deploy/verify-public-revision.sh
source_revision_url="$(verified_public_source_revision_url "$rev")"

app="pisama-n8n-api"
echo "Deploying $app at build_revision=$rev"
flyctl deploy . \
  --config deploy/fly.toml \
  --dockerfile deploy/Dockerfile.server \
  -a "$app" \
  --build-arg PISAMA_BUILD_REVISION="$rev" \
  --build-arg PISAMA_SOURCE_REVISION_URL="$source_revision_url" \
  "$@"

# The deploy changed this app's live SHA, so any deployment snapshot that pins it is now
# stale. Remind the operator to refresh it (this app's provenance is verifiable any time
# via `curl https://pisama-n8n-api.fly.dev/healthz`).
echo
echo "Deploy complete: $app is now build_revision ${rev:0:7}."
echo "REMINDER: update your deployment snapshot ($app -> ${rev:0:7})."
