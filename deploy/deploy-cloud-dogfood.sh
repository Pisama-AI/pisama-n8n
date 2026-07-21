#!/usr/bin/env bash
# Deploy the isolated n8n Cloud dogfood server with verifiable source provenance.
#
# The build revision is an image build argument, not a static fly.toml value. Passing
# the current SHA at deploy time makes the corpus audit's --require-current-build gate
# meaningful while preserving the app's separate volume and revocable dogfood key.
set -euo pipefail

cd "$(dirname "$0")/.."

revision="$(git rev-parse HEAD)"
if ! git diff --quiet HEAD -- . 2>/dev/null; then
  echo "WARNING: working tree is dirty; build_revision=$revision may not match the image" >&2
fi

echo "Deploying pisama-n8n-cloud-dogfood at build_revision=$revision"
exec flyctl deploy . \
  --config deploy/fly.cloud-dogfood.toml \
  --dockerfile deploy/Dockerfile.server \
  -a pisama-n8n-cloud-dogfood \
  --build-arg PISAMA_BUILD_REVISION="$revision" \
  "$@"
