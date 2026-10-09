#!/usr/bin/env bash
set -uo pipefail

HOOK="$(dirname "$0")/T1-claim-detect-local-first.sh"
KEYWORDS="$(dirname "$0")/claim-detect-keywords.json"
TMP=$(mktemp -d)
PASS=0
FAIL=0

cleanup() {
  rm -r "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/home/.claude/hooks" "$TMP/home/.claude/logs"
cp "$KEYWORDS" "$TMP/home/.claude/hooks/claim-detect-keywords.json"

write_transcript() {
  local path="$1"
  local message="$2"
  local tool="$3"
  local input_json="$4"
  local error="$5"
  local second_tool="${6:-}"
  local second_input_json="${7:-}"
  [[ -n "$second_input_json" ]] || second_input_json='{}'
  local second_error="${8:-}"

  jq -nc '{type:"user",isMeta:false,message:{content:"run"}}' > "$path"
  jq -nc --arg tool "$tool" --argjson input "$input_json" '{type:"assistant",message:{content:[{type:"tool_use",id:"tool-1",name:$tool,input:$input}]}}' >> "$path"
  jq -nc --arg error "$error" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:"tool-1",is_error:true,content:$error}]}}' >> "$path"
  if [[ -n "$second_tool" ]]; then
    jq -nc --arg tool "$second_tool" --argjson input "$second_input_json" '{type:"assistant",message:{content:[{type:"tool_use",id:"tool-2",name:$tool,input:$input}]}}' >> "$path"
    jq -nc --arg error "$second_error" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:"tool-2",is_error:true,content:$error}]}}' >> "$path"
  fi
  jq -nc --arg message "$message" '{type:"assistant",message:{content:[{type:"text",text:$message}]}}' >> "$path"
}

run_case() {
  local name="$1"
  local message="$2"
  local tool="$3"
  local input_json="$4"
  local error="$5"
  local expected="$6"
  local pattern="${7:-}"
  local second_tool="${8:-}"
  local second_input_json="${9:-}"
  [[ -n "$second_input_json" ]] || second_input_json='{}'
  local second_error="${10:-}"
  local transcript="$TMP/$name.jsonl"
  local output
  local status=0

  write_transcript "$transcript" "$message" "$tool" "$input_json" "$error" "$second_tool" "$second_input_json" "$second_error"
  output=$(jq -nc --arg sid "test-$name" --arg path "$transcript" --arg message "$message" '{session_id:$sid,transcript_path:$path,last_assistant_message:$message,stop_hook_active:false}' | HOME="$TMP/home" "$HOOK") || status=$?

  if [[ "$status" -ne 0 ]]; then
    FAIL=$((FAIL + 1))
    printf 'FAIL %s exit=%s output=%s\n' "$name" "$status" "$output"
    return
  fi

  if [[ "$expected" == "silent" && -z "$output" ]]; then
    PASS=$((PASS + 1))
    printf 'PASS %s\n' "$name"
    return
  fi

  # 2026-09-24 恢復注入：命中時輸出要含合取 gate 提醒，且 audit 要記到本 case 的 fired=true。
  # 2026-09-17～09-24 曾為 detect-only（零輸出），那段期間的 expected=detect 已全數改回 fire。
  if [[ "$expected" == "fire" ]]; then
    local audit="$TMP/home/.claude/logs/T1-claim-detect-conjunction-audit.jsonl"
    local fired open
    fired=$(jq -r --arg sid "test-$name" 'select(.session_id == $sid) | .fired' "$audit" 2>/dev/null | tail -1)
    open=$(jq -r --arg sid "test-$name" 'select(.session_id == $sid) | .open_error_count' "$audit" 2>/dev/null | tail -1)
    if [[ "$output" == *"T1 claim-detect (合取 gate)"* && ( -z "$pattern" || "$output" == *"$pattern"* ) && "$fired" == "true" && "${open:-0}" -gt 0 ]]; then
      PASS=$((PASS + 1))
      printf 'PASS %s\n' "$name"
      return
    fi
    FAIL=$((FAIL + 1))
    printf 'FAIL %s expected=fire fired=%s open=%s output=%s\n' "$name" "$fired" "$open" "$output"
    return
  fi

  FAIL=$((FAIL + 1))
  printf 'FAIL %s expected=%s pattern=%s output=%s\n' "$name" "$expected" "$pattern" "$output"
}

