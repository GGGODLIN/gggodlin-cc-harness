spec 或 design 文件寫完常直接進實作，沒有先審；這支 hook 在這類文件落檔時跳出 review-spec 的分級選單。

**安裝**：把 `hooks/review-spec-tier1-nudge.sh` 複製到 `~/.claude/hooks/review-spec-tier1-nudge.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Write|Edit`）：`~/.claude/hooks/review-spec-tier1-nudge.sh`

**測試**：`hooks/review-spec-tier1-nudge.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
