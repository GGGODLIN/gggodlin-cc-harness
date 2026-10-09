每日本機分析報告要有人記得去跑；這支 hook 在當天第一則提問時提醒執行 daily-local，並把報告裡需要決策的項目排到前面。

**安裝**：把 `hooks/daily-local-analysis-trigger.sh` 複製到 `~/.claude/hooks/daily-local-analysis-trigger.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `UserPromptSubmit`：`~/.claude/hooks/daily-local-analysis-trigger.sh`

**測試**：`hooks/daily-local-analysis-trigger.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
