#!/bin/bash
# Contract tests for dispatch-obligation-nudge.py (提示型 gate：所有錯誤分支都必須靜默 exit 0)
set -u
HOOK="$(dirname "$0")/dispatch-obligation-nudge.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export DON_TEST_MODE=1 DON_LOG="$TMP/log.jsonl" DON_STATE_DIR="$TMP/state" DON_RELAY_KEY=test-key DON_FORCE_ARM=treatment
pass=0; fail=0
ok() { pass=$((pass+1)); echo "PASS $1"; }
ko() { fail=$((fail+1)); echo "FAIL $1: $2"; }

mk_transcript() {
  local f="$1"; shift
  : > "$f"
  for line in "$@"; do echo "$line" >> "$f"; done
}
HUMAN='{"type":"user","uuid":"h1","message":{"role":"user","content":"幫我查三家 gateway 的 Jev 價格與限流，比較後給表"}}'
HUMAN_SHORT='{"type":"user","uuid":"h2","message":{"role":"user","content":"可以"}}'
ASSIST_TEXT='{"type":"assistant","message":{"role":"assistant","model":"gpt-5.6-sol","content":[{"type":"text","text":"我打算逐家查官方文件再彙整。"}]}}'
SEARCH='{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"WebSearch","input":{"query":"x"}}]}}'
FETCH='{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"WebFetch","input":{"url":"x"}}]}}'
NAV='{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t3","name":"mcp__claude-in-chrome__navigate","input":{"url":"x"}}]}}'
AGENT='{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"a1","name":"Agent","input":{"subagent_type":"parallel-search","prompt":"q"}}]}}'
META='{"type":"user","isMeta":true,"message":{"role":"user","content":[{"type":"text","text":"<system-reminder>x</system-reminder>"}]}}'

run_prompt() { printf '%s' "$1" | python3 "$HOOK" prompt; }
run_tool() { printf '%s' "$1" | python3 "$HOOK" tool; }
payload_prompt() { python3 -c 'import json,sys; print(json.dumps({"session_id":"s1","transcript_path":sys.argv[1],"prompt":sys.argv[2],"cwd":"/tmp"}))' "$1" "$2"; }
payload_tool() { python3 -c 'import json,sys; print(json.dumps({"session_id":"s1","transcript_path":sys.argv[1],"tool_name":sys.argv[2]}))' "$1" "$2"; }

T="$TMP/t.jsonl"; mk_transcript "$T" "$HUMAN" "$ASSIST_TEXT"

# fake answer 會跳過請求組裝，這裡從 HTTP 邊界驗證輸出上限與 JSON 判定仍能通過。
python3 - "$HOOK" "$T" "$TMP" <<'EOF' && ok "HTTP request caps output and preserves JSON nudge" || ko "HTTP output cap" "see traceback"
import json, os, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

captured = []
answer = {"trigger": {"choice": "search>2", "probabilities": {"none": 0.05, "big": 0.02, "edit>5": 0.03, "search>2": 0.9}}, "exceptionHolds": {"probability": 0.1}}

class Relay(BaseHTTPRequestHandler):
  def do_POST(self):
    captured.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
    body = json.dumps({"choices": [{"message": {"content": json.dumps(answer)}}]}).encode()
    self.send_response(200)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def log_message(self, *args):
    pass

server = HTTPServer(("127.0.0.1", 0), Relay)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
env = dict(os.environ)
env.pop("DON_FAKE_ANSWER", None)
env.update({"DON_RELAY_URL": "http://127.0.0.1:%s/v1/chat/completions" % server.server_port, "DON_MODEL": "groq-qwen-3.8-27b", "DON_LOG": str(Path(sys.argv[3]) / "cap-log.jsonl"), "DON_STATE_DIR": str(Path(sys.argv[3]) / "cap-state"), "DON_CONTROL": "0"})
payload = {"session_id": "cap-fixture", "transcript_path": sys.argv[2], "prompt": "請核對三家官方網站並比較", "cwd": sys.argv[3]}
try:
  result = subprocess.run([sys.executable, sys.argv[1], "prompt"], input=json.dumps(payload), text=True, capture_output=True, env=env, timeout=5)