run_case spoken-done '做完了。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' fire 'R1'
run_case spoken-fixed '修好了' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' fire 'R1'
run_case conditional '如果完成。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' silent
run_case negative '沒有修好。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' silent
run_case question '能否完成。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' silent
run_case object-complete '已將修正完成。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' fire 'R1'
run_case required-object-complete '需要的修正已完成。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' fire 'R1'
run_case english-incomplete 'The migration is incomplete.' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' silent
run_case english-unfixed 'The bug remains unfixed.' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' silent
run_case mixed-clause '測試還沒完成，但程式修好。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' fire 'R1'
run_case disclosed-agent 'xp-0-all 被 T2-routing-gate 攔下，未執行成功，也未重試。 DONE.' Agent '{"subagent_type":"xp-0-all"}' 'Agent type xp-0-all was blocked by T2-routing-gate' silent
run_case disclosed-agent-priority 'xp-0-all 被 T2-routing-gate 攔下，未執行成功。 DONE.' Agent '{"description":"alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu","prompt":"one two three four five six seven eight nine ten eleven twelve","subagent_type":"xp-0-all"}' 'Agent type xp-0-all was blocked by T2-routing-gate' silent
run_case retry-only 'verify.py 已重跑。全部完成。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' fire 'ImportError'
run_case bash-routing-text 'settings.json 的 rg 搜尋失敗。全部完成。' Bash '{"command":"rg routing-gate settings.json"}' 'Exit code 1: command referenced T2-routing-gate and 改派 documentation' silent
run_case no-retry-only 'xp-0-all 沒有重試。 DONE.' Agent '{"subagent_type":"xp-0-all"}' 'Agent type xp-0-all was blocked by T2-routing-gate' fire 'R1'
run_case actionable-write '五處全部完成。繁中副本已覆蓋。' Write '{"file_path":"/tmp/review-zh.md"}' 'File has not been read yet. Read it first before writing.' fire 'File has not been read yet'
run_case generic-anchor 'ImportError 已修正。全部完成。' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for' fire 'ImportError'
run_case unicode-anchor '繁中副本.md 尚未讀，因此 Write 失敗。全部完成。' Write '{"file_path":"/tmp/繁中副本.md"}' 'File has not been read yet. Read it first before writing.' silent
run_case partial-disclosure '全部完成。xp-0-all 被 gate 攔下，未執行成功。' Agent '{"subagent_type":"xp-0-all"}' 'Agent type xp-0-all was blocked by gate' fire 'ImportError' Bash '{"command":"python3 verify.py"}' 'Exit code 1: ImportError: cannot import section_for'
run_case no-error '全部完成。' Bash '{"command":"true"}' 'BLOCKED by dcg fixture noise' silent

# 反向斷言（2026-10-01）：L2 Gemini 已移除，不得再出現 L2 呼叫、Gemini 版號讀取或 model-routing 依賴；兩層逾時鎖在 1.5 秒
if ! grep -qE 'call_l2_relay|^L2_(URL|MODEL|TIMEOUT)=|^GEMINI_FLASH_MODEL=|scripts/model-routing\.sh' "$HOOK" \
  && grep -q '^L1_TIMEOUT=1.5$' "$HOOK" && grep -q '^L3_TIMEOUT="${T1_L3_TIMEOUT:-1.5}"$' "$HOOK"; then
  PASS=$((PASS + 1))
  printf 'PASS no-l2-and-1.5s-timeouts\n'
else
  FAIL=$((FAIL + 1))
  printf 'FAIL no-l2-and-1.5s-timeouts\n'
fi

AUDIT="$TMP/home/.claude/logs/T1-claim-detect-conjunction-audit.jsonl"
if [[ -f "$AUDIT" && "$(stat -f '%Lp' "$AUDIT")" == "600" ]] && ! grep -q 'claim_120' "$AUDIT"; then
  PASS=$((PASS + 1))
  printf 'PASS audit-ledger\n'
else
  FAIL=$((FAIL + 1))
  printf 'FAIL audit-ledger\n'
