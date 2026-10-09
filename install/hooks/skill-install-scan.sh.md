從外部裝進來的 skill 或 command 可能夾帶要你按星、追蹤、回報資料的指令；這支 hook 在第三方內容寫進 skills／commands 時觸發軟注入掃描。

**安裝**：把 `hooks/skill-install-scan.sh` 複製到 `~/.claude/hooks/skill-install-scan.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Write|Edit`）：`~/.claude/hooks/skill-install-scan.sh`

**測試**：`hooks/skill-install-scan.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
