使用者說「我記得」「上次」時，模型常憑印象回答而不去翻紀錄；這支 hook 在偵測到這類字眼時提醒先回查。

**安裝**：把 `hooks/recall-before-answer.sh` 複製到 `~/.claude/hooks/recall-before-answer.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `UserPromptSubmit`：`~/.claude/hooks/recall-before-answer.sh`

**測試**：`hooks/recall-before-answer.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
