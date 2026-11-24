在 `Bash` 執行 git commit 或修改受控設定檔（agents／skills／hooks／workflows）時強制驗證契約與結構完整性，防繞過或寫壞受控檔。

**安裝**：把 `hooks/agent-contract-validator-gate.sh` 複製到 `~/.claude/hooks/agent-contract-validator-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash`）：`~/.claude/hooks/agent-contract-validator-gate.sh`

**測試**：`hooks/agent-contract-validator-gate.test.sh`。
