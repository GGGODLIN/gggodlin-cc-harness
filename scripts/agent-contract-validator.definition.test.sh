#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents"
printf '%s\n' '---' 'model: opus' 'effort: medium' 'tools: [Read]' '---' > "$TMP/global/agents/missing-name.md"
printf '%s\n' '---' 'name: duplicate' 'tools: [Read]' '---' > "$TMP/global/agents/duplicate.md"
printf '%s\n' '---' 'name: duplicate' 'tools: [Read]' '---' > "$TMP/global/agents/duplicate-copy.md"
printf '%s\n' '---' 'name: declared-name' 'tools: [Read]' '---' > "$TMP/global/agents/wrong-file.md"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 1 ]; then
  printf 'FAIL definition completeness exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const codes = new Set(data.diagnostics.map(item => item.code))
if (!codes.has("MISSING_AGENT_NAME") || !codes.has("DUPLICATE_AGENT_NAME") || !codes.has("AGENT_FILENAME_MISMATCH")) process.exit(1)
if (data.diagnostics.some(item => item.status !== "error" || !item.path || !item.line || !item.column)) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL definition completeness diagnostics: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS definition completeness diagnostics\n'
