agent 常在呼叫 Figma MCP 前忘了先載入 figma-context-budget skill，一次讀進整份設計稿把 context 燒光；這支 gate 在沒載入 skill 時擋下 Figma MCP 呼叫。

**安裝**：把 `hooks/figma-context-budget-gate.sh` 複製到 `~/.claude/hooks/figma-context-budget-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Skill`）：`~/.claude/hooks/figma-context-budget-gate.sh`
- `PreToolUse`（matcher `mcp__figma*|mcp__claude_ai_Figma__*`）：`~/.claude/hooks/figma-context-budget-gate.sh`

**測試**：`hooks/figma-context-budget-gate.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
