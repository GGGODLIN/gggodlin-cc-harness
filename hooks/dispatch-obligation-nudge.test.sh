#!/bin/bash
# Contract tests for dispatch-obligation-nudge.py (提示型 gate：所有錯誤分支都必須靜默 exit 0)
set -u
HOOK="$(dirname "$0")/dispatch-obligation-nudge.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# selfbulk 預設關：沒帶假答案的舊案例否則會真的打本機 relay；selfbulk 段與 HTTP 案例再各自打開
export DON_TEST_MODE=1 DON_LOG="$TMP/log.jsonl" DON_STATE_DIR="$TMP/state" DON_RELAY_KEY=test-key DON_FORCE_ARM=treatment DON_SELFBULK_DISABLE=1
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
    request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
    captured.append((self.path, request))
    reply = {"q_zh": 0.95, "q_en": 0.95} if "q_en:" in request["messages"][0]["content"] else answer
    body = json.dumps({"choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
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
env.pop("DON_SELFBULK_DISABLE", None)
env["DON_SELFBULK_SYNC"] = "1"
env.update({"DON_RELAY_URL": "http://127.0.0.1:%s/v1/chat/completions" % server.server_port, "DON_MODEL": "groq-qwen-3.8-27b", "DON_LOG": str(Path(sys.argv[3]) / "cap-log.jsonl"), "DON_STATE_DIR": str(Path(sys.argv[3]) / "cap-state"), "DON_CONTROL": "0"})
payload = {"session_id": "cap-fixture", "transcript_path": sys.argv[2], "prompt": "請核對三家官方網站並比較", "cwd": sys.argv[3]}
try:
  result = subprocess.run([sys.executable, sys.argv[1], "prompt"], input=json.dumps(payload), text=True, capture_output=True, env=env, timeout=5)
finally:
  server.shutdown()
  server.server_close()
  thread.join(timeout=2)

assert result.returncode == 0, result.stderr
assert len(captured) == 2, captured
bulk = [r for p, r in captured if "q_en:" in r["messages"][0]["content"]]
assert len(bulk) == 1 and bulk[0]["max_tokens"] == 64 and bulk[0]["temperature"] == 0 and bulk[0]["model"] == "groq-qwen-3.8-27b", bulk
assert "[助理最後一則回覆]" in bulk[0]["messages"][1]["content"], bulk
path, request = next((p, r) for p, r in captured if "q_en:" not in r["messages"][0]["content"])
assert path == "/v1/chat/completions", path
assert request.get("max_tokens") == 256, request
assert request["response_format"] == {"type": "json_object"}, request
assert request["model"] == "groq-qwen-3.8-27b", request
assert request["temperature"] == 0, request
assert [m["role"] for m in request["messages"]] == ["system", "user"], request
output = json.loads(result.stdout)
assert output["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit", output
assert "dispatch-obligation" in output["hookSpecificOutput"]["additionalContext"], output
rows = [json.loads(l) for l in (Path(sys.argv[3]) / "cap-log.jsonl").read_text().splitlines()]
row = next(r for r in rows if r["event"] == "prompt")
assert row["result"] == "nudge" and row["pMust"] == 0.81, row
side = next(r for r in rows if r["event"] == "selfbulk")
assert side["result"] == "would-flag" and side["pEn"] == 0.95, side
assert "selfbulk" not in result.stdout and "逐一" not in result.stdout, result.stdout
EOF

python3 - "$HOOK" "$T" "$TMP" <<'EOF' && ok "prompt accepts a normal relay response beyond 1.5 seconds" || ko "prompt relay budget" "see traceback"
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

answer = {"trigger": {"choice": "search>2", "probabilities": {"none": 0.05, "big": 0.02, "edit>5": 0.03, "search>2": 0.9}}, "exceptionHolds": {"probability": 0.1}}

class Relay(BaseHTTPRequestHandler):
  def do_POST(self):
    self.rfile.read(int(self.headers["Content-Length"]))
    time.sleep(2)
    body = json.dumps({"choices": [{"message": {"content": json.dumps(answer)}}]}).encode()
    try:
      self.send_response(200)
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
      pass

  def log_message(self, *args):
    pass

server = ThreadingHTTPServer(("127.0.0.1", 0), Relay)
server.daemon_threads = False
thread = threading.Thread(target=server.serve_forever)
thread.start()
env = dict(os.environ)
for name in ("DON_FAKE_ANSWER", "DON_TIMEOUT_S"):
  env.pop(name, None)
env.update(DON_SELFBULK_DISABLE="1", DON_CONTROL="0", DON_RELAY_URL="http://127.0.0.1:%d/v1/chat/completions" % server.server_port, DON_LOG=str(Path(sys.argv[3]) / "budget.jsonl"), DON_STATE_DIR=str(Path(sys.argv[3]) / "budget-state"))
payload = json.dumps({"session_id": "relay-budget", "transcript_path": sys.argv[2], "prompt": "請核對三家官方網站並比較"})
try:
  result = subprocess.run([sys.executable, sys.argv[1], "prompt"], input=payload, text=True, capture_output=True, env=env, timeout=5)
  assert result.returncode == 0 and "dispatch-obligation" in result.stdout, (result.returncode, result.stdout, result.stderr)
  env["DON_TIMEOUT_S"] = "0.1"
  failed = subprocess.run([sys.executable, sys.argv[1], "prompt"], input=payload, text=True, capture_output=True, env=env, timeout=5)
  assert failed.returncode == 0 and failed.stdout == "", (failed.returncode, failed.stdout, failed.stderr)
  rows = [json.loads(line) for line in Path(env["DON_LOG"]).read_text().splitlines()]
  assert [row["result"] for row in rows] == ["nudge", "unavailable"], rows
finally:
  server.shutdown()
  server.server_close()
  thread.join()
EOF

# selfBulk 觀察題（2026-10-13）：只寫 log、永不注入；並行請求、分開冷卻、可單獨關閉
export DON_LOG="$TMP/sb.jsonl" DON_SELFBULK_DISABLE=0 DON_SELFBULK_SYNC=1
QUIET='{"trigger":{"choice":"none","probabilities":{"none":0.95,"big":0.02,"edit>5":0.02,"search>2":0.01}},"exceptionHolds":{"probability":0.2}}'
sb_last() { grep '"event": "selfbulk"' "$DON_LOG" | tail -1; }
out=$(DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_zh":0.95,"q_en":0.95}' run_prompt "$(payload_prompt "$T" "好")"); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && sb_last | grep -q '"result": "would-flag"' && ok "selfbulk known-bad: logged would-flag, nothing injected" || ko "selfbulk known-bad" "rc=$rc out=$out $(sb_last)"
out=$(DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_zh":0.0,"q_en":0.0}' run_prompt "$(payload_prompt "$T" "好")")
[ -z "$out" ] && sb_last | grep -q '"result": "quiet"' && ok "selfbulk known-good: quiet" || ko "selfbulk known-good" "$(sb_last)"
out=$(DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_zh":0.0,"q_en":0.5}' run_prompt "$(payload_prompt "$T" "好")")
sb_last | grep -q '"result": "would-flag"' && ok "selfbulk boundary: q_en 0.5 flags (zh ignored)" || ko "selfbulk boundary 0.5" "$(sb_last)"
out=$(DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_zh":0.99,"q_en":0.49}' run_prompt "$(payload_prompt "$T" "好")")
sb_last | grep -q '"result": "quiet"' && ok "selfbulk boundary: q_en 0.49 quiet even if zh high" || ko "selfbulk boundary 0.49" "$(sb_last)"
out=$(DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_en":"x"}' run_prompt "$(payload_prompt "$T" "好")"); rc=$?
[ $rc -eq 0 ] && sb_last | grep -q '"result": "malformed"' && ok "selfbulk malformed → logged, exit 0" || ko "selfbulk malformed" "$(sb_last)"
before=$(grep -c '"event": "selfbulk"' "$DON_LOG")
out=$(DON_SELFBULK_DISABLE=1 DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_zh":1,"q_en":1}' run_prompt "$(payload_prompt "$T" "好")")
[ "$(grep -c '"event": "selfbulk"' "$DON_LOG")" -eq "$before" ] && grep -q '"result": "quiet"' "$DON_LOG" && ok "recovery: DON_SELFBULK_DISABLE=1 stops only selfbulk" || ko "selfbulk disable" "$(tail -2 "$DON_LOG")"
out=$(DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_zh":1,"q_en":1}' run_prompt "$(payload_prompt "$T" "/compact")")
[ "$(grep -c '"event": "selfbulk"' "$DON_LOG")" -eq "$before" ] && ok "selfbulk skipped on slash prompt" || ko "selfbulk slash" "$(sb_last)"
mk_transcript "$TMP/noreply.jsonl" "$HUMAN"
out=$(DON_FAKE_ANSWER="$QUIET" DON_FAKE_SELFBULK='{"q_zh":1,"q_en":1}' run_prompt "$(payload_prompt "$TMP/noreply.jsonl" "好")")
[ "$(grep -c '"event": "selfbulk"' "$DON_LOG")" -eq "$before" ] && ok "selfbulk skipped when no prior main reply" || ko "selfbulk no reply" "$(sb_last)"
out=$(DON_RELAY_URL="http://127.0.0.1:9/v1/chat/completions" DON_TIMEOUT_S=0.3 DON_SELFBULK_TIMEOUT_S=0.3 run_prompt "$(payload_prompt "$T" "好")"); rc=$?
[ $rc -eq 0 ] && [ -z "$out" ] && sb_last | grep -q '"result": "unavailable"' && ok "selfbulk relay unreachable → unavailable, exit 0" || ko "selfbulk unreachable" "rc=$rc $(sb_last)"
python3 - "$HOOK" <<'EOF' && ok "selfbulk state: all main text after last human, tail 6000" || ko "selfbulk state" "see traceback"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("don", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
h = lambda t: {"type": "user", "message": {"role": "user", "content": t}}
a = lambda t: {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}
s = m.self_bulk_state([h("舊問題"), a("舊回覆"), h("你審得來嗎"), a("共 399 份"), a("x" * 7000), a("由我分批審")], "好")
assert "你審得來嗎" in s and "舊回覆" not in s and "由我分批審" in s and s.count("x") >= 5900, s[:200]
assert m.self_bulk_state([h("只有人類")], "好") == ""
EOF
python3 - "$HOOK" "$TMP" <<'EOF' && ok "selfbulk 429 sets only its own cooldown" || ko "selfbulk cooldown isolation" "see traceback"
import importlib.util, os, sys, threading, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
os.environ["DON_STATE_DIR"] = str(Path(sys.argv[2]) / "cool-state")
class R(BaseHTTPRequestHandler):
  def do_POST(self):
    self.rfile.read(int(self.headers["Content-Length"]))
    body = b'{"error":{"message":"Rate limit reached"}}'
    self.send_response(429); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
  def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), R); threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["DON_RELAY_URL"] = "http://127.0.0.1:%d/v1/chat/completions" % srv.server_port
os.environ.pop("DON_FAKE_SELFBULK", None)
spec = importlib.util.spec_from_file_location("don", sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
row = m.self_bulk_row("state", "s")
srv.shutdown()
assert row["result"] == "unavailable" and row["reason"] == "http-429", row
assert m.in_cooldown("selfbulk-cooldown") and not m.in_cooldown(), "cooldown leaked to the live question"
assert m.self_bulk_row("state", "s")["reason"] == "cooldown"
EOF
# 正式路徑（非 SYNC）：relay 慢 2 秒時 hook 仍立刻結束，log 列由脫離的子程序事後補上
python3 - "$HOOK" "$T" "$TMP" <<'EOF' && ok "selfbulk detached: hook returns fast, row lands later" || ko "selfbulk detached" "see traceback"
import json, os, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
QUIET = {"trigger": {"choice": "none", "probabilities": {"none": 0.95, "big": 0.02, "edit>5": 0.02, "search>2": 0.01}}, "exceptionHolds": {"probability": 0.2}}
class R(BaseHTTPRequestHandler):
  def do_POST(self):
    req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
    bulk = "q_en:" in req["messages"][0]["content"]
    if bulk:
      time.sleep(2)
    body = json.dumps({"choices": [{"message": {"content": json.dumps({"q_zh": 0.95, "q_en": 0.95} if bulk else QUIET)}}]}).encode()
    self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
  def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), R); threading.Thread(target=srv.serve_forever, daemon=True).start()
log = Path(sys.argv[3]) / "detached.jsonl"
env = {k: v for k, v in os.environ.items() if k not in ("DON_FAKE_ANSWER", "DON_FAKE_SELFBULK", "DON_SELFBULK_SYNC", "DON_SELFBULK_DISABLE")}
env.update({"DON_RELAY_URL": "http://127.0.0.1:%d/v1/chat/completions" % srv.server_port, "DON_LOG": str(log), "DON_STATE_DIR": str(Path(sys.argv[3]) / "det-state")})
payload = {"session_id": "detached", "transcript_path": sys.argv[2], "prompt": "好", "cwd": sys.argv[3]}
start = time.time()
result = subprocess.run([sys.executable, sys.argv[1], "prompt"], input=json.dumps(payload), text=True, capture_output=True, env=env, timeout=5)
elapsed = time.time() - start
assert result.returncode == 0 and result.stdout == "", result
assert elapsed < 1.5, elapsed
rows = []
for _ in range(60):
  rows = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
  if any(r["event"] == "selfbulk" for r in rows):
    break
  time.sleep(0.1)
srv.shutdown()
side = [r for r in rows if r["event"] == "selfbulk"]
assert len(side) == 1 and side[0]["result"] == "would-flag" and side[0]["ms"] >= 1900, rows
EOF
export DON_LOG="$TMP/log.jsonl" DON_SELFBULK_DISABLE=1

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
