#!/usr/bin/env bash

readonly PISAMA_PUBLIC_GIT_URL="https://github.com/Pisama-AI/pisama-n8n.git"
readonly PISAMA_PUBLIC_GIT_BRANCH="main"

verify_clean_tree() {
  local changes

  if ! changes="$(git status --porcelain --untracked-files=normal)"; then
    echo "ERROR: unable to inspect the deployment worktree." >&2
    return 1
  fi
  if [ -n "$changes" ]; then
    echo "ERROR: refusing to deploy a dirty tree because build_revision would be inaccurate." >&2
    return 1
  fi
}

verify_public_revision() {
  local revision="$1"

  verify_clean_tree || return
  if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: refusing to deploy a non-canonical build revision: $revision" >&2
    return 1
  fi
  if ! git fetch --quiet --no-tags "$PISAMA_PUBLIC_GIT_URL" "$PISAMA_PUBLIC_GIT_BRANCH"; then
    echo "ERROR: unable to fetch the canonical Pisama-AI/pisama-n8n branch." >&2
    return 1
  fi
  if ! git merge-base --is-ancestor "$revision" FETCH_HEAD; then
    echo "ERROR: refusing to deploy revision $revision because it is not reachable from Pisama-AI/pisama-n8n main." >&2
    return 1
  fi
}

# A public deployment may advertise a source revision only after the clean-tree and
# public-default-branch checks above succeed.
verified_public_source_revision_url() {
  local revision="$1"
  verify_public_revision "$revision" || return
  printf 'https://github.com/Pisama-AI/pisama-n8n/commit/%s' "$revision"
}