fi

# === L1 HTTP 狀態碼傳遞（2026-09-17）===
# 迴歸「return "$http_code" 被 bash 截成低 8 位」：429 曾變成 173，cooldown 分支從不觸發。
# 正反配對：429 必須建 cooldown；500 必須只記 log、不得建 cooldown。
l1_http_case() {
  local name="$1" code="$2" want_cooldown="$3"
  local home="$TMP/home-$name"
  mkdir -p "$home/.claude/hooks" "$home/.claude/logs" "$home/.claude/hooks/state"
  cp "$KEYWORDS" "$home/.claude/hooks/claim-detect-keywords.json"

  local port
  port=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')
  python3 -c "
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response($code); self.send_header('Content-Type','application/json'); self.end_headers()
        self.wfile.write(b'{\"error\":\"test\"}')
    def log_message(self, *a): pass
http.server.HTTPServer(('127.0.0.1', $port), H).serve_forever()
" &
  local pid=$!
  local ready=0 i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if python3 -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(0 if s.connect_ex(('127.0.0.1',$port))==0 else 1)"; then ready=1; break; fi
    sleep 0.2
  done
  if [[ "$ready" -ne 1 ]]; then
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
    FAIL=$((FAIL + 1)); printf 'FAIL %s (mock server 起不來)\n' "$name"; return
  fi

  local transcript="$TMP/$name.jsonl"
  jq -nc '{type:"user",isMeta:false,message:{content:"run"}}' > "$transcript"
  jq -nc '{type:"assistant",message:{content:[{type:"text",text:"全部完成。"}]}}' >> "$transcript"

  jq -nc --arg sid "test-$name" --arg path "$transcript" --arg m "全部完成。" \
    '{session_id:$sid,transcript_path:$path,last_assistant_message:$m,stop_hook_active:false}' \
    | HOME="$home" T1_RELAY_KEY="test-key" T1_L1_URL="http://127.0.0.1:$port/v1/chat/completions" \
      T1_L2_URL="http://127.0.0.1:$port/v1/chat/completions" \
      T1_L3_URL="http://127.0.0.1:$port/v1/systemone" T1_L3_KEY="test-key" "$HOOK" >/dev/null 2>&1
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null

  local cooldown="$home/.claude/hooks/state/T1-L1-cooldown"
  local warn="$home/.claude/hooks/T1-claim-detect.warnings.log"
  # 掃全檔而非 tail -1：cascade 結尾還會補 "L1+L2 failed, trying L3" 等行
  local has_cooldown=no; [[ -f "$cooldown" ]] && has_cooldown=yes
  local want_line; [[ "$want_cooldown" == "yes" ]] && want_line="429 quota" || want_line="L1 http=$code"
  local has_line=no; [[ -f "$warn" ]] && grep -q "$want_line" "$warn" && has_line=yes
  local saw_429=no; [[ -f "$warn" ]] && grep -q "429 quota" "$warn" && saw_429=yes

  if [[ "$has_cooldown" == "$want_cooldown" && "$has_line" == "yes" ]]; then
    # 反向斷言：500 這格不得誤判成 429
    if [[ "$want_cooldown" == "yes" || "$saw_429" == "no" ]]; then
      PASS=$((PASS + 1)); printf 'PASS %s\n' "$name"; return
    fi
  fi
  FAIL=$((FAIL + 1))
  printf 'FAIL %s cooldown=%s want=%s line[%s]=%s log=%s\n' \
    "$name" "$has_cooldown" "$want_cooldown" "$want_line" "$has_line" "$([[ -f "$warn" ]] && tr '\n' '|' < "$warn")"
}

l1_http_case l1-429-cooldown 429 yes
l1_http_case l1-500-no-cooldown 500 no

