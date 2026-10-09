#!/bin/bash
# check-my-stack Step 1 reconcile probe: install state + self-stack references for one tool name.
# Covers CLI install managers; skill/agent adoption needs session-jsonl counts (not this script).
set -u
name="${1:-}"
if [ -z "$name" ]; then
  echo "usage: reconcile.sh <tool-name>"
  exit 1
fi

echo "== install state: $name =="
found=0
if command -v "$name" >/dev/null 2>&1; then
  echo "PATH: $(command -v "$name")"
  found=1
fi
for probe in "uv tool list" "npm ls -g --depth=0" "brew list" "pipx list"; do
  hit=$($probe 2>/dev/null | grep -i -- "$name")
  if [ -n "$hit" ]; then
    echo "${probe%% *}: $hit" | head -3
    found=1
  fi
done
[ "$found" -eq 0 ] && echo "not installed via PATH/uv/npm/brew/pipx"

echo "== self-stack references (skills/commands/agents) =="
refs=$(grep -rli -- "$name" ~/.claude/skills ~/.claude/commands ~/.claude/agents 2>/dev/null | grep -v "/check-my-stack/")
if [ -n "$refs" ]; then
  echo "$refs"
else
  echo "no references found"
fi
