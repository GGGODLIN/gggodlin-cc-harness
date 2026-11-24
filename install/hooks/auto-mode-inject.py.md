在每次使用者送出提示前檢查自動模式是否啟用；啟用時將 `scripts/auto-mode/` 的決策紀錄 CLI 與停手條件注入當輪上下文。

**安裝**：把 `hooks/auto-mode-inject.py` 複製到 `~/.claude/hooks/auto-mode-inject.py`，並一併複製 `scripts/auto-mode/` 下的模組到 `~/.claude/scripts/auto-mode/`。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `UserPromptSubmit`：`python3 -IB ~/.claude/hooks/auto-mode-inject.py`

**測試**：`hooks/auto-mode-inject.test.py`、`scripts/auto-mode/test_*.py`。
