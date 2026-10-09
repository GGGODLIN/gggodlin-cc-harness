#!/bin/bash
# Stop hook — Phase 1 (silent log) of verify rule機械化計畫
# 偵測本 turn 有沒有「需要 verify」的動作 + assistant 有沒有給「預期/實際/匹配」三句格式
# 不 nudge 不擋、純 append jsonl。
#
# Disable: touch ~/.claude/hooks/.verify-audit-disabled
# Log:     ~/.claude/logs/verify-audit.jsonl
#
# Stop hook input (stdin JSON): {session_id, transcript_path, stop_hook_active}
# Output: 一律 exit 0 silent

set -uo pipefail

SENTINEL="$HOME/.claude/hooks/.verify-audit-disabled"
[ -f "$SENTINEL" ] && exit 0

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)

[ -z "$SESSION_ID" ] && exit 0
[ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ] && exit 0
[ "$STOP_HOOK_ACTIVE" = "true" ] && exit 0
[ -n "${CC_VENDOR:-}" ] && exit 0

LOG="$HOME/.claude/logs/verify-audit.jsonl"

export TRANSCRIPT SESSION_ID LOG
python3 <<'PY' 2>/dev/null || exit 0
import json
import os
import re
import sys
from datetime import datetime, timezone

TRANSCRIPT = os.environ.get("TRANSCRIPT", "")
SESSION_ID = os.environ.get("SESSION_ID", "")
LOG = os.environ.get("LOG", "")

if not TRANSCRIPT or not LOG:
    sys.exit(0)

# 讀 jsonl，找最後一個 user message 之後的 events = 「本 turn」
events = []
try:
    with open(TRANSCRIPT) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass
except Exception:
    sys.exit(0)

# 找最後一個 type=user 且 content 非 tool_result 的 index（真實 user prompt，不是 tool feedback）
turn_start_idx = 0
for i in range(len(events) - 1, -1, -1):
    obj = events[i]
    if obj.get("type") != "user":
        continue
    msg = obj.get("message", {})
    content = msg.get("content")
    is_tool_result = False
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_result":
                is_tool_result = True
                break
    if not is_tool_result:
        turn_start_idx = i
        break

turn_events = events[turn_start_idx:]

# 偵測 trigger tools
trigger_tools = []
edit_count = 0
write_files = []

for obj in turn_events:
    if obj.get("type") != "assistant":
        continue
    msg = obj.get("message", {})
    content = msg.get("content")
    if not isinstance(content, list):
        continue
    for c in content:
        if not isinstance(c, dict):
            continue
        if c.get("type") != "tool_use":
            continue
        name = c.get("name", "")
        inp = c.get("input", {}) or {}

        if name == "Bash":
            cmd = inp.get("command", "")
            if re.search(r'\bgit\s+commit\b', cmd):
                trigger_tools.append("git commit")
            if re.search(r'\bgit\s+push\b', cmd):
                trigger_tools.append("git push")
            if re.search(r'\bgh\s+pr\s+create\b', cmd):
                trigger_tools.append("gh pr create")
        elif name == "Edit":
            edit_count += 1
        elif name == "Write":
            fp = inp.get("file_path", "")
            if fp:
                write_files.append(fp)

if edit_count >= 3:
    trigger_tools.append(f"Edit×{edit_count}")
if write_files:
    trigger_tools.append(f"Write×{len(write_files)}")

trigger_tools = list(dict.fromkeys(trigger_tools))  # dedup preserve order
has_trigger = len(trigger_tools) > 0

# 偵測 assistant text 三句格式
assistant_text_parts = []
for obj in turn_events:
    if obj.get("type") != "assistant":
        continue
    msg = obj.get("message", {})
    content = msg.get("content")
    if not isinstance(content, list):
        continue
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            txt = c.get("text", "")
            if txt:
                assistant_text_parts.append(txt)

assistant_text = "\n".join(assistant_text_parts)

# 寬鬆 match: 預期 + 實際 + (匹配|match|✓|❌)
has_expected = bool(re.search(r'預期[：:]', assistant_text))
has_actual = bool(re.search(r'實際[：:]', assistant_text))
has_match = bool(re.search(r'匹配|match|✓|❌|對齊|相符|不符', assistant_text, re.IGNORECASE))
has_format = has_expected and has_actual and has_match

# Tail snippet (最後 200 字)
tail = assistant_text[-200:] if assistant_text else ""

# Output record
record = {
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "session_id": SESSION_ID,
    "has_trigger": has_trigger,
    "trigger_tools": trigger_tools,
    "has_format": has_format,
    "format_components": {
        "expected": has_expected,
        "actual": has_actual,
        "match": has_match,
    },
    "assistant_text_len": len(assistant_text),
    "tail_200": tail,
}

try:
    with open(LOG, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
except Exception:
    pass
PY

exit 0
