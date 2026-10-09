背景 Workflow 跑到一半撞到用量上限會整批作廢；這支 hook 在 Workflow 啟動時提醒掛上 workflow-monitor 守護。

**安裝**：把 `hooks/workflow-monitor-nudge.sh` 複製到 `~/.claude/hooks/workflow-monitor-nudge.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Workflow`）：`~/.claude/hooks/workflow-monitor-nudge.sh`

**需要自己接**：後端標記 CC_VENDOR（見 `WIRING.md`）。

**測試**：`hooks/workflow-monitor-nudge.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
