#!/bin/bash
# websearch-parallel-enforce.sh
# Threat model: drift prevention for honest agents, not a security boundary. This
# literal matcher recognizes LCU navigation calls and retained OBU command shapes;
# it does not promise complete shell/JavaScript semantics and may match quoted code.
# LCU tickets require a non-error result, not proof that every SERP row was read.
# Locked: this hook and its fixtures. Editable: paired-search guidance. Append-only:
# the JSONL log. Human-controlled recovery: remove the WebSearch matcher in settings.json.
# Block WebSearch unless the same turn contains a same-query Google SERP ticket.
# Decision rationale: reference_search_tool_comparison_2026_05_10.md
# Why hook: advisory guidance can be forgotten; this preserves ticket accounting.

set -u
INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)

LOG_DIR="$HOME/.claude/hooks/state"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/websearch-parallel.log"

log() {
  printf '{"ts":"%s","tool":"%s","action":"%s"%s}\n' \
    "$(date -u +%FT%TZ)" "$TOOL_NAME" "$1" "$2" >> "$LOG"
}

[ "$TOOL_NAME" != "WebSearch" ] && exit 0

# Vendor-session bypass (2026-06-19): cc-vendor-bridge ccp-* functions export
# CC_VENDOR so hook can identify non-Anthropic sessions. The "WebSearch must pair
# with an OBU SERP" discipline is designed for main Claude sessions (Anthropic
# ranking quality concerns + Agent Chrome search results). Vendor
# sessions have their own cost-benefit profile (subscription prompt quota /
# different MCP availability) — don't impose Claude-shaped discipline on them.
# Main Claude session has CC_VENDOR unset.
[ -n "${CC_VENDOR:-}" ] && { log "exempt_vendor" ",\"vendor\":\"$CC_VENDOR\""; exit 0; }

[ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ] && { log "no_transcript" ""; exit 0; }

# Enforcement scope by agent_type (2026-06-01 trial review).
#   ""              = main session                    -> enforce (Claude can read-then-ignore a
#                                                        rule; the hook is the only hard layer)
#   parallel-search = dedicated paired-search agent   -> enforce (its whole job IS the SERP+WebSearch
#                                                        pair; hard-guarantee it never skips the SERP)
#   anything else   = fan-out subagent                -> exempt (forcing chrome on mass parallel
#                                                        search bloats the user's real browser with
#                                                        hundreds of tabs — see trial review verdict)
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
case "$AGENT_TYPE" in
  ""|parallel-search) ;;
  *) log "exempt_subagent" ""; exit 0 ;;
esac

# Subagent transcript redirect (2026-06-01 root-cause fix). Only fires for the
# parallel-search agent now (main session has empty agent_id; other subagents
# already exited above).
# For a subagent/workflow tool call, transcript_path is the MAIN session
# transcript, NOT the subagent's — so the pairing check reads the wrong file,
# never sees the subagent's google nav, and false-blocks every subagent
# WebSearch (this was the 98% block rate: 5325 subagent WS all read against main).
# The input carries agent_id; the subagent transcript lives under
# <main_transcript_without_.jsonl>/subagents/[workflows/wf_*/]agent-<agent_id>.jsonl.
# Redirect TRANSCRIPT there so nav/WebSearch pairing is evaluated against the
# subagent's own turn.
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
if [ -n "$AGENT_ID" ]; then
  SUB_BASE="${TRANSCRIPT%.jsonl}/subagents"
  SUB_TP="$SUB_BASE/agent-${AGENT_ID}.jsonl"
  [ -f "$SUB_TP" ] || SUB_TP=$(find "$SUB_BASE" -name "agent-${AGENT_ID}.jsonl" 2>/dev/null | head -1)
  [ -n "$SUB_TP" ] && [ -f "$SUB_TP" ] && TRANSCRIPT="$SUB_TP"
fi

