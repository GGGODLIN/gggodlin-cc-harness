寫 hook 時容易跳過威脅模型、繞過面與失效模式的檢查；這支 hook 在編輯 hook 檔時提醒先走 gate-authoring 清單。

**安裝**：把 `hooks/gate-authoring-nudge.sh` 複製到 `~/.claude/hooks/gate-authoring-nudge.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Write|Edit`）：`~/.claude/hooks/gate-authoring-nudge.sh`
