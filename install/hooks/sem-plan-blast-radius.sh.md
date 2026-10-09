實作計畫要改的既有檔，影響範圍常被低估；這支 hook 在 tasks 檔落檔時用 sem 算出受影響的呼叫端並提醒。

**安裝**：把 `hooks/sem-plan-blast-radius.sh` 複製到 `~/.claude/hooks/sem-plan-blast-radius.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Write|Edit`）：`~/.claude/hooks/sem-plan-blast-radius.sh`

**測試**：`hooks/sem-plan-blast-radius.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
