#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents" "$TMP/repo/.claude/skills/prose" "$TMP/repo/.claude/skills/syntax"
printf '%s\n' '---' 'name: known-agent' 'tools: [Read]' '---' > "$TMP/global/agents/known-agent.md"
printf '%s\n' 'This prose mentions subagent_type: missing-agent but does not dispatch it.' > "$TMP/repo/.claude/skills/prose/SKILL.md"
printf '%s\n' 'subagent_type: known-agent' > "$TMP/repo/.claude/skills/syntax/SKILL.md"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 0 ]; then
  printf 'FAIL prose filtering exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
if (data.status !== "pass" || data.summary.errors !== 0 || data.diagnostics.some(item => item.code === "UNKNOWN_AGENT_REFERENCE")) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL prose filtering diagnostics: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS prose filtering and explicit syntax\n'