# L1 200 成功路徑：守 body 傳遞（stdout → 全域 L1_BODY 的改動）。
# 沒有這件，改壞 body 傳遞會讓判官全靜默而測試仍全綠。
l1_success_case() {
  local name="l1-200-nudge"
  local home="$TMP/home-$name"
  mkdir -p "$home/.claude/hooks" "$home/.claude/logs" "$home/.claude/hooks/state"
  cp "$KEYWORDS" "$home/.claude/hooks/claim-detect-keywords.json"

  local port
  port=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')
  python3 -c "
import http.server, json
VERDICT = json.dumps({'is_claim': True, 'reason': 'mock verdict.'})
PAYLOAD = json.dumps({'choices': [{'message': {'content': VERDICT}}]}).encode()
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
        self.wfile.write(PAYLOAD)
    def log_message(self, *a): pass
http.server.HTTPServer(('127.0.0.1', $port), H).serve_forever()
" &
  local pid=$!
  local ready=0 i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if python3 -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(0 if s.connect_ex(('127.0.0.1',$port))==0 else 1)"; then ready=1; break; fi
    sleep 0.2
  done
  if [[ "$ready" -ne 1 ]]; then
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
    FAIL=$((FAIL + 1)); printf 'FAIL %s (mock server 起不來)\n' "$name"; return
  fi

  local transcript="$TMP/$name.jsonl"
  jq -nc '{type:"user",isMeta:false,message:{content:"run"}}' > "$transcript"
  jq -nc '{type:"assistant",message:{content:[{type:"text",text:"全部完成。"}]}}' >> "$transcript"

  local output
  output=$(jq -nc --arg sid "test-$name" --arg path "$transcript" --arg m "全部完成。" \
    '{session_id:$sid,transcript_path:$path,last_assistant_message:$m,stop_hook_active:false}' \
    | HOME="$home" T1_RELAY_KEY="test-key" T1_L1_URL="http://127.0.0.1:$port/v1/chat/completions" \
      T1_L2_URL="http://127.0.0.1:$port/v1/chat/completions" "$HOOK" 2>/dev/null)
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null

  local ctx; ctx=$(jq -r '.hookSpecificOutput.additionalContext // ""' <<<"$output" 2>/dev/null)
  if [[ "$ctx" == *"T1 claim-detect v7"* && "$ctx" == *"mock verdict."* ]]; then
    PASS=$((PASS + 1)); printf 'PASS %s\n' "$name"; return
  fi
  FAIL=$((FAIL + 1)); printf 'FAIL %s output=%s\n' "$name" "$output"
}

l1_success_case


# === L3 Jev（2026-09-29）===
# 全部用本機 mock 端點：L1/L2 指到拒絕連線的 port 9，L3 指到 mock；不打任何真服務。
# 真的 Jev 端點由 llm.test.sh 的 l3-* 案例（live）覆蓋。
DEAD_URL="http://127.0.0.1:9/v1/chat/completions"
L3_KEY_VALUE="SECRET-L3-KEY-7f3a"
MOCK_PY="$TMP/mock.py"
cat > "$MOCK_PY" <<'PY'
import http.server, json, sys, time
port, status, body, delay, log = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], float(sys.argv[4]), sys.argv[5]
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with open(log, "a") as f:
            f.write(json.dumps({"path": self.path, "auth": self.headers.get("Authorization"), "body": raw.decode("utf-8")}) + "\n")
        time.sleep(delay)
        try:
            self.send_response(status); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body.encode())
        except Exception:
            pass
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
PY

MOCK_PORT=""; MOCK_PID=""
start_mock() {  # start_mock <status> <body> <delay> <reqlog>；結果放全域 MOCK_PORT / MOCK_PID
  MOCK_PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')
  python3 "$MOCK_PY" "$MOCK_PORT" "$1" "$2" "$3" "$4" &
  MOCK_PID=$!
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if python3 -c "import socket,sys;s=socket.socket();s.settimeout(0.3);sys.exit(0 if s.connect_ex(('127.0.0.1',$MOCK_PORT))==0 else 1)"; then return 0; fi
    sleep 0.2
  done
  return 1
}
stop_mock() { kill "$MOCK_PID" 2>/dev/null; wait "$MOCK_PID" 2>/dev/null; }

new_home() {
  local h="$TMP/home-$1"
  mkdir -p "$h/.claude/hooks" "$h/.claude/logs" "$h/.claude/hooks/state"
  cp "$KEYWORDS" "$h/.claude/hooks/claim-detect-keywords.json"
  printf '%s' "$h"
}

