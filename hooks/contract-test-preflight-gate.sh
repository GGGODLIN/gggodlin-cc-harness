#!/usr/bin/env bash
# Threat model: this提示型 gate protects honest but forgetful agents that edit a command or SKILL.md without checking its contract tests. It does not prevent deliberate bypasses through an uncovered tool, a direct filesystem write, or a fabricated test reference, and it does not promise that a listed test is meaningful or that the edit will run it.
# This gate uses literal path and file-content matching rather than a shell parser. It recognises common entry points only, 不承諾 grep 找得到用變數拼檔名的引用, and may match text that merely discusses a command or path.
# Surface table:
# | 類別 | 面 | 邊界 |
# | Locked | gate、shared helper、fixture | agent 可讀但不可用本 gate 自評放行 |
# | Editable | commands/*.md、skills/**/SKILL.md | 目標內容由 Edit/Write 修改 |
# | Append-only | state/contract-test-seen-* | 每個 session 與 canonical path 各留一次 sentinel |
# | Human-controlled | state/contract-test-gate.disabled | 使用者建立或移除 recovery 開關 |
# Locked lifecycle: bootstrap is the normal settings.json install; update edits this gate, its helper, or its fixture and reruns the fixture; recovery uses contract-test-gate.disabled and leaves the allow decision in stderr.
# Bypass table:
# | 場景 | 預期攔截點 |
# | uncovered tool or direct filesystem write | outside this hook; no promise |
# | test mentions a filename without testing behavior | helper lists it because matching is intentionally literal |
# | helper failure | fail-open with one stderr line because this is a提示型 gate |
# | retry after first deny | allow by design after the session/path sentinel exists |
set -u

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PAYLOAD=$(cat 2>/dev/null) || exit 0

command -v jq >/dev/null 2>&1 || {
  printf '%s\n' '[contract-test-preflight-gate] jq unavailable; allowing edit.' >&2
  exit 0
}

EVENT=""
TOOL=""
FILE_PATH=""
SESSION_ID=""
CWD=""
if ! {
  IFS= read -r -d '' EVENT
  IFS= read -r -d '' TOOL
  IFS= read -r -d '' FILE_PATH
  IFS= read -r -d '' SESSION_ID
  IFS= read -r -d '' CWD
} < <(printf '%s' "$PAYLOAD" | jq -j '
  if type == "object" then
    (if (.hook_event_name? | type) == "string" then .hook_event_name else "" end), "\u0000",
    (if (.tool_name? | type) == "string" then .tool_name else "" end), "\u0000",
    (if (.tool_input? | type) == "object" and (.tool_input.file_path? | type) == "string" then .tool_input.file_path else "" end), "\u0000",
    (if (.session_id? | type) == "string" then .session_id else "" end), "\u0000",
    (if (.cwd? | type) == "string" then .cwd else "" end), "\u0000"
  else empty end
' 2>/dev/null); then
  exit 0
fi

[ -z "$EVENT" ] || [ "$EVENT" = "PreToolUse" ] || exit 0
case "$TOOL" in
  Edit|Write) ;;
  *) exit 0 ;;
esac
[ -n "$FILE_PATH" ] || exit 0

# Fast-path: a non-symlink file whose basename does not end in .md cannot resolve to */SKILL.md or /commands/*.md.
case "$FILE_PATH" in
  *.md) ;;
  *)
    _RAW_CHECK="$FILE_PATH"
    case "$_RAW_CHECK" in
      /*|~*) ;;
      *) _RAW_CHECK="${CWD:-.}/$_RAW_CHECK" ;;
    esac
    if [ ! -L "$_RAW_CHECK" ]; then
      exit 0
    fi
    ;;
esac

CANONICAL_PATH=$(python3 - "$FILE_PATH" "$CWD" <<'PY' 2>/dev/null
import os
import sys

path, cwd = sys.argv[1:3]
path = os.path.expanduser(path)
if not os.path.isabs(path):
  path = os.path.join(cwd or os.getcwd(), path)
print(os.path.realpath(path))
PY
) || {
  printf '%s\n' '[contract-test-preflight-gate] path resolution failed; allowing edit.' >&2
  exit 0
}

TARGET=0
case "$CANONICAL_PATH" in
  */SKILL.md) TARGET=1 ;;