finally:
  server.shutdown()
  server.server_close()
  thread.join(timeout=2)

assert result.returncode == 0, result.stderr
assert len(captured) == 1, captured
path, request = captured[0]
assert path == "/v1/chat/completions", path
assert request.get("max_tokens") == 256, request
assert request["response_format"] == {"type": "json_object"}, request
assert request["model"] == "groq-qwen-3.8-27b", request
assert request["temperature"] == 0, request
assert [m["role"] for m in request["messages"]] == ["system", "user"], request
output = json.loads(result.stdout)
assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit", output
assert "dispatch-obligation" in output["hookSpecificOutput"]["additionalContext"], output
row = json.loads((Path(sys.argv[3]) / "cap-log.jsonl").read_text())
assert row["result"] == "nudge" and row["pMust"] == 0.81, row
EOF

# known-bad: model says search>2 with no exception → nudge
out=$(DON_FAKE_ANSWER='{"trigger":{"choice":"search>2","probabilities":{"none":0.05,"big":0.02,"edit>5":0.03,"search>2":0.9}},"exceptionHolds":{"probability":0.1}}' run_prompt "$(payload_prompt "$T" "可以，開始")"); rc=$?
if [ $rc -eq 0 ] && echo "$out" | grep -q "dispatch-obligation" && echo "$out" | grep -q "事實研究"; then ok "prompt known-bad nudges with trigger label"; else ko "prompt known-bad" "rc=$rc out=$out"; fi
grep -q '"result": "nudge"' "$DON_LOG" && ok "prompt nudge logged" || ko "prompt log" "$(cat "$DON_LOG")"

# known-good: model says none → silent
out=$(DON_FAKE_ANSWER='{"trigger":{"choice":"none","probabilities":{"none":0.95,"big":0.02,"edit>5":0.02,"search>2":0.01}},"exceptionHolds":{"probability":0.2}}' run_prompt "$(payload_prompt "$T" "謝謝")"); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && ok "prompt known-good silent" || ko "prompt known-good" "rc=$rc out=$out"

# boundary on P(must)=pTrigger×(1−pException): 0.7×0.3=0.21 silent; 0.9×0.45=0.405 silent; 0.75×0.9=0.675 fires (2026-09-19 real relay case that the old 0.8 rule missed)
out=$(DON_FAKE_ANSWER='{"trigger":{"choice":"search>2","probabilities":{"none":0.3,"big":0,"edit>5":0,"search>2":0.7}},"exceptionHolds":{"probability":0.7}}' run_prompt "$(payload_prompt "$T" "查一下")")
[ -z "$out" ] && ok "boundary pMust 0.21 silent" || ko "boundary pMust 0.21" "$out"
out=$(DON_FAKE_ANSWER='{"trigger":{"choice":"search>2","probabilities":{"none":0.1,"big":0,"edit>5":0,"search>2":0.9}},"exceptionHolds":{"probability":0.55}}' run_prompt "$(payload_prompt "$T" "查一下")")
[ -z "$out" ] && ok "boundary pMust 0.405 silent" || ko "boundary pMust 0.405" "$out"
out=$(DON_FAKE_ANSWER='{"trigger":{"choice":"search>2","probabilities":{"none":0.05,"big":0.15,"edit>5":0.05,"search>2":0.75}},"exceptionHolds":{"probability":0.1}}' run_prompt "$(payload_prompt "$T" "逐家核對後做表")")
echo "$out" | grep -q "dispatch-obligation" && ok "boundary pMust 0.675 fires (regression: old separate-threshold rule stayed quiet)" || ko "boundary pMust 0.675" "$out"

# injection / slash prompts skipped without calling model
out=$(DON_FAKE_ANSWER='{"trigger":{"choice":"big","probabilities":{"none":0,"big":1,"edit>5":0,"search>2":0}},"exceptionHolds":{"probability":0}}' run_prompt "$(payload_prompt "$T" "<system-reminder>x</system-reminder>")")
[ -z "$out" ] && ok "prompt injection-shaped skipped" || ko "prompt injection" "$out"
out=$(DON_FAKE_ANSWER='{"trigger":{"choice":"big","probabilities":{"none":0,"big":1,"edit>5":0,"search>2":0}},"exceptionHolds":{"probability":0}}' run_prompt "$(payload_prompt "$T" "/compact")")
[ -z "$out" ] && ok "prompt slash skipped" || ko "prompt slash" "$out"