make_transcript() {  # make_transcript <path> <text>：零 tool 的 turn，G0 會放行進 LLM 層
  jq -nc '{type:"user",isMeta:false,message:{content:"run"}}' > "$1"
  jq -nc --arg m "$2" '{type:"assistant",message:{content:[{type:"text",text:$m}]}}' >> "$1"
}

L3_OUT=""; L3_HOME=""; L3_LOG=""; L3_ELAPSED=0
l3_exec() {  # l3_exec <name> <mock_status> <mock_body> <mock_delay> [ENV=VAL ...]（後面的 ENV 覆蓋預設）
  local name="$1" status="$2" body="$3" delay="$4"; shift 4
  L3_HOME=$(new_home "$name"); L3_LOG="$TMP/$name.reqlog"; : > "$L3_LOG"
  if ! start_mock "$status" "$body" "$delay" "$L3_LOG"; then
    stop_mock; L3_OUT="MOCK_FAILED"; return 1
  fi
  local transcript="$TMP/$name.jsonl"
  make_transcript "$transcript" "全部完成。"
  local t0; t0=$(date +%s)
  L3_OUT=$(jq -nc --arg sid "test-$name" --arg path "$transcript" --arg m "全部完成。" \
    '{session_id:$sid,transcript_path:$path,last_assistant_message:$m,stop_hook_active:false}' \
    | env HOME="$L3_HOME" T1_RELAY_KEY="test-key" T1_L1_URL="$DEAD_URL" T1_L2_URL="$DEAD_URL" \
        T1_L3_URL="http://127.0.0.1:$MOCK_PORT/v1/systemone" T1_L3_KEY="$L3_KEY_VALUE" "$@" "$HOOK" 2>/dev/null)
  L3_ELAPSED=$(( $(date +%s) - t0 ))
  stop_mock
}
req_count() { [[ -s "$1" ]] && wc -l < "$1" | tr -d ' ' || echo 0; }
warn_of() { cat "$1/.claude/hooks/T1-claim-detect.warnings.log" 2>/dev/null; }
trace_of() { cat "$1/.claude/hooks/T1-claim-detect.trace.log" 2>/dev/null; }
fires_of() { cat "$1/.claude/logs/T1-claim-detect-fires.jsonl" 2>/dev/null; }
assert_case() {  # assert_case <name> <cond exit status> <diagnostic>
  if [[ "$2" -eq 0 ]]; then PASS=$((PASS + 1)); printf 'PASS %s\n' "$1"
  else FAIL=$((FAIL + 1)); printf 'FAIL %s %s\n' "$1" "$3"; fi
}

# known-bad：L1、L2 都拒絕連線 → L3 被呼叫，nudge 帶 (L3)，fires 記 layer=L3，請求內容正確，key 不落檔
l3_exec l3-fallback-fire 200 '{"answers":{"is_claim":{"noul":0.91}}}' 0
ctx=$(jq -r '.hookSpecificOutput.additionalContext // ""' <<<"$L3_OUT" 2>/dev/null)
req=$(head -1 "$L3_LOG" 2>/dev/null)
ok=1
[[ "$ctx" == *"T1 claim-detect v7 (L3)"* ]] && ok=0
[[ $ok -eq 0 && "$(req_count "$L3_LOG")" == "1" ]] || ok=1
[[ $ok -eq 0 && "$(jq -r '.auth' <<<"$req")" == "Bearer $L3_KEY_VALUE" ]] || ok=1
[[ $ok -eq 0 && "$(jq -r '.path' <<<"$req")" == "/v1/systemone" ]] || ok=1
[[ $ok -eq 0 ]] && jq -e '.body | fromjson | .model=="jev-latest" and .state=="全部完成。" and .questions.is_claim.type=="noul" and (.questions.is_claim.instructions | contains("結案級宣告") and (contains("只輸出一行 JSON") | not) and (contains("# 輸出") | not))' <<<"$req" >/dev/null || ok=1
[[ $ok -eq 0 ]] && jq -e -s 'length==1 and .[0].layer=="L3" and .[0].source=="llm" and .[0].error_count==0' <<<"$(fires_of "$L3_HOME")" >/dev/null || ok=1
[[ $ok -eq 0 && "$(trace_of "$L3_HOME")" == *"layer=L3 is_claim=true"* ]] || ok=1
[[ $ok -eq 0 && "$(warn_of "$L3_HOME")" == *"L1 failed, trying L3"* ]] || ok=1
assert_case l3-fallback-fire "$ok" "ctx=$ctx reqs=$(req_count "$L3_LOG") fires=$(fires_of "$L3_HOME") trace=$(trace_of "$L3_HOME")"

