#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents" "$TMP/repo/.claude/skills/demo" "$TMP/repo/.claude/workflows"
printf '%s\n' '---' 'name: zero-output' 'tools: []' '---' '<!-- intentional-zero-tools -->' > "$TMP/global/agents/zero-output.md"
printf '%s\n' '---' 'name: helper-a' 'tools: [Read, mcp__known__read, mcp__plugin__read]' '---' > "$TMP/global/agents/helper-a.md"
printf '%s\n' '---' 'name: helper-b' 'tools: [Read]' '---' > "$TMP/global/agents/helper-b.md"
printf '%s\n' '---' 'name: namespace:worker' 'tools: [MissingBuiltin]' '---' > "$TMP/global/agents/plugin-worker.md"
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: helper-a' 'subagent_type: helper-b' 'subagent_type: namespace:worker' 'agentType: ${selectedAgent}' > "$TMP/repo/.claude/skills/demo/SKILL.md"
printf '%s\n' 'export const run = () => agent("demo", { agentType: "helper-a" })' > "$TMP/repo/.claude/workflows/demo.mjs"
printf '%s\n' '{"mcpServers":{"known":{}}}' > "$TMP/mcp.json"
printf '%s\n' '{"enabledPlugins":{"plugin@market":true}}' > "$TMP/settings.json"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" --mcp-config "$TMP/mcp.json" --settings "$TMP/settings.json" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 0 ]; then
  printf 'FAIL valid fixture exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
if (data.status !== "pass" || data.valid !== true || data.summary.errors !== 0 || data.summary.unverified !== 1) process.exit(1)
if (data.diagnostics.some(item => item.status === "error" || item.code === "UNKNOWN_AGENT_REFERENCE" || item.code === "UNKNOWN_MCP_TOOL")) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL valid fixture result: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS valid fixture exit status and exclusions\n'
