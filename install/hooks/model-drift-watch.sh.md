模型別名悄悄換到新版本時，舊的行為假設可能已經不成立；這支 hook 在第一次看到新的模型 ID 時提醒做一次模型 review。

**安裝**：把 `hooks/model-drift-watch.sh` 複製到 `~/.claude/hooks/model-drift-watch.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `UserPromptSubmit`：`~/.claude/hooks/model-drift-watch.sh`

**測試**：`hooks/model-drift-watch.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