esac
if [[ "$CANONICAL_PATH" =~ /commands/[^/]+\.md$ ]]; then
  TARGET=1
fi
[ "$TARGET" -eq 1 ] || exit 0

HELPER="${CONTRACT_TEST_HELPER:-$HOOK_DIR/../scripts/contract-test-helper.sh}"
if [ ! -x "$HELPER" ]; then
  printf '%s\n' '[contract-test-preflight-gate] contract-test helper failed; allowing edit.' >&2
  exit 0
fi

TESTS=$("$HELPER" "$CANONICAL_PATH" 2>/dev/null)
HELPER_STATUS=$?
[ "$HELPER_STATUS" -eq 0 ] || {
  printf '%s\n' '[contract-test-preflight-gate] contract-test helper failed; allowing edit.' >&2
  exit 0
}
[ -n "$TESTS" ] || exit 0

[ -n "$SESSION_ID" ] || {
  printf '%s\n' '[contract-test-preflight-gate] session id unavailable; allowing edit.' >&2
  exit 0
}

HOME_DIR="${HOME:-}"
STATE_DIR="${CONTRACT_TEST_STATE_DIR:-${HOME_DIR:+$HOME_DIR/.claude/hooks/state}}"
DISABLED="${CONTRACT_TEST_DISABLED_SENTINEL:-${STATE_DIR:+$STATE_DIR/contract-test-gate.disabled}}"
if [ -n "$DISABLED" ] && { [ -e "$DISABLED" ] || [ -L "$DISABLED" ]; }; then
  printf 'contract-test-preflight-gate disabled by %s; allowing edit.\n' "$DISABLED" >&2
  exit 0
fi

if [ ! -d "$STATE_DIR" ]; then
  mkdir -p "$STATE_DIR" 2>/dev/null || {
    printf '%s\n' '[contract-test-preflight-gate] state directory unavailable; allowing edit.' >&2
    exit 0
  }
fi
[ -L "$STATE_DIR" ] || [ -d "$STATE_DIR" ] || {
  printf '%s\n' '[contract-test-preflight-gate] state directory is not a directory; allowing edit.' >&2
  exit 0
}

PATH_HASH=$(python3 - "$CANONICAL_PATH" <<'PY' 2>/dev/null
import hashlib
import sys
print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:24])
PY
) || {
  printf '%s\n' '[contract-test-preflight-gate] path hashing failed; allowing edit.' >&2
  exit 0
}

case "$SESSION_ID" in
  *[!A-Za-z0-9._-]*)
    SESSION_KEY=$(python3 - "$SESSION_ID" <<'PY' 2>/dev/null
import hashlib
import sys
print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:24])
PY
    ) || {
      printf '%s\n' '[contract-test-preflight-gate] session hashing failed; allowing edit.' >&2
      exit 0
    }
    ;;
  *) SESSION_KEY="$SESSION_ID" ;;
esac

SENTINEL="$STATE_DIR/contract-test-seen-${SESSION_KEY}-${PATH_HASH}"
if [ -e "$SENTINEL" ] || [ -L "$SENTINEL" ]; then
  exit 0
fi

if ! (set -C; : >"$SENTINEL") 2>/dev/null; then
  if [ -e "$SENTINEL" ] || [ -L "$SENTINEL" ]; then
    exit 0
  fi
  printf '%s\n' '[contract-test-preflight-gate] seen sentinel unavailable; allowing edit.' >&2
  exit 0
fi
chmod 600 "$SENTINEL" 2>/dev/null || true

REASON=$(printf '這次修改未套用。這個檔案有契約測試，先查下列考卷：\n%s\n注意：本前置 gate 為單次提醒（首次攔截即記錄本 session+檔案已提醒，重試原本的 Edit／Write 即放行，重試放行不代表測試收據已驗過；真正的測試收據硬檢查在 commit／Stop gate）。改完必須跑上列測試；此檔無標記者請補檔頭標記。' "$TESTS")
jq -cn --arg reason "$REASON" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
exit 0
