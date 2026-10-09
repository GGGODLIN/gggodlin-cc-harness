#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents" "$TMP/repo/.claude/skills/demo"
printf '%s\n' '---' 'name: known-agent' 'model: opus' 'effort: medium' 'tools: [Read]' '---' > "$TMP/global/agents/known-agent.md"
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: missing-agent' > "$TMP/repo/.claude/skills/demo/SKILL.md"
printf '%s\n' '{"mcpServers":{}}' > "$TMP/mcp.json"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" --mcp-config "$TMP/mcp.json" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 1 ]; then
  printf 'FAIL missing agent exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const diagnostic = data.diagnostics.find(item => item.code === "UNKNOWN_AGENT_REFERENCE")
if (!diagnostic || diagnostic.surface !== "dispatch-reference" || !diagnostic.path.endsWith("/SKILL.md") || diagnostic.line !== 4 || diagnostic.status !== "error") process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL missing agent structured diagnostic: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS missing agent structured diagnostic\n'
