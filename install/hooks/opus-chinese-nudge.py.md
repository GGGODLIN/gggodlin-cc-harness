在 `UserPromptSubmit` 注入簡短語系提醒，降低主力模型在英文系統訊息或工具輸出後意外切回英文回覆的機率。

**安裝**：把 `hooks/opus-chinese-nudge.py` 複製到 `~/.claude/hooks/opus-chinese-nudge.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `UserPromptSubmit`：`python3 ~/.claude/hooks/opus-chinese-nudge.py`

**測試**：`hooks/opus-chinese-nudge.test.py`。
