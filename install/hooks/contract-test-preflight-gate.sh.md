在修改受契約測試保護的檔案（檔頭註記 `本檔在契約測試底下`）前注入前導提醒，提示修改後需執行對應契約測試。

**安裝**：把 `hooks/contract-test-preflight-gate.sh` 複製到 `~/.claude/hooks/contract-test-preflight-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Write|Edit`）：`~/.claude/hooks/contract-test-preflight-gate.sh`

**測試**：`hooks/contract-test-preflight-gate.test.sh`。
