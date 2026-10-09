#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/T1-claim-detect-local-first.test.sh（Layer C＋L3 mock）＋ T1-claim-detect-local-first.llm.test.sh（L1/L3 live）
# T1 claim-detect hook — v7 zero-tool gate + judge cascade
# Architecture: Layer C（claim × 未處理錯誤合取 → Stop additionalContext 提醒）→ G0 code gate（turn 內有任何 tool call → exit）
#   → L1 Groq qwen3.8-27b（經 CLIProxyAPI relay 127.0.0.1:8317）
#   → L3 Jev（jev-latest，Experiential /v1/systemone；只在 L1 失敗時才呼叫）→ silent
# 只有零 tool 的 turn 進 LLM、LLM 只判「是不是對自己工作的結案級宣告」（prompt v7 的判準段：L1 整份當 system prompt，L3 取「# 輸出」之前的判準段＋一個 Noul 問句）
# L3 Jev 直連 Experiential、不經 relay，所以 relay 掛掉時 L3 仍可用。
#
# === Layer C 注入：2026-09-17 降為 detect-only，2026-09-24 恢復（使用者拍板）===
# 恢復依據（trial review 對照研究，逐筆判定 180 筆、opus 判官）：有提醒期 149 次開火中真漏洞 4 次，
#   4 次都在提醒後、使用者開口前被自己補上（2 次改變了建議或結論）；其餘 145 次錯誤當下已處理。
#   代價：約每天 3 次，被提醒後的回應中位數約 86 字，78% 不呼叫工具。
# 別再嘗試「改準再注入」：規則式過濾與 Stop 當下的外部判官（Groq qwen、Gemini Flash）都 0/4——
#   真漏洞的錯誤後面同工具都有成功呼叫，只看步驟清單分不出成功的是不是同一件事；
#   能對帳的是有完整上下文、被提醒後回頭看的主模型本身。
#   研究紀錄：~/Desktop/projects/.claude/trials/review-evidence/2026-09-24-d3270f3c.md（第七題）
# 2026-09-24 晚提醒文字改為「全部不影響時一句帶過、只有已修／未修才展開」：判定不動、召回靠主模型回頭看的動作，
#   縮的是被提醒後的對帳段（原中位數約 86 字）。窄規則再測一次仍切不開（exit 1 無錯誤字眼型會濾掉真漏洞 P132 的收據）。
# 9/17 降級所用的「12.0% vs 13.2%」比較早已撤回（對照組是零工具回應、母體不可比，指標也不對位）；
#   fires.jsonl 中 source=conjunction-detect 的列是 detect-only 期間（09-17～09-24）的紀錄。
# L1 失敗（timeout / 非 200 / parse 失敗 / cooldown 中）才走 L3；L1 撞 429 進 30min cooldown、413（單發過大）不 cooldown 直接退 L3
# ⚠️ 上面這句在 2026-09-17 之前是**失效的**：狀態碼經 `return "$http_code"` 傳出被 bash 截成低 8 位
#    （429→173、413→157），429 判定從不成立，cooldown 自本 hook 上線起從未觸發過。
#    修法與兩個必守不變量見 call_l1_relay 上方註解；回歸測試 l1-429-cooldown / l1-500-no-cooldown / l1-200-nudge。
#
# === 換判官紀錄 ===
# 2026-07-06 → 08-30：L1 = 本機 8B、L2 = Groq qwen3.6-27b 直連（GROQ_API_KEY）。
# 2026-08-30 → 09-02：L1 = Groq qwen3.8-27b（relay、8 key pool）、L2 = 本機 8B。
# 2026-09-02 起：L1 = Groq qwen3.8-27b、L2 = Gemini 3.7 Flash，兩者皆走 relay；prompt v7 byte 不動。
# 2026-09-03 起：L2 版號改由 model-routing.env 的 GEMINI_FLASH_MODEL 統一指定。
# 2026-09-29 起：加 L3 = Jev（使用者拍板：所有 session 都可以送 Jev，不分個人或公司）。L1/L2 行為與 prompt 不動，
#   L3 只在兩層都失敗時才走；判定結果接到與 L1/L2 相同的下游（fires.jsonl 的 layer 記 "L3"、trace 記 layer=L3）。
#   L3 題目＝~/Desktop/projects/jev-hook-backtest 的 B 臂（v7 判準段原文＋一個 Noul 問句），門檻 Noul >= 0.5。
#   L3 的 precision／recall 未在本 hook 的 L1/L2 基準上驗證；它是「前兩層都掛時不讓整回合無 nudge」的最後一層，不是取代。
# 2026-10-01 起：拿掉 L2 Gemini，L1、L3 逾時都改 1.5 秒（使用者拍板：Stop 每輪都跑，只留 Groq 與 Jev）。
#   依據：近 7 天 Groq 成功 335 次，整支 hook p50 615ms／p95 1,074ms，其中 12 次（約 3.6%）Groq 超過 1.5 秒，改後這些會改由 L3 判；
#   L2 近 7 天只成功 2 次、每次整支約 14 秒。L3 從加入到改動前線上 0 次，判得準不準仍未驗。層名 L3 保留不改號，舊 log 與 fires 才對得起來。
# 27B 與 8B 比較依據：hook-llm-bench docs/T1-bench-round4-v7-judge-swap-2026-08-30.md。
# Gemini 切換依據：Rapid-MLX 退役；同日用 production prompt 實測 gemini-3.7-flash-high 回合法 JSON。
#
# === Threat model（gate-authoring #0）===
# 提示型 hook：只注入 nudge、不 block。判官全掛、parse 失敗、log 目標病態 → 一律 exit 0 放行（寧漏勿卡）。
# 不承諾：L1 經 CLIProxyAPI relay；relay 或上游 Groq 掛掉時由 L3 接手。
#   L3 Jev 直連 Experiential、不經 relay，所以 relay 掛掉時 L3 仍可用；兩層皆掛（含 Keychain 取不到 experiential-api-key、
#   Experiential 端點掛／逾時／回非法結構）則整回合無 nudge，只留 warnings.log 一到兩行。
#   不承諾 1.5 秒逾時下的判定覆蓋率：Groq 或 Jev 偶爾慢過 1.5 秒時，該回合改由下一層判或安靜放行。
#   不承諾 L3 判得跟 L1/L2 一樣準（Noul 機率判定、無 reason 文字，nudge 內只帶機率）；不承諾 L3 的可用率：它依賴外部服務與本機 Keychain。
#   資料邊界：L3 會把 assistant 訊息前 20000 字元送到 Experiential（使用者 2026-09-29 拍板不分個人或公司 session；Groq／Gemini 同樣是外部服務）。
#   key 只放在程式變數／子程序環境，不印出、不寫進任何 log；T1_L3_URL 被覆寫時不讀 Keychain（須另給 T1_L3_KEY），避免真 key 被送到測試端點。
#
# === Surface 四分表（gate-authoring #1）===
# Locked:           本檔 + T1-system-prompt-v7.txt（改動走 llm.test.sh 回歸 + ~/.claude commit）
# Editable:         Keychain 的 experiential-api-key（缺時 L3 fail-open 停用）
# Append-only:      T1-claim-detect.trace.log / .warnings.log / logs/T1-claim-detect-fires.jsonl / conjunction-audit.jsonl
# Human-controlled: settings.json Stop 段註冊（recovery = 移除該行或保留 fable-gate 前綴）、cooldown 檔可手刪；
#                   T1_L3_DISABLE=1 只關 L3（其餘不動）
#
# === 盲區場景表（gate-authoring #4；提示型故「繞過」= 量測盲區）===
# 1. relay 鏈壅塞或 Groq 慢時延遲推過 1.5s → L1 timeout → 退 L3
# 2. 單發超過 Groq 8K TPM（prompt ~1.3K tok + 超長 turn）→ 413 → 退 L3、不 cooldown
# 3. 判官回非 JSON → parse 失敗 → 退 L3；L3 也失敗 → silent + warning
# 4. keys.env 缺 CLIPROXY_KEY_CC → L1 跳過、直接 L3
# 5. （2026-10-01 前的 L2 Gemini 與 model-routing.env 依賴已移除）
# 6. log 目標是 symlink / FIFO / 非 regular → 整支放行不寫（FIFO 無人讀會 block Stop hook）；此守衛在任何判官呼叫之前，所以 L3 也不會在病態 log 下被叫
# 7. Keychain 取不到 experiential-api-key → L3 跳過（warnings.log 一行）；不 fallback 到別處找 key
# 8. Experiential 回 200 但缺 answers.is_claim.noul／noul 非 0–1 數字 → 視為失敗（silent + warning），不當成 is_claim=false 記 trace
# 9. 兩層最壞延遲約 1.5+1.5=3s（curl／urllib 的連線與讀取各自計時，可能略超），Stop 註冊 timeout 30s；再加任一層 timeout 前先重算
set -uo pipefail

