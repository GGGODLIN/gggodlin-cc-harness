#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -r "$TMP"' EXIT
mkdir -p "$TMP/global/agents"
index=1
while [ "$index" -le 300 ]; do
  printf '%s\n' '---' "name: bad-$index" 'tools: [MissingTool]' '---' > "$TMP/global/agents/bad-$index.md"
  index=$((index + 1))
done

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" --mcp-config /dev/null 2>/dev/null |
  node --input-type=module -e '
let text = ""
process.stdin.setEncoding("utf8")
process.stdin.on("data", chunk => { text += chunk })
process.stdin.on("end", () => {
  const data = JSON.parse(text)
  if (data.status !== "fail" || data.valid !== false || data.summary.errors < 300 || data.diagnostics.length < 300) process.exit(1)
})
'; then
  printf 'PASS validator pipe output is complete\n'
else
  printf 'FAIL validator pipe output was truncated or invalid\n'
  exit 1
fi
