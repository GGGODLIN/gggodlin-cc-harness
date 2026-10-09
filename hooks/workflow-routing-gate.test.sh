#!/usr/bin/env bash
# workflow-routing-gate.py 回歸：known-good／known-bad／邊界／自身生命週期（gate-authoring 第 3 條）。
set -u
HOOK="$(cd "$(dirname "$0")" && pwd)/workflow-routing-gate.py"
TMP=$(mktemp -d)
trap '/bin/rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
mkdir -p "$HOME/.claude/hooks" "$HOME/.claude/workflows"
PASS=0
FAIL=0

run_inline() {
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Workflow","tool_input":{"script":open(sys.argv[1]).read()}}))' "$1" | python3 "$HOOK"
}

expect() {
  local want="$1" name="$2" out="$3"
  local got=allow
  case "$out" in *'"deny"'*) got=deny ;; esac
  if [ "$got" = "$want" ]; then
    PASS=$((PASS + 1)); echo "PASS: $name"
  else
    FAIL=$((FAIL + 1)); echo "FAIL: $name (want $want, got $got) $out"
  fi
}

case_inline() {
  local want="$1" name="$2" body="$3"
  printf '%s\n' "$body" > "$TMP/s.js"
  expect "$want" "$name" "$(run_inline "$TMP/s.js")"
}

# known-good
case_inline allow 'agentType literal' "await agent('p', { label: 'x', agentType: 'routed-judge' })"
case_inline allow 'model literal' "await agent('p', { model: 'sonnet' })"
case_inline allow 'shorthand model key' "const model = 'opus'; await agent('p', { label, model })"
case_inline allow 'quoted agentType key' "await agent('p', { 'agentType': 'routed-mech' })"
case_inline allow 'spread opts' "await agent('p', { ...base, label: 'x' })"
case_inline allow 'opts variable (opaque)' "await agent(prompt, options)"
case_inline allow 'agent( inside string' "log('call agent(x) later'); await agent('p', { agentType: 'routed-mech' })"
case_inline allow 'agent( inside template text' 'const t = `agent(x) ${a}`; await agent(t, { model: "sonnet" })'
case_inline allow 'agent( inside comment' "// agent(x)
/* agent(y) */ await agent('p', { agentType: 'routed-impl' })"
case_inline allow 'method call .agent(' "await client.agent('p')"
case_inline allow 'identifier suffix myagent(' "await myagent('p')"

# known-bad
case_inline deny 'single-arg agent(p)' "await agent('p')"
case_inline deny 'literal opts without routing' "await agent('p', { label: 'x', schema: S })"
case_inline deny 'nested in arrow inside pipeline' "await pipeline(items, it => agent(\`do \${it}\`, { phase: 'A' }))"
case_inline deny 'multi-line call' "await agent(
  'long prompt',
  {
    label: 'x',
    phase: 'Verify',
  },
)"
case_inline deny 'model only inside nested object' "await agent('p', { schema: { model: 'x' } })"
case_inline deny 'one good one bad' "await agent('a', { agentType: 'routed-judge' }); await agent('b', { label: 'y' })"

# 邊界：prompt 字串裡含 model: 不算數
case_inline deny 'model: only inside prompt string' "await agent('model: opus please', { label: 'x' })"
case_inline allow 'template ${} with nested call keeps routing' 'await agent(`x ${f({a:1})}`, { agentType: "routed-mech" })'

# scriptPath / name 模式
printf '%s\n' "await agent('p')" > "$TMP/bad.js"
expect deny 'scriptPath bad' "$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Workflow","tool_input":{"scriptPath":sys.argv[1]}}))' "$TMP/bad.js" | python3 "$HOOK")"
printf '%s\n' "await agent('p')" > "$HOME/.claude/workflows/named-bad.js"
expect deny 'named workflow bad' "$(echo '{"tool_name":"Workflow","tool_input":{"name":"named-bad"}}' | python3 "$HOOK")"
expect allow 'named workflow not found' "$(echo '{"tool_name":"Workflow","tool_input":{"name":"no-such"}}' | python3 "$HOOK")"
expect allow 'scriptPath missing file' "$(echo '{"tool_name":"Workflow","tool_input":{"scriptPath":"/nonexistent/x.js"}}' | python3 "$HOOK")"

# 自身生命週期：非 Workflow tool、壞 JSON、停用開關
expect allow 'non-Workflow tool' "$(echo '{"tool_name":"Agent","tool_input":{"prompt":"agent(p)"}}' | python3 "$HOOK")"
expect allow 'malformed payload' "$(echo 'not json' | python3 "$HOOK")"
touch "$HOME/.claude/hooks/workflow-routing-gate.off"
expect allow 'off sentinel disables gate' "$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Workflow","tool_input":{"scriptPath":sys.argv[1]}}))' "$TMP/bad.js" | python3 "$HOOK")"
rm -f "$HOME/.claude/hooks/workflow-routing-gate.off"

# deny 訊息必須指回 SSOT
out=$(run_inline "$TMP/bad.js")
case "$out" in *subagent-routing.md*routed-judge*) PASS=$((PASS + 1)); echo 'PASS: deny message points to SSOT' ;; *) FAIL=$((FAIL + 1)); echo "FAIL: deny message lacks SSOT pointer: $out" ;; esac

echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