# key 只在 Authorization header；任何 log／state 檔都不得含 key 原文
if grep -rqF "$L3_KEY_VALUE" "$L3_HOME/.claude" 2>/dev/null; then ok=1; else ok=0; fi
assert_case l3-key-not-logged "$ok" "key leaked into $L3_HOME/.claude"

# known-good：Noul 低於門檻 → 靜默，trace 記 is_claim=false，不寫 fires
l3_exec l3-below-threshold 200 '{"answers":{"is_claim":{"noul":0.30}}}' 0
ok=1
[[ -z "$L3_OUT" && "$(req_count "$L3_LOG")" == "1" && "$(trace_of "$L3_HOME")" == *"layer=L3 is_claim=false"* && -z "$(fires_of "$L3_HOME")" ]] && ok=0
assert_case l3-below-threshold "$ok" "out=$L3_OUT trace=$(trace_of "$L3_HOME") fires=$(fires_of "$L3_HOME")"

# 邊界：0.5 剛好算 fire（>=），0.4999 不算——鎖住線的位置
l3_exec l3-boundary-0.5 200 '{"answers":{"is_claim":{"noul":0.5}}}' 0
ok=1; [[ "$L3_OUT" == *"T1 claim-detect v7 (L3)"* ]] && ok=0
assert_case l3-boundary-0.5-fires "$ok" "out=$L3_OUT"
l3_exec l3-boundary-0.4999 200 '{"answers":{"is_claim":{"noul":0.4999}}}' 0
ok=1; [[ -z "$L3_OUT" && "$(trace_of "$L3_HOME")" == *"layer=L3 is_claim=false"* ]] && ok=0
assert_case l3-boundary-0.4999-silent "$ok" "out=$L3_OUT"

# L3 也失敗：非 200 / 缺欄位 / noul 非法 / 逾時 → 一律 silent、不寫 fires、warnings 記固定字串
l3_fail_case() {  # l3_fail_case <name> <status> <body> <delay> <expected error token> [ENV=VAL ...]
  local name="$1" status="$2" body="$3" delay="$4" token="$5"; shift 5
  l3_exec "$name" "$status" "$body" "$delay" "$@"
  local ok=1
  [[ -z "$L3_OUT" && -z "$(fires_of "$L3_HOME")" && "$(warn_of "$L3_HOME")" == *"L3 (jev) failed: $token"* && "$(warn_of "$L3_HOME")" == *"L1+L3 failed, silent"* ]] && ok=0
  assert_case "$name" "$ok" "out=$L3_OUT warn=$(warn_of "$L3_HOME" | tr '\n' '|') fires=$(fires_of "$L3_HOME")"
}
l3_fail_case l3-http-500 500 '{"error":"x"}' 0 http_500
l3_fail_case l3-http-401 401 '{"error":"bad key"}' 0 http_401
l3_fail_case l3-missing-answers 200 '{"answers":{}}' 0 KeyError
l3_fail_case l3-noul-out-of-range 200 '{"answers":{"is_claim":{"noul":1.5}}}' 0 noul_invalid
l3_fail_case l3-noul-string 200 '{"answers":{"is_claim":{"noul":"0.9"}}}' 0 noul_invalid
l3_fail_case l3-not-json 200 'not-json' 0 JSONDecodeError
l3_fail_case l3-timeout 200 '{"answers":{"is_claim":{"noul":0.9}}}' 6 timeout T1_L3_TIMEOUT=1
ok=1; [[ "$L3_ELAPSED" -lt 5 ]] && ok=0
assert_case l3-timeout-bounded "$ok" "elapsed=${L3_ELAPSED}s"

