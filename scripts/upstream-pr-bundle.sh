#!/usr/bin/env bash
# Builds the read-only input for the upstream-pr-reviewer agent.
# The reviewer has only Read, so everything it must judge has to be in this one file;
# per-commit patches are included because a clean final diff can hide content added then removed.
set -euo pipefail

usage() {
  echo "usage: upstream-pr-bundle.sh --repo <path> --base <upstream ref, e.g. upstream/main> --out <file> [--head <ref>] [--title <text>] [--body-file <file>]" >&2
  exit 2
}

repo="" base="" out="" head="HEAD" title="" body_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --head) head="$2"; shift 2 ;;
    --title) title="$2"; shift 2 ;;
    --body-file) body_file="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$repo" ] && [ -n "$base" ] && [ -n "$out" ] || usage

git -C "$repo" rev-parse --verify --quiet "$base^{commit}" >/dev/null || { echo "base not found: $base" >&2; exit 1; }
git -C "$repo" rev-parse --verify --quiet "$head^{commit}" >/dev/null || { echo "head not found: $head" >&2; exit 1; }

head_sha=$(git -C "$repo" rev-parse "$head")
base_sha=$(git -C "$repo" merge-base "$base" "$head")
count=$(git -C "$repo" rev-list --count "$base_sha..$head_sha")

umask 077
{
  echo "# UPSTREAM CONTRIBUTION BUNDLE"
  echo "repo: $repo"
  echo "origin: $(git -C "$repo" remote get-url origin 2>/dev/null || echo '(none)')"
  echo "base ref: $base"
  echo "merge-base: $base_sha"
  echo "head: $head_sha"
  echo "commits to publish: $count"
  echo "files changed: $(git -C "$repo" diff --name-only "$base_sha" "$head_sha" | wc -l | tr -d ' ')"
  echo
  echo "# TITLE"
  echo "${title:-(not provided)}"
  echo
  echo "# BODY"
  if [ -n "$body_file" ]; then cat "$body_file"; else echo "(not provided)"; fi
  echo
  echo "# COMMITS (oldest first, full message, author/committer, patch)"
  git -C "$repo" log --reverse --format=fuller -p "$base_sha..$head_sha"
  echo
  echo "# FINAL DIFF ($base_sha..$head_sha)"
  git -C "$repo" diff "$base_sha" "$head_sha"
} > "$out"

echo "BUNDLE_PATH: $out"
echo "BUNDLE_TOTAL_LINES: $(wc -l < "$out" | tr -d ' ')"
echo "HEAD_SHA: $head_sha"
echo "COMMITS: $count"
