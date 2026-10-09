#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents" "$TMP/repo/.claude/skills/demo"
printf '%s\n' '---' 'name: zero-good' 'tools: []' '---' '<!-- intentional-zero-tools -->' > "$TMP/global/agents/zero-good.md"
printf '%s\n' '---' 'name: zero-bad' 'tools: []' '---' > "$TMP/global/agents/zero-bad.md"
printf '%s\n' '---' 'name: zero-prose' 'tools: []' '---' 'The intentional-zero-tools marker appears in prose.' > "$TMP/global/agents/zero-prose.md"
printf '%s\n' '---' 'name: tool-user' 'tools: [Read, MissingBuiltin, mcp__known__read, mcp__missing__read, mcp__plugin__read]' '---' > "$TMP/global/agents/tool-user.md"
printf '%s\n' '---' 'name: plugin:worker' 'tools: [MissingBuiltin]' '---' > "$TMP/global/agents/plugin-worker.md"
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: plugin:worker' > "$TMP/repo/.claude/skills/demo/SKILL.md"
printf '%s\n' '{"mcpServers":{"known":{}}}' > "$TMP/mcp.json"
printf '%s\n' '{"enabledPlugins":{"plugin@market":true}}' > "$TMP/settings.json"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" --mcp-config "$TMP/mcp.json" --settings "$TMP/settings.json" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 1 ]; then
  printf 'FAIL tools contract exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const codes = new Set(data.diagnostics.map(item => item.code))
if (!codes.has("ZERO_TOOLS_UNMARKED") || !codes.has("UNKNOWN_BUILTIN_TOOL") || !codes.has("UNKNOWN_MCP_TOOL")) process.exit(1)
if (codes.has("PLUGIN_TOOL_UNKNOWN") || codes.has("UNKNOWN_AGENT_REFERENCE")) process.exit(1)
const zeroDiagnostics = data.diagnostics.filter(item => item.code === "ZERO_TOOLS_UNMARKED")
if (!zeroDiagnostics.some(item => item.path.endsWith("/zero-prose.md"))) process.exit(1)
if (zeroDiagnostics.some(item => item.path.endsWith("/zero-good.md"))) process.exit(1)
const locations = data.diagnostics.filter(item => ["ZERO_TOOLS_UNMARKED", "UNKNOWN_BUILTIN_TOOL", "UNKNOWN_MCP_TOOL"].includes(item.code))
if (locations.some(item => !item.path || !item.line || !item.column || !item.surface)) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL tools contract diagnostics: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS tools contract diagnostics\n'
