#!/usr/bin/env bash
set -u

CLI="$(cd "$(dirname "$0")" && pwd)/agent-contract-validator.mjs"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/global/agents" "$TMP/repo/.claude/skills/demo" "$TMP/repo/.claude/workflows"
printf '%s\n' '---' 'name: routed-impl' 'model: opus' 'effort: medium' 'tools: [Read]' '---' > "$TMP/global/agents/routed-impl.md"
printf '%s\n' '---' 'name: routed-judge' 'model: opus' 'effort: xhigh' 'tools: [Read]' '---' > "$TMP/global/agents/routed-judge.md"
printf '%s\n' '---' 'name: helper-a' 'tools: [Read]' '---' > "$TMP/global/agents/helper-a.md"
printf '%s\n' '---' 'name: helper-b' 'tools: [Read]' '---' > "$TMP/global/agents/helper-b.md"
printf '%s\n' '---' 'name: namespace:worker' 'tools: [Read]' '---' > "$TMP/global/agents/namespace-worker.md"
printf '%s\n' '---' 'name: demo' '---' 'subagent_type: general-purpose' 'agentType: claude' 'subagent_type: namespace:worker' 'agentType: ${selectedAgent}' 'subagent_type: helper-b' > "$TMP/repo/.claude/skills/demo/SKILL.md"
printf '%s\n' 'export const run = () => agent("demo", { agentType: "routed-impl" })' > "$TMP/repo/.claude/workflows/demo.mjs"
printf '%s\n' '| Agent | Class | model | effort |' '|---|---|---|---|' '| routed-impl | implementation | opus | medium |' '| routed-judge | judgment | sonnet | xhigh |' > "$TMP/routing.md"
printf '%s\n' '{"permissions":{"deny":["Agent(general-purpose)","Agent(claude)"]}}' > "$TMP/settings.json"

if node "$CLI" --global-root "$TMP/global" --repo-root "$TMP/repo" --routing "$TMP/routing.md" --settings "$TMP/settings.json" > "$TMP/output.json" 2>&1; then
  status=0
else
  status=$?
fi

if [ "$status" -ne 1 ]; then
  printf 'FAIL routing contract exit status: %s\n' "$status"
  exit 1
fi

node -e '
const fs = require("node:fs")
const data = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const codes = new Set(data.diagnostics.map(item => item.code))
if (!codes.has("ROUTING_POLICY_MISMATCH") || !codes.has("DISABLED_AGENT_REFERENCE") || !codes.has("DYNAMIC_AGENT_REFERENCE_UNVERIFIED")) process.exit(1)
const dynamic = data.diagnostics.find(item => item.code === "DYNAMIC_AGENT_REFERENCE_UNVERIFIED")
if (!dynamic || dynamic.status !== "unverified" || dynamic.surface !== "dispatch-reference" || !dynamic.path.endsWith("/SKILL.md") || !dynamic.line || !dynamic.column) process.exit(1)
if (data.summary.unverified < 1 || data.diagnostics.some(item => item.code === "UNKNOWN_AGENT_REFERENCE" && item.message.includes("namespace:worker"))) process.exit(1)
' "$TMP/output.json" || {
  printf 'FAIL routing contract diagnostics: %s\n' "$(<"$TMP/output.json")"
  exit 1
}

printf 'PASS routing contract diagnostics\n'