# Scope: tool_use lines since the last user turn started.
# Why this scope: each user turn is one "research session" — nav and WebSearch
# count must balance (1:1) within the same turn. Cross-turn carry would let an
# earlier nav cover a later unrelated WebSearch.
#
# Why per-line grep: each tool_use is its own jsonl line (CC splits parallel
# tool_use blocks across lines, sharing message.id). grep -c on tool_use lines
# gives an accurate count.
#
# Why grep instead of jq: jq fails on invalid control chars in transcript;
# byte-level grep on the tool_use name field is robust.
#
# Why google.com/search filter on navigate: navigate to docs/github doesn't
# count as SERP cross-reference; only google search counts.
#
# Known false-negative: when nav and WebSearch are dispatched in the same
# assistant message (parallel), the message line is not yet written to
# transcript when PreToolUse fires for WebSearch — so nav looks missing and
# WebSearch is blocked. Workaround: emit nav in the message *before* the
# WebSearch message, not in the same parallel batch.
# Match real user prompts only (string content). CC wraps tool_result as
# user-role messages too, but those have array content — exclude them.
LAST_USER_LINE=$(grep -nE '"type":"user","message":\{"role":"user","content":"' "$TRANSCRIPT" | tail -1 | cut -d: -f1)
if [ -n "$LAST_USER_LINE" ]; then
  TURN=$(awk -v start="$LAST_USER_LINE" 'NR > start' "$TRANSCRIPT")
else
  TURN=$(cat "$TRANSCRIPT")
fi
CURRENT_WS_QUERY=$(echo "$INPUT" | jq -r '.tool_input.query // empty' 2>/dev/null)