# error paths: relay unreachable, timeout, malformed answer → silent exit 0
out=$(DON_RELAY_URL="http://127.0.0.1:9/v1/chat/completions" DON_TIMEOUT_S=0.3 run_prompt "$(payload_prompt "$T" "查三家價格")"); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && grep -q '"result": "unavailable"' "$DON_LOG" && ok "relay unreachable → silent, logged unavailable" || ko "relay unreachable" "rc=$rc out=$out"
out=$(DON_FAKE_ANSWER='{"garbage":true}' run_prompt "$(payload_prompt "$T" "查三家價格")"); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && grep -q '"result": "malformed"' "$DON_LOG" && ok "malformed answer → silent" || ko "malformed" "rc=$rc out=$out"
out=$(printf 'not json' | python3 "$HOOK" prompt); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && ok "bad payload → silent" || ko "bad payload" "rc=$rc out=$out"

# lifecycle recovery: DON_DISABLE=1 → silent even on known-bad
out=$(DON_DISABLE=1 DON_FAKE_ANSWER='{"trigger":{"choice":"search>2","probabilities":{"none":0,"big":0,"edit>5":0,"search>2":1}},"exceptionHolds":{"probability":0}}' run_prompt "$(payload_prompt "$T" "可以")")
[ -z "$out" ] && ok "DON_DISABLE=1 silences" || ko "disable" "$out"

# log path pathological: symlink → refuse to write, still exit 0 and still nudge
ln -sf /dev/null "$TMP/evil.jsonl"
out=$(DON_LOG="$TMP/evil.jsonl" DON_FAKE_ANSWER='{"trigger":{"choice":"big","probabilities":{"none":0,"big":0.9,"edit>5":0.05,"search>2":0.05}},"exceptionHolds":{"probability":0}}' run_prompt "$(payload_prompt "$T" "整個 repo 盤點")"); rc=$?
[ $rc -eq 0 ] && echo "$out" | grep -q "dispatch-obligation" && [ -L "$TMP/evil.jsonl" ] && ok "symlink log refused, hook still works" || ko "symlink log" "rc=$rc out=$out"

