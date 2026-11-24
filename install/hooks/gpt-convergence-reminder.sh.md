當偵測到目前主模型為 GPT 系列時，在 `SessionStart`（啟動／續接／壓縮後）注入收斂原則提醒，減少過度設計與重複重驗；非 GPT 模型會靜默放行。

**安裝**：把 `hooks/gpt-convergence-reminder.sh` 複製到 `~/.claude/hooks/gpt-convergence-reminder.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `SessionStart`：`~/.claude/hooks/gpt-convergence-reminder.sh`

**測試**：`hooks/gpt-convergence-reminder.test.sh`。