# Per-query ticket model (2026-05-11 redesign — see git blame for old count-based logic):
# - Each nav to google.com/search?q=X grants one ticket for query X.
# - Each successful (non-blocked) WebSearch with query X consumes one X-ticket.
# - Blocked WS (tool_result contains "[search-parallel]") does NOT consume a ticket — retry-friendly.
# - Allow current WS only if remaining X-tickets >= 1.
# Rationale: "one round" = same-query nav + WS. Repeated same-query WS wastes quota
# (same results). User trigger: "重點是一輪完整搜尋要包含 webSearch 和 chrome".
DECISION=$(echo "$TURN" | CURRENT_Q="$CURRENT_WS_QUERY" python3 -c '
import json, sys, os, urllib.parse, re

def norm(q):
    return " ".join(urllib.parse.unquote(q.replace("+", " ")).lower().split()).strip()

current_q_norm = norm(os.environ["CURRENT_Q"])

def lcu_result_ok(block):
    if block.get("is_error"):
        return False
    content = block.get("content")
    if not content:
        return False
    if isinstance(content, str):
        if content.startswith(("Error:", "MCP error")):
            return False
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            return True
    if isinstance(content, dict):
        if content.get("isError"):
            return False
        result = content.get("result")
        if isinstance(result, dict) and result.get("isError"):
            return False
    return True

nav_queries = []
lcu_pending_queries = {}
bash_pending_queries = {}
ws_success_queries = []
ws_pending_q = None
ws_pending_id = None

for line in sys.stdin:
    try:
        d = json.loads(line)
        t = d.get("type")
        if t == "assistant":
            for c in d["message"]["content"]:
                if c.get("type") != "tool_use": continue
                name = c["name"]
                if name in ("mcp__open_browser_use__open_tab", "mcp__open_browser_use__navigate"):
                    url = c["input"].get("url", "")
                    parsed = urllib.parse.urlparse(url)
                    if parsed.netloc in ("google.com", "www.google.com") and parsed.path == "/search":
                        q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
                        if q: nav_queries.append(norm(q))
                elif name == "mcp__lcu__js":
                    code = c["input"].get("code", "")
                    queries = []
                    if re.search(r"(?:\.createBrowserTab|\.goto)\s*\(", code):
                        urls = re.findall(r"https://(?:www\.)?google\.com/search\?[^\s\"\x27\\]+", code)
                        for url in urls:
                            parsed = urllib.parse.urlparse(url)
                            q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
                            if q: queries.append(norm(q))
                    if queries and c.get("id"):
                        lcu_pending_queries[c["id"]] = queries
                elif name == "Bash":
                    command = c["input"].get("command", "")
                    queries = []
                    if "agent_browser_cli.py" in command and "open-tab" in command:
                        urls = re.findall(r"https://(?:www\.)?google\.com/search\?[^\s\"\x27\\]+", command)
                        for url in urls:
                            parsed = urllib.parse.urlparse(url)
                            q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
                            if q: queries.append(norm(q))
                    if queries and c.get("id"):
                        bash_pending_queries[c["id"]] = queries
                elif name == "WebSearch":
                    ws_pending_q = norm(c["input"].get("query", ""))
                    ws_pending_id = c.get("id")
        elif t == "user":
            content = d["message"]["content"]
            if isinstance(content, list):
                for c in content:
                    if c.get("type") != "tool_result":
                        continue
                    tool_use_id = c.get("tool_use_id")
                    if tool_use_id in lcu_pending_queries:
                        if lcu_result_ok(c):
                            nav_queries.extend(lcu_pending_queries[tool_use_id])
                        del lcu_pending_queries[tool_use_id]
                    if tool_use_id in bash_pending_queries:
                        payload = None
                        if not c.get("is_error") and isinstance(c.get("content"), str):
                            try:
                                payload = json.loads(c["content"])
                            except json.JSONDecodeError:
                                pass
                        steps = payload.get("steps") if isinstance(payload, dict) else None
                        if isinstance(steps, list) and any(
                            isinstance(step, dict) and step.get("action") == "open-tab"
                            for step in steps
                        ):
                            nav_queries.extend(bash_pending_queries[tool_use_id])
                        del bash_pending_queries[tool_use_id]
                    if ws_pending_q is not None and tool_use_id == ws_pending_id:
                        text = str(c.get("content", ""))
                        if "[search-parallel]" not in text:
                            ws_success_queries.append(ws_pending_q)
                        ws_pending_q = None
                        ws_pending_id = None
    except: pass

q_nav = nav_queries.count(current_q_norm)
q_ws_ok = ws_success_queries.count(current_q_norm)
remaining = q_nav - q_ws_ok
print(f"ok|{q_nav}|{q_ws_ok}" if remaining >= 1 else f"block|{q_nav}|{q_ws_ok}")
')

VERDICT=$(echo "$DECISION" | cut -d'|' -f1)
Q_NAV=$(echo "$DECISION" | cut -d'|' -f2)
Q_WS_OK=$(echo "$DECISION" | cut -d'|' -f3)

if [[ "$VERDICT" == "ok" ]]; then
  log "ok" ",\"scope\":\"ticket_query_match\",\"q_nav\":${Q_NAV:-0},\"q_ws_ok\":${Q_WS_OK:-0}"
  exit 0
fi

ENCODED=$(echo "$CURRENT_WS_QUERY" | python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.stdin.read().strip()))" 2>/dev/null)

log "block" ",\"q_nav\":${Q_NAV:-0},\"q_ws_ok\":${Q_WS_OK:-0}"

# Build JSON safely via jq to handle quotes/special chars in query.
REASON="[search-parallel] 例外條款（先看這條）：使用者明確說「只跑 WebSearch」「不要開 browser」可只 call WebSearch，但需在 response 開頭明示原因。非例外情況：沒有可用的 SERP ticket 配對 query='${CURRENT_WS_QUERY}'（同 query nav=${Q_NAV:-0}, 已成功 WS=${Q_WS_OK:-0}）。先用正式 LCU MCP js 的 createBrowserTab／goto 實際導航並讀回 https://www.google.com/search?q=${ENCODED}，操作碼保留該完整 URL 字面值，取得非錯誤回件後再 call WebSearch。同 query 重複 WebSearch 請先補新 ticket；不要為補 ticket 啟動已退出預設路徑的 OBU／Agent Chrome。背景：reference_search_tool_comparison_2026_05_10.md"

jq -nc --arg reason "$REASON" '{decision: "block", reason: $reason}'
