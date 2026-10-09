新 session 不知道這個 repo 進行到哪裡，常從頭問起；這支 hook 在 session 開始時注入 repo 裡的 STATE 檔。

**安裝**：把 `hooks/session-start-state.sh` 複製到 `~/.claude/hooks/session-start-state.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `SessionStart`：`~/.claude/hooks/session-start-state.sh`

**測試**：`hooks/session-start-state-symlink.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
