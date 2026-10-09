程式沒改就把同一個驗證指令再跑一次，不會產生新證據；這支 hook 在偵測到一字不差的重跑時提醒換驗證角度。

**安裝**：把 `hooks/repeat-verify-reminder.sh` 複製到 `~/.claude/hooks/repeat-verify-reminder.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Bash|Edit|Write|NotebookEdit`）：`~/.claude/hooks/repeat-verify-reminder.sh`

**測試**：`hooks/repeat-verify-reminder.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
