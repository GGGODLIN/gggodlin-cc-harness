操作瀏覽器時若呼叫 LCU 不支援的 Playwright 方法，或在同一次呼叫中連點多個數字索引（未等畫面更新重讀無障礙樹），會導致操作失敗或點錯元素；這支 gate 在呼叫前攔截這兩類錯誤寫法。

**安裝**：把 `hooks/lcu-browser-routing-gate.py` 複製到 `~/.claude/hooks/lcu-browser-routing-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `mcp__lcu__js`）：`python3 ~/.claude/hooks/lcu-browser-routing-gate.py`

**測試**：`hooks/lcu-browser-routing-gate.test.py`。