# 只在 L1 失敗時才走 L3：L1 成功，L3 mock 不得收到請求
l12_ok_case() {  # l12_ok_case <name> <which: l1>
  local name="$1" which="$2" home port pid transcript out
  home=$(new_home "$name")
  local l3log="$TMP/$name.l3log"; : > "$l3log"
  start_mock 200 '{"answers":{"is_claim":{"noul":0.95}}}' 0 "$l3log"; local l3port="$MOCK_PORT" l3pid="$MOCK_PID"
  local l12log="$TMP/$name.l12log"; : > "$l12log"
  local verdict; verdict=$(jq -nc '{choices:[{message:{content:"{\"is_claim\": true, \"reason\": \"mock l12.\"}"}}]}')
  start_mock 200 "$verdict" 0 "$l12log"; local l12port="$MOCK_PORT" l12pid="$MOCK_PID"
  transcript="$TMP/$name.jsonl"; make_transcript "$transcript" "全部完成。"
  local l1="$DEAD_URL" l2="$DEAD_URL" want="L2"
  [[ "$which" == "l1" ]] && { l1="http://127.0.0.1:$l12port/v1/chat/completions"; want="L1"; }
  [[ "$which" == "l2" ]] && l2="http://127.0.0.1:$l12port/v1/chat/completions"
  out=$(jq -nc --arg sid "test-$name" --arg path "$transcript" --arg m "全部完成。" \
    '{session_id:$sid,transcript_path:$path,last_assistant_message:$m,stop_hook_active:false}' \
    | env HOME="$home" T1_RELAY_KEY="test-key" T1_L1_URL="$l1" T1_L2_URL="$l2" T1_L2_MODEL="mock-l2" \
        T1_L3_URL="http://127.0.0.1:$l3port/v1/systemone" T1_L3_KEY="$L3_KEY_VALUE" "$HOOK" 2>/dev/null)
  kill "$l3pid" "$l12pid" 2>/dev/null; wait "$l3pid" "$l12pid" 2>/dev/null
  local ok=1
  [[ "$out" == *"T1 claim-detect v7 ($want)"* && "$(req_count "$l3log")" == "0" ]] && ok=0
  assert_case "$name" "$ok" "out=$out l3_reqs=$(req_count "$l3log")"
}
l12_ok_case l3-not-called-when-l1-ok l1

# 邊界（2026-10-01）：L1 慢過 1.5 秒逾時 → 不再等 Gemini、直接 L3；整支 3 秒內結束
l1_slow_case() {
  local name="l1-slow-falls-to-l3" home transcript out t0 elapsed
  home=$(new_home "$name")
  local l3log="$TMP/$name.l3log"; : > "$l3log"
  start_mock 200 '{"answers":{"is_claim":{"noul":0.95}}}' 0 "$l3log"; local l3port="$MOCK_PORT" l3pid="$MOCK_PID"
  local l1log="$TMP/$name.l1log"; : > "$l1log"
  local verdict; verdict=$(jq -nc '{choices:[{message:{content:"{\"is_claim\": true, \"reason\": \"slow l1.\"}"}}]}')
  start_mock 200 "$verdict" 4 "$l1log"; local l1port="$MOCK_PORT" l1pid="$MOCK_PID"
  transcript="$TMP/$name.jsonl"; make_transcript "$transcript" "全部完成。"
  t0=$(python3 -c 'import time;print(time.time())')
  out=$(jq -nc --arg sid "test-$name" --arg path "$transcript" --arg m "全部完成。" \
    '{session_id:$sid,transcript_path:$path,last_assistant_message:$m,stop_hook_active:false}' \
    | env HOME="$home" T1_RELAY_KEY="test-key" T1_L1_URL="http://127.0.0.1:$l1port/v1/chat/completions" \
        T1_L3_URL="http://127.0.0.1:$l3port/v1/systemone" T1_L3_KEY="$L3_KEY_VALUE" "$HOOK" 2>/dev/null)
  elapsed=$(python3 -c "import time;print(round(time.time()-$t0,2))")
  kill "$l3pid" "$l1pid" 2>/dev/null; wait "$l3pid" "$l1pid" 2>/dev/null
  local ok=1
  [[ "$out" == *"T1 claim-detect v7 (L3)"* && "$(req_count "$l1log")" == "1" && "$(req_count "$l3log")" == "1" ]] \
    && python3 -c "import sys;sys.exit(0 if $elapsed < 3.0 else 1)" && ok=0
  assert_case "$name" "$ok" "out=$out elapsed=${elapsed}s l1_reqs=$(req_count "$l1log") l3_reqs=$(req_count "$l3log")"
}
l1_slow_case

