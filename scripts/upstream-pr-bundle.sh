#!/usr/bin/env bash
# Builds the read-only input for the upstream-pr-reviewer agent.
# The reviewer has only Read, so everything it must judge has to be in this one file;
# per-commit patches are included because a clean final diff can hide content added then removed.
set -euo pipefail

#
# --since <bundle already reviewed> writes a DELTA bundle instead: what changed after that review
# (title, body, new commits, the diff between the two heads), so a wording fix is not a full
# re-review (trial upstream-pr-delta-review, 2026-10-21). It falls back to a full bundle when the
# new head does not descend from the reviewed one, because a rewritten history can change content
# the earlier review saw, and a delta would hide that.
usage() {
  echo "usage: upstream-pr-bundle.sh --repo <path> --base <upstream ref, e.g. upstream/main> --out <file> [--head <ref>] [--title <text>] [--body-file <file>] [--since <reviewed bundle>]" >&2
  exit 2
}

repo="" base="" out="" head="HEAD" title="" body_file="" since=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --base) base="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --head) head="$2"; shift 2 ;;
    --title) title="$2"; shift 2 ;;
    --body-file) body_file="$2"; shift 2 ;;
    --since) since="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$repo" ] && [ -n "$base" ] && [ -n "$out" ] || usage
[ -z "$since" ] || [ -r "$since" ] || { echo "reviewed bundle not readable: $since" >&2; exit 1; }

git -C "$repo" rev-parse --verify --quiet "$base^{commit}" >/dev/null || { echo "base not found: $base" >&2; exit 1; }
git -C "$repo" rev-parse --verify --quiet "$head^{commit}" >/dev/null || { echo "head not found: $head" >&2; exit 1; }

head_sha=$(git -C "$repo" rev-parse "$head")
base_sha=$(git -C "$repo" merge-base "$base" "$head")
count=$(git -C "$repo" rev-list --count "$base_sha..$head_sha")

umask 077

new_body() { if [ -n "$body_file" ]; then cat "$body_file"; else echo "(not provided)"; fi; }

if [ -n "$since" ]; then
  prev_head=$(sed -n 's/^head: //p' "$since" | head -1)
  prev_title=$(awk '/^# TITLE$/{getline; print; exit}' "$since")
  if [ -n "$prev_head" ] && git -C "$repo" merge-base --is-ancestor "$prev_head" "$head_sha" 2>/dev/null; then
    tmp=$(mktemp -d)
    awk '/^# BODY$/{p=1; next} /^# COMMITS \(oldest first/{p=0} p' "$since" | sed '$d' > "$tmp/before"
    new_body > "$tmp/after"
    new_count=$(git -C "$repo" rev-list --count "$prev_head..$head_sha")
    {
      echo "# UPSTREAM CONTRIBUTION DELTA BUNDLE"
      echo "This is a re-review. The bundle at $since (head $prev_head) was already reviewed;"
      echo "below is only what changed since then. Judge these changes; the commit count and"
      echo "file count describe the delta, not the whole contribution."
      echo "repo: $repo"
      echo "origin: $(git -C "$repo" remote get-url origin 2>/dev/null || echo '(none)')"
      echo "base ref: $base"
      echo "merge-base: $base_sha"
      echo "reviewed head: $prev_head"
      echo "head: $head_sha"
      echo "commits to publish in total: $count"
      echo "new commits since review: $new_count"
      echo
      echo "# TITLE"
      if [ "${title:-(not provided)}" = "$prev_title" ]; then echo "(unchanged)"; else
        echo "before: $prev_title"; echo "after:  ${title:-(not provided)}"; fi
      echo
      echo "# BODY CHANGES (unified diff, reviewed body -> new body)"
      diff -u "$tmp/before" "$tmp/after" | tail -n +3 || true
      echo
      echo "# NEW COMMITS (oldest first, full message, author/committer, patch)"
      git -C "$repo" log --reverse --format=fuller -p "$prev_head..$head_sha"
      echo
      echo "# DIFF BETWEEN HEADS ($prev_head..$head_sha)"
      git -C "$repo" diff "$prev_head" "$head_sha"
    } > "$out"
    rm -rf "$tmp"
    echo "BUNDLE_PATH: $out"
    echo "BUNDLE_TOTAL_LINES: $(wc -l < "$out" | tr -d ' ')"
    echo "HEAD_SHA: $head_sha"
    echo "COMMITS: $count"
    echo "MODE: delta since $prev_head"
    exit 0
  fi
  echo "reviewed head ${prev_head:-(none)} is not an ancestor of $head_sha; writing a full bundle" >&2
fi

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
  new_body
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