# blinding: state sent to model must not contain agent/model names (checked via fake echo file)
mk_transcript "$TMP/b.jsonl" "$HUMAN" '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"我會派 routed-judge 用 opus 查"}]}}'
python3 - "$HOOK" "$TMP/b.jsonl" <<'EOF' && ok "blinding masks agent and model names in state" || ko "blinding" "names leaked"
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("don", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
entries = m.parse_entries(m.read_tail(sys.argv[2]))
earlier, reply = m.context_before_prompt(entries)
assert "routed-judge" not in reply and "opus" not in reply and "<agent-name>" in reply and "<model>" in reply, reply
EOF

# tool mode: 3 searches, no agent → nudge once; second call same turn → silent (marker)
mk_transcript "$TMP/s3.jsonl" "$HUMAN" "$SEARCH" "$FETCH" "$NAV"
out=$(run_tool "$(payload_tool "$TMP/s3.jsonl" "mcp__claude-in-chrome__navigate")"); rc=$?
[ $rc -eq 0 ] && echo "$out" | grep -q "連續 3 次" && ok "tool known-bad: 3 searches no agent → nudge" || ko "tool known-bad" "rc=$rc out=$out"
out=$(run_tool "$(payload_tool "$TMP/s3.jsonl" "WebSearch")")
[ -z "$out" ] && ok "tool dedupe: same turn nudges once" || ko "tool dedupe" "$out"
# new human turn resets the marker
mk_transcript "$TMP/s3b.jsonl" "$HUMAN" "$SEARCH" "$FETCH" "$NAV" "$HUMAN_SHORT" "$SEARCH" "$FETCH" "$NAV"
out=$(run_tool "$(payload_tool "$TMP/s3b.jsonl" "WebSearch")")
echo "$out" | grep -q "連續 3 次" && ok "tool: new turn nudges again" || ko "tool new turn" "$out"
# 2 searches → silent; 3 searches with Agent → silent; meta user line does not split the turn
mk_transcript "$TMP/s2.jsonl" "$HUMAN" "$SEARCH" "$FETCH"
out=$(run_tool "$(payload_tool "$TMP/s2.jsonl" "WebFetch")"); [ -z "$out" ] && ok "tool boundary: 2 searches silent" || ko "tool boundary" "$out"
mk_transcript "$TMP/sa.jsonl" "$HUMAN" "$SEARCH" "$AGENT" "$FETCH" "$NAV"
out=$(run_tool "$(payload_tool "$TMP/sa.jsonl" "WebFetch")"); [ -z "$out" ] && ok "tool known-good: dispatched → silent" || ko "tool dispatched" "$out"
mk_transcript "$TMP/sm.jsonl" "$HUMAN" "$SEARCH" "$META" "$FETCH" "$NAV"
DON_STATE_DIR="$TMP/state2" out=$(DON_STATE_DIR="$TMP/state2" run_tool "$(payload_tool "$TMP/sm.jsonl" "WebFetch")"); echo "$out" | grep -q "連續 3 次" && ok "tool: meta user line does not split turn" || ko "tool meta split" "$out"
# non-search tool name → silent; state dir symlink → silent exit 0
out=$(run_tool "$(payload_tool "$TMP/s3.jsonl" "Bash")"); [ -z "$out" ] && ok "tool: non-search tool ignored" || ko "tool non-search" "$out"
ln -sf /dev/null "$TMP/state3"; out=$(DON_STATE_DIR="$TMP/state3" run_tool "$(payload_tool "$TMP/s3b.jsonl" "WebSearch")"); rc=$?
[ $rc -eq 0 ] && ok "tool: state dir pathological → exit 0" || ko "tool state dir" "rc=$rc"

# 2026-09-26 隨機對照：control 組判定該提醒時只記 would-nudge、不注入；對照期過後或 DON_CONTROL=0 一律回到提醒
BAD_ANSWER='{"trigger":{"choice":"search>2","probabilities":{"none":0.05,"big":0.02,"edit>5":0.03,"search>2":0.9}},"exceptionHolds":{"probability":0.1}}'
export DON_LOG="$TMP/ab.jsonl"
out=$(DON_FORCE_ARM=control DON_TEST_TODAY=2026-09-27 DON_FAKE_ANSWER="$BAD_ANSWER" run_prompt "$(payload_prompt "$T" "可以，開始")"); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && grep -q '"result": "would-nudge"' "$DON_LOG" && grep -q '"arm": "control"' "$DON_LOG" && ok "control prompt: would-nudge logged, nothing injected" || ko "control prompt" "rc=$rc out=$out log=$(cat "$DON_LOG" 2>/dev/null)"
out=$(DON_FORCE_ARM=treatment DON_TEST_TODAY=2026-09-27 DON_FAKE_ANSWER="$BAD_ANSWER" run_prompt "$(payload_prompt "$T" "可以，開始")")
echo "$out" | grep -q "dispatch-obligation" && tail -1 "$DON_LOG" | grep -q '"arm": "treatment"' && ok "treatment prompt: nudges and logs arm" || ko "treatment prompt" "$out"
out=$(DON_FORCE_ARM=control DON_TEST_TODAY=2026-09-27 DON_FAKE_ANSWER='{"trigger":{"choice":"none","probabilities":{"none":0.95,"big":0.02,"edit>5":0.02,"search>2":0.01}},"exceptionHolds":{"probability":0.2}}' run_prompt "$(payload_prompt "$T" "謝謝")")
[ -z "$out" ] && tail -1 "$DON_LOG" | grep -q '"result": "quiet"' && tail -1 "$DON_LOG" | grep -q '"arm": "control"' && ok "control quiet row still carries arm" || ko "control quiet arm" "$(tail -1 "$DON_LOG")"
out=$(DON_FORCE_ARM=control DON_TEST_TODAY=2026-10-03 DON_FAKE_ANSWER="$BAD_ANSWER" run_prompt "$(payload_prompt "$T" "可以，開始")")
[ -z "$out" ] && ok "boundary: 2026-10-03 still in control window" || ko "boundary 10-03" "$out"
out=$(DON_FORCE_ARM=control DON_TEST_TODAY=2026-10-04 DON_FAKE_ANSWER="$BAD_ANSWER" run_prompt "$(payload_prompt "$T" "可以，開始")")
echo "$out" | grep -q "dispatch-obligation" && tail -1 "$DON_LOG" | grep -q '"arm": "off"' && ok "boundary: 2026-10-04 window over → everyone nudged" || ko "boundary 10-04" "$out"
out=$(DON_CONTROL=0 DON_FORCE_ARM=control DON_TEST_TODAY=2026-09-27 DON_FAKE_ANSWER="$BAD_ANSWER" run_prompt "$(payload_prompt "$T" "可以，開始")")
echo "$out" | grep -q "dispatch-obligation" && ok "recovery: DON_CONTROL=0 ends control early" || ko "DON_CONTROL=0" "$out"
out=$(DON_DISABLE=1 DON_FORCE_ARM=treatment DON_TEST_TODAY=2026-09-27 DON_FAKE_ANSWER="$BAD_ANSWER" run_prompt "$(payload_prompt "$T" "可以，開始")")
[ -z "$out" ] && ok "recovery: DON_DISABLE=1 still silences during control window" || ko "disable in window" "$out"
mk_transcript "$TMP/sc.jsonl" "$HUMAN" "$SEARCH" "$FETCH" "$NAV"
before=$(wc -l < "$DON_LOG")
out=$(DON_STATE_DIR="$TMP/state-ab" DON_FORCE_ARM=control DON_TEST_TODAY=2026-09-27 run_tool "$(payload_tool "$TMP/sc.jsonl" "WebSearch")")
[ -z "$out" ] && tail -1 "$DON_LOG" | grep -q '"event": "tool"' && tail -1 "$DON_LOG" | grep -q '"result": "would-nudge"' && ok "control tool: would-nudge logged, nothing injected" || ko "control tool" "out=$out $(tail -1 "$DON_LOG")"
out=$(DON_STATE_DIR="$TMP/state-ab" DON_FORCE_ARM=control DON_TEST_TODAY=2026-09-27 run_tool "$(payload_tool "$TMP/sc.jsonl" "WebFetch")")
after=$(wc -l < "$DON_LOG")
[ -z "$out" ] && [ $((after - before)) -eq 1 ] && ok "control tool: same turn logs once" || ko "control tool dedupe" "rows=$((after - before))"
python3 - "$HOOK" <<'EOF' && ok "arm assignment: stable per session, both arms reachable, off outside test force" || ko "arm assignment" "see traceback"
import importlib.util, os, sys
os.environ.pop("DON_FORCE_ARM", None); os.environ["DON_TEST_TODAY"] = "2026-09-27"
spec = importlib.util.spec_from_file_location("don", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ids = ["session-%d" % i for i in range(40)]
arms = [m.arm_of(i) for i in ids]
assert arms == [m.arm_of(i) for i in ids], "unstable"
assert set(arms) == {"treatment", "control"}, set(arms)
os.environ["DON_TEST_MODE"] = "0"; os.environ["DON_FORCE_ARM"] = "control"
assert m.arm_of("session-1") == m.arm_of("session-1") and m.arm_of("x") in {"treatment", "control", "off"}
EOF
python3 - "$HOOK" <<'EOF' && ok "arm: production mode ignores DON_FORCE_ARM" || ko "force arm leak" "force honoured outside test mode"
import importlib.util, os, sys, hashlib
os.environ["DON_TEST_MODE"] = "0"; os.environ.pop("DON_CONTROL", None)
spec = importlib.util.spec_from_file_location("don", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
sid = next(s for s in ("p%d" % i for i in range(100)) if hashlib.sha256(s.encode()).digest()[0] % 2 == 0)
os.environ["DON_FORCE_ARM"] = "control"
assert m.arm_of(sid) in {"treatment", "off"}, m.arm_of(sid)
EOF
export DON_LOG="$TMP/log.jsonl"

echo "pass=$pass fail=$fail"
[ $fail -eq 0 ] && echo "DISPATCH-OBLIGATION-CONTRACT-OK"
[ $fail -eq 0 ]