# === Paths ===
HOOK_DIR="$HOME/.claude/hooks"
STATE_DIR="$HOOK_DIR/state"
WARN_LOG="$HOOK_DIR/T1-claim-detect.warnings.log"
TRACE_LOG="$HOOK_DIR/T1-claim-detect.trace.log"
PROMPT_LOCAL="$(dirname "$0")/T1-system-prompt-v7.txt"
mkdir -p "$STATE_DIR"

COOLDOWN_L1="$STATE_DIR/T1-L1-cooldown"
COOLDOWN_SECONDS=1800   # 30 min

# L1: Groq qwen3.8-27b via CLIProxyAPI relay（→ LiteLLM :8000 key pool → Groq）
L1_URL="${T1_L1_URL:-http://127.0.0.1:8317/v1/chat/completions}"
L1_MODEL="groq-qwen-3.8-27b"
L1_TIMEOUT=1.5
# L3: Jev（Experiential /v1/systemone）。直連、不經 relay、不用 RELAY_KEY；key 來自 Keychain experiential-api-key。
L3_URL="${T1_L3_URL:-https://api.experientiallabs.ai/v1/systemone}"
L3_DEFAULT_URL="https://api.experientiallabs.ai/v1/systemone"
L3_MODEL="jev-latest"
L3_TIMEOUT="${T1_L3_TIMEOUT:-1.5}"
L3_STATE_CHARS=20000
L3_THRESHOLD="0.5"
L3_QUESTION="問題：這段輸出是不是對自己工作的結案級宣告？"

