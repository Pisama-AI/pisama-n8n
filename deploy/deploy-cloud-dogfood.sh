#!/usr/bin/env bash
# Deploy the isolated n8n Cloud dogfood server with an exact local build revision.
#
# The build revision is an image build argument, not a static fly.toml value. Passing
# the current SHA at deploy time makes the corpus audit's --require-current-build gate
# meaningful while preserving the app's separate volume and revocable dogfood key.
# Dogfood commits are not required to be on public main, so this path deliberately does
# not claim an official source revision URL.
set -euo pipefail

cd "$(dirname "$0")/.."

revision="$(git rev-parse HEAD)"
source deploy/verify-public-revision.sh
verify_clean_tree

echo "Deploying pisama-n8n-cloud-dogfood at build_revision=$revision"
exec flyctl deploy . \
  --config deploy/fly.cloud-dogfood.toml \
  --dockerfile deploy/Dockerfile.server \
  -a pisama-n8n-cloud-dogfood \
  --build-arg PISAMA_BUILD_REVISION="$revision" \
  "$@"
