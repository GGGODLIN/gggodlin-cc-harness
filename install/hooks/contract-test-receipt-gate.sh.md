追蹤受契約測試保護的檔案修改紀錄，在回應結束前核對是否已跑過對應契約測試並產生有效驗證收據。

**安裝**：把 `hooks/contract-test-receipt-gate.sh` 複製到 `~/.claude/hooks/contract-test-receipt-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `Edit|Write`）：`~/.claude/hooks/contract-test-receipt-gate.sh`
- `Stop`：`~/.claude/hooks/contract-test-receipt-gate.sh`

**測試**：`hooks/contract-test-receipt-gate.test.sh`。
