#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents"
printf '%s\n' '---' 'name: Bad_Name' 'tools: [Read]' '---' > "$TMP/global/agents/invalid-name.md"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 1 ]; then
  printf 'FAIL invalid name exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const diagnostic = data.diagnostics.find(item => item.code === "INVALID_AGENT_NAME")
if (!diagnostic || diagnostic.surface !== "agent-definition" || !diagnostic.path.endsWith("/invalid-name.md") || !diagnostic.line || !diagnostic.column) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL invalid name diagnostic: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS invalid name diagnostic\n'
