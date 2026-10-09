#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents"
printf '%s\n' '---' 'name: mcp-user' 'tools: [mcp__known__read, mcp__known__missing]' '---' > "$TMP/global/agents/mcp-user.md"
printf '%s\n' '{"mcpServers":{"known":{"tools":["read"]}}}' > "$TMP/mcp.json"
printf '%s\n' '{"enabledPlugins":{"plugin@market":true},"permissions":{"allow":["mcp__known__read","mcp__known__missing","mcp__plugin__read"]}}' > "$TMP/settings.json"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" --mcp-config "$TMP/mcp.json" --settings "$TMP/settings.json" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 1 ]; then
  printf 'FAIL exact MCP tool exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const diagnostic = data.diagnostics.find(item => item.code === "UNKNOWN_MCP_TOOL" && item.surface === "tool-reference")
const settingsDiagnostic = data.diagnostics.find(item => item.code === "UNKNOWN_MCP_TOOL" && item.surface === "settings")
if (!diagnostic || !diagnostic.message.includes("mcp__known__missing") || !diagnostic.path.endsWith("/mcp-user.md") || !diagnostic.line || !diagnostic.column) process.exit(1)
if (!settingsDiagnostic || !settingsDiagnostic.message.includes("mcp__known__missing") || !settingsDiagnostic.path.endsWith("/settings.json") || !settingsDiagnostic.line || !settingsDiagnostic.column) process.exit(1)
if (data.diagnostics.some(item => item.surface === "settings" && item.message.includes("mcp__known__read"))) process.exit(1)
if (data.diagnostics.some(item => item.surface === "settings" && item.message.includes("mcp__plugin__read"))) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL exact MCP tool diagnostic: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS exact MCP tool diagnostic\n'
