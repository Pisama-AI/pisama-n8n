#!/usr/bin/env bash
# Deploy the hosted pisama-n8n demo detection API (Fly app: pisama-n8n-api).
#
# Always bakes the current git SHA into PISAMA_BUILD_REVISION so GET /healthz reports
# real image provenance. Without it the Dockerfile defaults the arg to "unknown", and
# the dogfood evidence gate silently skips --require-current-build. fly.toml cannot do
# this itself: a static [build.args] value would go stale the moment you commit again,
# so the live SHA has to be passed at deploy time — which is what this script is for.
#
# Usage:  ./deploy/deploy-demo-api.sh            (deploy current HEAD)
#         ./deploy/deploy-demo-api.sh --now      (any extra flags pass through to flyctl)
set -euo pipefail

cd "$(dirname "$0")/.."  # repo root, so relative --config/--dockerfile paths resolve

rev="$(git rev-parse HEAD)"
if ! git diff --quiet HEAD -- . 2>/dev/null; then
  echo "WARNING: working tree is dirty — build_revision=$rev will NOT match the deployed code." >&2
fi

echo "Deploying pisama-n8n-api at build_revision=$rev"
exec flyctl deploy . \
  --config deploy/fly.toml \
  --dockerfile deploy/Dockerfile.server \
  -a pisama-n8n-api \
  --build-arg PISAMA_BUILD_REVISION="$rev" \
  "$@"
