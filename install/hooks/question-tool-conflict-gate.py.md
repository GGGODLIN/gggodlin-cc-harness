有些模型會在同一回合先列出要你回答的問題（例如「### 待拍板」「### 第 2/5 題」），接著不停下來就呼叫工具，等於替你答了；這支 gate 在這種情況擋下工具呼叫，讓回合停下來等你回覆。

**安裝**：把 `hooks/question-tool-conflict-gate.py` 複製到 `~/.claude/hooks/question-tool-conflict-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Read|Edit|Write|MultiEdit|Bash|Skill|Agent|Workflow`）：`python3 ~/.claude/hooks/question-tool-conflict-gate.py`

**關閉**：設環境變數 `QUESTION_TOOL_GATE_DISABLE=1`，或從 `settings.json` 拿掉這一項。同一個問題最多擋 2 次，之後自動放行，不會讓 session 卡死。

**測試**：`hooks/question-tool-conflict-gate.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。

這支 gate 還在觀察期（2026-11-05 起），之後可能改動或移除。