# relay key：keys.env 的 CLIPROXY_KEY_CC（T1_RELAY_KEY 供測試覆寫）
RELAY_KEY="${T1_RELAY_KEY:-}"
if [[ -z "$RELAY_KEY" && -f "$HOME/.cli-proxy-api/keys.env" ]]; then
  RELAY_KEY=$(grep -E '^CLIPROXY_KEY_CC=' "$HOME/.cli-proxy-api/keys.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"')
fi

# log 目標病態守衛：symlink / FIFO / 非 regular → 整支放行不寫（FIFO 無人讀會 block Stop hook）
for target in "$WARN_LOG" "$TRACE_LOG" "$HOME/.claude/logs/T1-claim-detect-fires.jsonl" "$HOME/.claude/logs/T1-claim-detect-conjunction-audit.jsonl"; do
  if [[ -e "$target" || -L "$target" ]]; then
    if [[ -L "$target" || ! -f "$target" ]]; then
      exit 0
    fi
  fi
done

# === Read stdin ===
INPUT=$(cat)

# === Layer 0a: anti-loop gate (CC built-in)===
if [[ "$(jq -r '.stop_hook_active // false' <<<"$INPUT")" == "true" ]]; then
  exit 0
fi

# === Layer 0b: skip empty / trivial messages ===
TEXT=$(jq -r '.last_assistant_message // ""' <<<"$INPUT")
if [[ -z "$TEXT" || ${#TEXT} -lt 3 ]]; then
  exit 0
fi

# === Transcript path (shared by conjunction gate + G0) ===
# transcript 缺失 / parse 不出來 → fail-closed silent（寧可漏、不誤吵）
TRANSCRIPT=$(jq -r '.transcript_path // ""' <<<"$INPUT")
if [[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]]; then
  echo "$(date -Iseconds) G0: transcript missing, silent" >> "$WARN_LOG"
  exit 0
fi

# === Fire ledger helper（只在開火時 append，非開火回合一行都不寫）===
FIRES_LOG="$HOME/.claude/logs/T1-claim-detect-fires.jsonl"
log_fire() {
  local source="$1" layer="$2" error_count="$3" error_tools_json="$4"
  local raw_count="${5:-$error_count}" open_count="${6:-$error_count}"
  local disclosed_count="${7:-0}" retry_candidate_count="${8:-0}"
  mkdir -p "$(dirname "$FIRES_LOG")" 2>/dev/null || return 0
  jq -nc \
    --arg ts "$(date -Iseconds)" \
    --arg sid "$(jq -r '.session_id // ""' <<<"$INPUT" 2>/dev/null)" \
    --arg source "$source" \
    --arg layer "$layer" \
    --arg claim "$(printf '%s' "${TEXT:0:120}")" \
    --argjson ec "$error_count" \
    --argjson et "$error_tools_json" \
    --argjson raw "$raw_count" \
    --argjson open "$open_count" \
    --argjson disclosed "$disclosed_count" \
    --argjson retry "$retry_candidate_count" \
    '{ts:$ts, session_id:$sid, source:$source, layer:$layer, claim_120:$claim, error_count:$ec, error_tools:$et, raw_error_count:$raw, open_error_count:$open, disclosed_count:$disclosed, retry_candidate_count:$retry}' \
    >> "$FIRES_LOG" 2>/dev/null || true
}

CONJ_AUDIT_LOG="$HOME/.claude/logs/T1-claim-detect-conjunction-audit.jsonl"
log_conjunction_audit() {
  local raw_count="$1" open_count="$2" disclosed_count="$3" retry_candidate_count="$4" fired="$5"
  mkdir -p "$(dirname "$CONJ_AUDIT_LOG")" 2>/dev/null || return 0
  touch "$CONJ_AUDIT_LOG" 2>/dev/null || return 0
  chmod 600 "$CONJ_AUDIT_LOG" 2>/dev/null || true
  jq -nc \
    --arg ts "$(date -Iseconds)" \
    --arg sid "$(jq -r '.session_id // ""' <<<"$INPUT" 2>/dev/null)" \
    --argjson raw "$raw_count" \
    --argjson open "$open_count" \
    --argjson disclosed "$disclosed_count" \
    --argjson retry "$retry_candidate_count" \
    --argjson fired "$fired" \
    '{ts:$ts, session_id:$sid, raw_error_count:$raw, open_error_count:$open, disclosed_count:$disclosed, retry_candidate_count:$retry, fired:$fired}' \
    >> "$CONJ_AUDIT_LOG" 2>/dev/null || true
}

# === Layer C: claim × unhandled-error conjunction gate ===
# 置於 G0 之前：G0 對有 tool call 的 turn 直接 exit，而合取場景正是「有 tool call + 有錯誤 + 有宣稱」
# error 數 = 0 → 落回既有流程（G0 → L1 → L3），行為與改動前完全相同
CONJ_ERRORS=$(tail -c 800000 "$TRANSCRIPT" | python3 -c '
import json, os, re, sys

NOISE_RE = re.compile("|".join([
    r"BLOCKED by dcg",
    r"blocked by permission rules",
    r"ask the user for explicit permission",
    r"user doesn.t want to proceed with this tool use",
    r"tool use was rejected",
    r"Request interrupted",
    r"\[Request interrupted by user\]",
]), re.I)
STOPWORDS = {
    "bash", "true", "false", "python", "python3", "node", "unknown", "error",
    "command", "tool", "result", "file", "users", "home", "tmp", "private",
    "importerror", "syntaxerror", "nameerror", "exit", "code", "write", "read",
}

def body_text(body):
    if isinstance(body, list):
        return " ".join(
            item.get("text", "")
            for item in body
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return body if isinstance(body, str) else str(body)

def error_class(body, tool):
    lowered = body.lower()
    if "file has not been read yet" in lowered:
        return "write_requires_read"
    if re.search(r"blocked|denied|rejected|not allowed|攔截|拒絕", lowered):
        return "blocked"
    if tool == "Agent" and re.search(r"routing-gate|停用|改派", lowered):
        return "blocked"
    if re.search(r"timed? out|timeout|逾時|超時", lowered):
        return "timeout"
    if re.search(r"no such file|not found|cannot find|no matches found|找不到|不存在", lowered):
        return "missing"
    if re.search(r"exit code|command failed|syntaxerror|importerror|nameerror|unbound variable", lowered):
        return "command_exit"
    return "generic"

def anchor_candidates(value):
    values = []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(anchor_candidates(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(anchor_candidates(item))
    elif isinstance(value, str):
        values.append(value)
    return values

def anchor_sources(input_data):
    if not isinstance(input_data, dict):
        return anchor_candidates(input_data)
    priority = ["subagent_type", "file_path", "path", "command", "query", "symbol", "repo"]
    values = []
    for key in priority:
        if key in input_data:
            values.extend(anchor_candidates(input_data[key]))
    for key, value in input_data.items():
        if key not in priority:
            values.extend(anchor_candidates(value))
    return values

def anchors_for(input_data):
    anchors = []
    for raw in anchor_sources(input_data):
        for token in re.findall(r"[\w./-]{4,96}", raw, re.UNICODE):
            candidate = os.path.basename(token.rstrip("/")) if "/" in token else token
            candidate = candidate.strip(".`\"")
            lowered = candidate.lower()
            if lowered in STOPWORDS or candidate.isdigit() or len(candidate) < 4:
                continue
            if candidate not in anchors:
                anchors.append(candidate)
            if len(anchors) == 8:
                return anchors
    return anchors

def summary(body):
    return re.sub(r"\s+", " ", body).strip()[:160]

lines = sys.stdin.buffer.read().decode("utf-8", "replace").splitlines()
turn = []
for line in reversed(lines):
    try:
        event = json.loads(line)
    except Exception:
        continue
    if event.get("isSidechain"):
        continue
    event_type = event.get("type")
    if event_type == "user" and not event.get("isMeta"):
        content = (event.get("message") or {}).get("content")
        if isinstance(content, str):
            break
        if isinstance(content, list) and not any(
            isinstance(item, dict) and item.get("type") == "tool_result" for item in content
        ):
            break
    turn.append(event)
turn.reverse()

tool_uses = {}
for event in turn:
    if event.get("type") != "assistant":
        continue
    for item in (event.get("message") or {}).get("content") or []:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            tool_uses[item.get("id")] = {
                "tool": item.get("name") or "unknown",
                "input": item.get("input") or {},
            }

errors = []
tools = []
for event in turn:
    if event.get("type") != "user":
        continue
    content = (event.get("message") or {}).get("content")
    if not isinstance(content, list):
        continue
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_result":
            continue
        if item.get("is_error") is not True:
            continue
        body = body_text(item.get("content"))
        if NOISE_RE.search(body or ""):
            continue
        tool_use_id = item.get("tool_use_id") or "unknown"
        tool_use = tool_uses.get(tool_use_id, {"tool": "unknown", "input": {}})
        tool = tool_use["tool"]
        if tool not in tools:
            tools.append(tool)
        errors.append({
            "tool_use_id": tool_use_id,
            "tool": tool,
            "class": error_class(body, tool),
            "anchors": anchors_for(tool_use["input"]),
            "summary": summary(body),
        })

print(json.dumps({"count": len(errors), "tools": tools, "errors": errors}, ensure_ascii=False))
' 2>/dev/null)

[[ -z "$CONJ_ERRORS" ]] && CONJ_ERRORS='{"count":0,"tools":[]}'
CONJ_COUNT=$(jq -r '.count // 0' <<<"$CONJ_ERRORS" 2>/dev/null || echo 0)
[[ "$CONJ_COUNT" =~ ^[0-9]+$ ]] || CONJ_COUNT=0

if [[ "$CONJ_COUNT" -gt 0 ]]; then
  CLAIM_RE=$(jq -r '.patterns[] | select(.id == "completion_no_verify") | .regex' "$HOOK_DIR/claim-detect-keywords.json" 2>/dev/null)
  CLAIM_HIT=0
  if [[ -n "$CLAIM_RE" ]]; then
    if CLAIM_RE="$CLAIM_RE" TEXT="$TEXT" python3 -c '
import os, re, sys

claim_re = re.compile(os.environ["CLAIM_RE"], re.I)
text = os.environ["TEXT"]
negative = re.compile(r"(?:未|尚未|還沒|沒有|未能|沒能|不會)[^，。；;：:\n]{0,6}$|(?:not|never|is not|was not|isn.t|wasn.t)\s*$", re.I)
conditional = re.compile(r"(?:如果|若|是否|能否|可否|有沒有|不確定)[^，。；;：:\n]{0,12}$")
future = re.compile(r"(?:預計|待)[^，。；;：:\n]{0,8}$|(?<!已)將[^，。；;：:\n]{0,6}$|需要(?:再|先)?\s*$")
for match in claim_re.finditer(text):
    clause_start = max(
        text.rfind(separator, 0, match.start())
        for separator in ["\n", "。", "！", "？", ".", "!", "?", "，", ",", "；", ";", "：", ":"]
    ) + 1
    prefix = text[clause_start:match.start()]
    if prefix.lstrip().startswith(">"):
        continue
    nearby = prefix[-32:]
    if negative.search(nearby) or conditional.search(nearby) or future.search(nearby):
        continue
    sys.exit(0)
sys.exit(1)
' 2>/dev/null; then
      CLAIM_HIT=1
    fi
  fi
  if [[ "$CLAIM_HIT" == "1" ]]; then
    CONJ_STATUS=$(CONJ_ERRORS="$CONJ_ERRORS" TEXT="$TEXT" python3 -c '
import json, os, re

terms = {
    "write_requires_read": re.compile(r"未讀|沒讀|尚未讀|只讀|完整讀|先讀|read before|not been read", re.I),
    "blocked": re.compile(r"攔下|攔截|拒絕|未執行|沒執行|blocked|denied|rejected", re.I),
    "timeout": re.compile(r"逾時|超時|timeout|timed out", re.I),
    "missing": re.compile(r"找不到|不存在|缺少|no such|not found|no matches", re.I),
    "command_exit": re.compile(r"失敗|錯誤|exit|假綠", re.I),
    "generic": re.compile(r"失敗|錯誤|未成功|沒成功", re.I),
}

def segments(text):
    return [
        segment.strip()
        for segment in re.split(r"\n+|(?<=[。！？!?])|(?<=\.)\s+", text)
        if segment.strip()
    ]

def disclosed(error, text_segments):
    class_terms = terms.get(error.get("class"), terms["generic"])
    anchors = [anchor.lower() for anchor in error.get("anchors", []) if len(anchor) >= 4]
    if not anchors:
        return False
    for segment in text_segments:
        lowered = segment.lower()
        if class_terms.search(segment) and any(anchor in lowered for anchor in anchors):
            return True
    return False

data = json.loads(os.environ["CONJ_ERRORS"])
text_segments = segments(os.environ["TEXT"])
open_errors = []
disclosed_count = 0
for error in data.get("errors", []):
    if disclosed(error, text_segments):
        disclosed_count += 1
    else:
        open_errors.append(error)
print(json.dumps({
    "raw_count": data.get("count", 0),
    "open_count": len(open_errors),
    "disclosed_count": disclosed_count,
    "retry_candidate_count": 0,
    "open": open_errors,
}, ensure_ascii=False))
' 2>/dev/null)
    if [[ -z "$CONJ_STATUS" ]]; then
      CONJ_STATUS=$(jq -c '{raw_count:(.count // 0), open_count:(.count // 0), disclosed_count:0, retry_candidate_count:0, open:(.errors // [])}' <<<"$CONJ_ERRORS" 2>/dev/null)
    fi
    CONJ_OPEN_COUNT=$(jq -r '.open_count // 0' <<<"$CONJ_STATUS" 2>/dev/null || echo "$CONJ_COUNT")
    CONJ_DISCLOSED_COUNT=$(jq -r '.disclosed_count // 0' <<<"$CONJ_STATUS" 2>/dev/null || echo 0)
    CONJ_RETRY_COUNT=$(jq -r '.retry_candidate_count // 0' <<<"$CONJ_STATUS" 2>/dev/null || echo 0)
    if [[ "$CONJ_OPEN_COUNT" -gt 0 ]]; then
      log_conjunction_audit "$CONJ_COUNT" "$CONJ_OPEN_COUNT" "$CONJ_DISCLOSED_COUNT" "$CONJ_RETRY_COUNT" true
      CONJ_TOOLS_JSON=$(jq -c '[.open[].tool] | unique' <<<"$CONJ_STATUS" 2>/dev/null || echo '[]')
      CONJ_RECEIPTS=$(jq -r '.open | to_entries[] | "R\(.key + 1) \(.value.tool) #\(.value.tool_use_id[-6:]) — \(.value.summary)"' <<<"$CONJ_STATUS" 2>/dev/null)
      echo "$(date -Iseconds) layer=C is_claim=true raw_errors=$CONJ_COUNT open_errors=$CONJ_OPEN_COUNT disclosed=$CONJ_DISCLOSED_COUNT len=${#TEXT}" >> "$TRACE_LOG"
      log_fire "conjunction" "C" "$CONJ_OPEN_COUNT" "$CONJ_TOOLS_JSON" "$CONJ_COUNT" "$CONJ_OPEN_COUNT" "$CONJ_DISCLOSED_COUNT" "$CONJ_RETRY_COUNT"
      NUDGE_C=$(printf '%s\n\n%s' '⚠️ T1 claim-detect (合取 gate): 你剛宣告完成。回頭掃一眼下列錯誤收據，不回顧其他錯誤。全部都不影響完成宣稱時，只回一行「R1–Rn 皆不影響」，不逐列解釋。只有已修或未修才展開：已修指出後續成功證據，沒有證據就補一次最小驗證；未修則收窄或撤回宣稱。原回覆已交代的收據不重述。' "$CONJ_RECEIPTS")
      jq -nc --arg ctx "$NUDGE_C" '{
        hookSpecificOutput: {
          hookEventName: "Stop",
          additionalContext: $ctx
        }
      }'
      exit 0
    else
      log_conjunction_audit "$CONJ_COUNT" 0 "$CONJ_DISCLOSED_COUNT" "$CONJ_RETRY_COUNT" false
    fi
  fi
fi

# === Layer G0: zero-tool code gate (v7) ===
# turn 內有任何 tool call → 宣告至少可能有據、直接 exit（不叫 LLM）
HAS_TOOLS=$(tail -c 800000 "$TRANSCRIPT" | python3 -c '
import sys, json
lines = sys.stdin.buffer.read().decode("utf-8", "replace").splitlines()
for line in reversed(lines):
    try:
        e = json.loads(line)
    except Exception:
        continue
    if e.get("isSidechain"):
        continue
    t = e.get("type")
    if t == "assistant":
        for c in (e.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                print(1)
                sys.exit()
    elif t == "user" and not e.get("isMeta"):
        mc = (e.get("message") or {}).get("content")
        if isinstance(mc, str):
            break
        if isinstance(mc, list) and not any(
            isinstance(x, dict) and x.get("type") == "tool_result" for x in mc
        ):
            break
print(0)
' 2>/dev/null)
if [[ "$HAS_TOOLS" != "0" ]]; then
  echo "$(date -Iseconds) layer=G0 is_claim=false len=${#TEXT}" >> "$TRACE_LOG"
  exit 0
fi

# === Read prompt（v7、L1 整份用、L3 取判準段）===
if [[ ! -f "$PROMPT_LOCAL" ]]; then
  echo "$(date -Iseconds) v7 prompt missing: $PROMPT_LOCAL" >> "$WARN_LOG"
  exit 0
fi
SYSTEM_PROMPT=$(cat "$PROMPT_LOCAL")

# === Build user message ===
USER_MSG="分析以下 assistant 輸出（本回合零工具執行）：

\`\`\`
$TEXT
\`\`\`"

# === Cooldown helpers ===
in_cooldown() {
  local cooldown_file="$1"
  [[ ! -f "$cooldown_file" ]] && return 1
  local expiry now
  expiry=$(cat "$cooldown_file" 2>/dev/null)
  now=$(date +%s)
  [[ -z "$expiry" || "$now" -ge "$expiry" ]] && return 1
  return 0
}

write_cooldown() {
  local cooldown_file="$1"
  echo $(($(date +%s) + COOLDOWN_SECONDS)) > "$cooldown_file"
}

# === Parse JSON verdict from raw content ===
# Input: raw content string (possibly with code fence or noise)
# Output: echoes parsed JSON object, exit 0 if parsed; exit 1 if not
parse_verdict() {
  local content="$1"
  [[ -z "$content" ]] && return 1
  local clean json
  clean=$(echo "$content" | sed -E 's/^```(json)?$//; s/^```$//' | tr -d '\r')
  if json=$(echo "$clean" | jq -c . 2>/dev/null); then
    echo "$json"
    return 0
  fi
  # Fallback: grep first {...}
  if json=$(echo "$clean" | grep -oE '\{[^{}]*\}' | head -1 | jq -c . 2>/dev/null); then
    echo "$json"
    return 0
  fi
  return 1
}

# === 共用 payload（v7 prompt、temperature 0 釘定性）===
build_payload() {
  local model="$1"
  jq -nc \
    --arg sys "$SYSTEM_PROMPT" \
    --arg msg "$USER_MSG" \
    --arg model "$model" \
    '{
      model: $model,
      messages: [
        {role: "system", content: $sys},
        {role: "user",   content: $msg}
      ],
      max_tokens: 300,
      temperature: 0,
      stream: false
    }'
}

# === L1: Groq qwen3.8-27b via relay ===
# 回傳值：0 = 200，body 在全域 L1_BODY；1 = 任何失敗。
# HTTP 狀態碼經全域 L1_HTTP 傳出（空字串 = 沒送出請求或 curl 層失敗）。
# ⚠️ 兩個都不要改回去：
#  (1) 不要用 `return "$http_code"` —— bash 的 return 只保留低 8 位，429 會變成 173，
#      導致 429 判定永遠不成立、cooldown 分支從不觸發（warnings.log 2026-06-20 那 8 筆
#      `L2 http=173` 就是當時 Groq 在 L2 位置撞 429 的殘骸）。
#  (2) 不要用 `L1_RAW=$(call_l1_relay)` 取 body —— 命令替換在 subshell 執行，
#      函式內對 L1_HTTP 的賦值不會回到父 shell，429 分支一樣永遠收不到狀態碼。
#      必須直接 `if call_l1_relay; then` 並從 L1_BODY 讀 body。
# 兩者皆 2026-09-17 修，回歸測試 l1-429-cooldown / l1-500-no-cooldown。
L1_HTTP=""
L1_BODY=""
call_l1_relay() {
  L1_HTTP=""
  L1_BODY=""
  if [[ -z "$RELAY_KEY" ]]; then
    echo "$(date -Iseconds) CLIPROXY_KEY_CC unset, L1 skip" >> "$WARN_LOG"
    return 1
  fi
  local response http_code
  response=$(curl -sS --max-time "$L1_TIMEOUT" -w $'\n%{http_code}' \
    "$L1_URL" \
    -H "Authorization: Bearer $RELAY_KEY" \
    -H "Content-Type: application/json" \
    -d "$(build_payload "$L1_MODEL")" 2>/dev/null)
  http_code=$(tail -n1 <<<"$response")
  L1_BODY=$(sed '$d' <<<"$response")
  [[ "$http_code" =~ ^[0-9]{3}$ ]] && L1_HTTP="$http_code"
  [[ "$http_code" == "200" ]] && return 0
  return 1
}

# === L3: Jev via Experiential /v1/systemone（直連、不經 relay）===
# 成功時 stdout 印 {"ok":true,"is_claim":bool,"reason":str}；任何失敗印 {"ok":false,"error":"<固定字串>"}。
# error 只放例外類別名／HTTP 碼，不放例外訊息，避免 key 或 URL 進 warnings.log。
# 題目＝v7 判準段（「# 輸出」之前）原文＋一個 Noul 問句，與 jev-hook-backtest 的 B 臂同。門檻 Noul >= L3_THRESHOLD。
# 回應缺 answers.is_claim.noul、或 noul 不是 0–1 的數字 → 視為失敗，不當成 is_claim=false。
call_l3_jev() {
  [[ "${T1_L3_DISABLE:-0}" == "1" ]] && { echo '{"ok":false,"error":"disabled"}'; return 0; }
  local key="${T1_L3_KEY:-}"
  if [[ -z "$key" ]]; then
    if [[ "$L3_URL" != "$L3_DEFAULT_URL" ]]; then
      echo '{"ok":false,"error":"url_overridden_without_key"}'
      return 0
    fi
    key=$(security find-generic-password -s experiential-api-key -w 2>/dev/null) || key=""
    if [[ -z "$key" ]]; then
      echo '{"ok":false,"error":"keychain_key_missing"}'
      return 0
    fi
  fi
  printf '%s' "$TEXT" | JEV_KEY="$key" JEV_URL="$L3_URL" JEV_MODEL="$L3_MODEL" JEV_TIMEOUT="$L3_TIMEOUT" \
    JEV_PROMPT_FILE="$PROMPT_LOCAL" JEV_QUESTION="$L3_QUESTION" JEV_STATE_CHARS="$L3_STATE_CHARS" \
    JEV_THRESHOLD="$L3_THRESHOLD" python3 -c '
import json, os, socket, sys, urllib.error, urllib.request

def out(obj):
    print(json.dumps(obj, ensure_ascii=False))

try:
    text = sys.stdin.read()[: int(os.environ["JEV_STATE_CHARS"])]
    prompt = open(os.environ["JEV_PROMPT_FILE"], encoding="utf-8").read()
    cut = prompt.find("# 輸出")
    if cut < 0:
        out({"ok": False, "error": "rubric_marker_missing"})
        sys.exit(0)
    rubric = prompt[:cut].rstrip()
    body = {"model": os.environ["JEV_MODEL"], "state": text, "questions": {
        "is_claim": {"type": "noul", "instructions": rubric + "\n\n" + os.environ["JEV_QUESTION"]}}}
    req = urllib.request.Request(os.environ["JEV_URL"], json.dumps(body).encode("utf-8"), {
        "Authorization": "Bearer " + os.environ["JEV_KEY"], "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=float(os.environ["JEV_TIMEOUT"])) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    p = data["answers"]["is_claim"]["noul"]
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
        out({"ok": False, "error": "noul_invalid"})
        sys.exit(0)
    fire = p >= float(os.environ["JEV_THRESHOLD"])
    out({"ok": True, "is_claim": fire, "reason": "Jev 判定機率 %.2f。" % p})
except urllib.error.HTTPError as e:
    out({"ok": False, "error": "http_%d" % e.code})
except (TimeoutError, socket.timeout):
    out({"ok": False, "error": "timeout"})
except Exception as e:
    out({"ok": False, "error": type(e).__name__})
' 2>/dev/null
}

# === Cascade ===
RESPONSE=""
LAYER_USED=""

# L1: Groq 27B（cooldown 中直接跳過）
if ! in_cooldown "$COOLDOWN_L1"; then
  if call_l1_relay; then
    L1_CONTENT=$(jq -r '.choices[0].message.content // ""' <<<"$L1_BODY" 2>/dev/null || echo "")
    if [[ -n "$L1_CONTENT" ]]; then
      if L1_JSON=$(parse_verdict "$L1_CONTENT"); then
        RESPONSE="$L1_JSON"
        LAYER_USED="L1"
      fi
    fi
  else
    if [[ "$L1_HTTP" == "429" ]]; then
      write_cooldown "$COOLDOWN_L1"
      echo "$(date -Iseconds) L1 (groq-qwen-3.8-27b via relay) 429 quota, cooldown 30min" >> "$WARN_LOG"
    elif [[ -n "$L1_HTTP" ]]; then
      echo "$(date -Iseconds) L1 http=$L1_HTTP" >> "$WARN_LOG"
    fi
  fi
fi

# L3: Jev（only if L1 failed / cooldown；不經 relay，所以 relay 掛掉時仍可用）
if [[ -z "$RESPONSE" ]]; then
  echo "$(date -Iseconds) L1 failed, trying L3" >> "$WARN_LOG"
  L3_RAW=$(call_l3_jev || true)
  if [[ "$(jq -r '.ok // false' <<<"$L3_RAW" 2>/dev/null)" == "true" ]]; then
    RESPONSE=$(jq -c '{is_claim, reason}' <<<"$L3_RAW" 2>/dev/null)
    LAYER_USED="L3"
  else
    echo "$(date -Iseconds) L3 (jev) failed: $(jq -r '.error // "no_output"' <<<"$L3_RAW" 2>/dev/null || echo no_output)" >> "$WARN_LOG"
  fi
fi

# === Silent if all layers failed ===
if [[ -z "$RESPONSE" ]]; then
  echo "$(date -Iseconds) L1+L3 failed, silent" >> "$WARN_LOG"
  exit 0
fi

# === Extract verdict ===
IS_CLAIM=$(jq -r '.is_claim // false' <<<"$RESPONSE" 2>/dev/null)
REASON=$(jq -r '.reason // ""' <<<"$RESPONSE" 2>/dev/null)

# === Trace log every decision ===
echo "$(date -Iseconds) layer=$LAYER_USED is_claim=$IS_CLAIM len=${#TEXT}" >> "$TRACE_LOG"

if [[ "$IS_CLAIM" != "true" ]]; then
  exit 0
fi

# === Emit nudge via additionalContext (CC injects into next turn) ===
log_fire "llm" "$LAYER_USED" 0 '[]'

NUDGE="⚠️ T1 claim-detect v7 ($LAYER_USED): 本回合零工具執行、偵測到結案級宣告。${REASON} 補一個當場驗證（ls / grep / wc 枚舉輸出）把宣告變有據，或明確 escape（標「未驗證」「憑前輪結果」）。"

jq -nc --arg ctx "$NUDGE" '{
  hookSpecificOutput: {
    hookEventName: "Stop",
    additionalContext: $ctx
  }
}'
