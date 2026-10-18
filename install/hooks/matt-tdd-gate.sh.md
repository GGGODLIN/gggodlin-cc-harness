選了 TDD 的實作批次常在測試先紅之前就寫了實作；這支 gate 依批次設定檢查紅綠順序。

**安裝**：把 `hooks/matt-tdd-gate.sh` 複製到 `~/.claude/hooks/matt-tdd-gate.sh`，保留執行權限。
同時把 `skills/implement/scripts/tdd-policy.mjs` 複製到 `~/.claude/skills/implement/scripts/tdd-policy.mjs`（hook 在驗證測試與實作順序時會呼叫它）。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Skill`）：`~/.claude/hooks/matt-tdd-gate.sh`
- `Stop`：`~/.claude/hooks/matt-tdd-gate.sh`

**測試**：`skills/implement/scripts/tests/matt-tdd-gate.test.sh`、`hooks/matt-tdd-loopguard.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
