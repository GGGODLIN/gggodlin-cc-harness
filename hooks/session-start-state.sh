#!/bin/bash
# SessionStart hook — 若 cwd 下有 docs/owner/STATE.md 就注入內容讓 Claude 知道現況
# 對應規則：proj / 其他 repo 的 CLAUDE.md 寫「Session 開頭 Read docs/owner/STATE.md if exists」
# 以 no-follow directory fd 讀取，避免檢查與開檔之間被 symlink 替換
# 本檔在契約測試底下：bash ~/.claude/hooks/session-start-state-symlink.test.sh

set -uo pipefail

STATE_FILE="docs/owner/STATE.md"

python3 - "$STATE_FILE" <<'PY' 2>/dev/null || exit 0
import os
import stat
import sys
from pathlib import Path

state = Path(sys.argv[1])
if not state.is_absolute():
    state = Path.cwd() / state
parts = state.parts
if len(parts) < 2:
    raise SystemExit(0)
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
directory_fd = -1
state_fd = -1
try:
    directory_fd = os.open(state.anchor, directory_flags)
    for part in parts[1:-1]:
        next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
        os.close(directory_fd)
        directory_fd = next_fd
    state_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
    metadata = os.fstat(state_fd)
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(0)
    with os.fdopen(state_fd, "r", encoding="utf-8") as handle:
        state_fd = -1
        content = handle.read().rstrip("\n")
except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError):
    raise SystemExit(0)
finally:
    if state_fd >= 0:
        os.close(state_fd)
    if directory_fd >= 0:
        os.close(directory_fd)

sys.stdout.write(f"<project-state>\nSource: {state}\n\n{content}\n</project-state>\n")
PY
