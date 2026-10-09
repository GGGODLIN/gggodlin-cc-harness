Workflow 腳本裡的 agent() 不經過一般的派工 gate，漏寫模型就會繼承 main 的模型；這支 gate 擋下確定漏寫的呼叫。

**安裝**：把 `hooks/workflow-routing-gate.py` 複製到 `~/.claude/hooks/workflow-routing-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Workflow`）：`python3 ~/.claude/hooks/workflow-routing-gate.py`

**測試**：`hooks/workflow-routing-gate.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
