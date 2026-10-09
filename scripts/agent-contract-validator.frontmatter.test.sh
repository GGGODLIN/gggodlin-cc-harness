#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents"
printf '%s\n' '---' 'name: invalid-agent' 'model: gpt' 'effort: extreme' 'tools: [Read]' '---' > "$TMP/global/agents/invalid-agent.md"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 1 ]; then
  printf 'FAIL invalid frontmatter exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const codes = new Set(data.diagnostics.map(item => item.code))
const diagnostics = data.diagnostics.filter(item => codes.has(item.code))
if (!codes.has("INVALID_MODEL") || !codes.has("INVALID_EFFORT") || diagnostics.some(item => item.surface !== "agent-definition" || !item.path.endsWith("/invalid-agent.md") || item.line !== 3 && item.line !== 4)) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL invalid frontmatter diagnostics: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS invalid frontmatter diagnostics\n'
