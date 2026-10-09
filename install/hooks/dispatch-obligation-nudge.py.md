使用者同意後，main session 容易自己連查好幾次網頁、自己改一堆檔，而不是派 subagent；這支 hook 依搜尋次數與提示內容提醒該派工了。

**安裝**：把 `hooks/dispatch-obligation-nudge.py` 複製到 `~/.claude/hooks/dispatch-obligation-nudge.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `WebSearch|WebFetch|mcp__claude-in-chrome__navigate|mcp__chrome-devtools__navigate_page`）：`/usr/bin/python3 ~/.claude/hooks/dispatch-obligation-nudge.py tool`
- `UserPromptSubmit`：`/usr/bin/python3 ~/.claude/hooks/dispatch-obligation-nudge.py prompt`

**需要自己接**：跨模型後端（見 `WIRING.md`）。

**測試**：`hooks/dispatch-obligation-nudge.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