# kill switch 與 URL 覆寫保護：都不得送出請求
l3_exec l3-disabled 200 '{"answers":{"is_claim":{"noul":0.9}}}' 0 T1_L3_DISABLE=1
ok=1; [[ -z "$L3_OUT" && "$(req_count "$L3_LOG")" == "0" && "$(warn_of "$L3_HOME")" == *"L3 (jev) failed: disabled"* ]] && ok=0
assert_case l3-disabled "$ok" "out=$L3_OUT reqs=$(req_count "$L3_LOG")"
l3_exec l3-url-override-no-key 200 '{"answers":{"is_claim":{"noul":0.9}}}' 0 T1_L3_KEY=
ok=1; [[ -z "$L3_OUT" && "$(req_count "$L3_LOG")" == "0" && "$(warn_of "$L3_HOME")" == *"url_overridden_without_key"* ]] && ok=0
assert_case l3-url-override-no-key "$ok" "out=$L3_OUT reqs=$(req_count "$L3_LOG")"

# 自身生命週期／病態 log：fires 是 FIFO 或 symlink，且 L1/L2 都掛——整支在判官之前就放行，
# L3 不得被叫、不得卡住、不得寫到 symlink 指向的別處
patho_case() {  # patho_case <name> <fifo|symlink>
  local name="$1" kind="$2"
  local home; home=$(new_home "$name")
  local target="$home/.claude/logs/T1-claim-detect-fires.jsonl"
  local victim="$TMP/$name.victim"; printf 'untouched\n' > "$victim"
  if [[ "$kind" == "fifo" ]]; then mkfifo "$target"; else ln -s "$victim" "$target"; fi
  local l3log="$TMP/$name.l3log"; : > "$l3log"
  start_mock 200 '{"answers":{"is_claim":{"noul":0.95}}}' 0 "$l3log"
  local transcript="$TMP/$name.jsonl"; make_transcript "$transcript" "全部完成。"
  local outfile="$TMP/$name.out" statusfile="$TMP/$name.status"
  ( jq -nc --arg sid "test-$name" --arg path "$transcript" --arg m "全部完成。" \
      '{session_id:$sid,transcript_path:$path,last_assistant_message:$m,stop_hook_active:false}' \
      | env HOME="$home" T1_RELAY_KEY="test-key" T1_L1_URL="$DEAD_URL" T1_L2_URL="$DEAD_URL" \
          T1_L3_URL="http://127.0.0.1:$MOCK_PORT/v1/systemone" T1_L3_KEY="$L3_KEY_VALUE" "$HOOK" > "$outfile" 2>&1
    echo $? > "$statusfile" ) &
  local hp=$! i
  for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$hp" 2>/dev/null || break; sleep 1; done
  local ok=1
  if kill -0 "$hp" 2>/dev/null; then
    kill "$hp" 2>/dev/null
  elif [[ "$(cat "$statusfile")" == "0" && ! -s "$outfile" && "$(req_count "$l3log")" == "0" && "$(cat "$victim")" == "untouched" ]]; then
    ok=0
  fi
  stop_mock
  assert_case "$name" "$ok" "status=$(cat "$statusfile" 2>/dev/null) out=$(cat "$outfile" 2>/dev/null) l3_reqs=$(req_count "$l3log") victim=$(cat "$victim")"
}
patho_case l3-fires-fifo fifo
patho_case l3-fires-symlink symlink

# 反向斷言（2026-09-29）：舊的「L1+L2 failed, silent」措辭不得再出現——三層都掛時的 silent 行是 L1+L2+L3
if ! grep -qE 'L1\+L2 failed, silent|L1\+L2\+L3 failed|L1\+L2 failed, trying' "$HOOK"; then PASS=$((PASS + 1)); printf 'PASS no-stale-l1l2-silent-wording\n'
else FAIL=$((FAIL + 1)); printf 'FAIL no-stale-l1l2-silent-wording\n'; fi

printf '%s pass, %s fail\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
