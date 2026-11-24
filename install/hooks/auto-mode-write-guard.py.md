保護自動模式（auto-mode）狀態檔與停用開關，防止 agent 在執行過程中擅自修改人控的自動模式開關或覆寫策略。

**安裝**：把 `hooks/auto-mode-write-guard.py` 複製到 `~/.claude/hooks/auto-mode-write-guard.py`，並一併複製 `scripts/auto-mode/` 下的模組到 `~/.claude/scripts/auto-mode/`。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash|Edit|Write`）：`/usr/bin/python3 -IB ~/.claude/hooks/auto-mode-write-guard.py`

**測試**：`hooks/auto-mode-write-guard.test.py`、`scripts/auto-mode/test_*.py`。
