有些模型會把工具呼叫寫成純文字，subagent 因此什麼都沒執行就結束；這支 hook 在 subagent 結束時偵測這種情況並提醒重派。

**安裝**：把 `hooks/subagent-text-toolcall-nudge.py` 複製到 `~/.claude/hooks/subagent-text-toolcall-nudge.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `SubagentStop`：`python3 ~/.claude/hooks/subagent-text-toolcall-nudge.py`

**測試**：`hooks/subagent-text-toolcall-nudge.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
