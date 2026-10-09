最貴的模型當 main 時，一些重型提醒 hook 只會徒增成本；這支包裝器依目前的模型決定要不要跑被包住的 hook。

**安裝**：把 `hooks/fable-gate.sh` 複製到 `~/.claude/hooks/fable-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Bash`）：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/cd-cwd-persistence-nudge.sh`
- `PreToolUse`（matcher `Agent`）：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/T2-routing-gate.sh`
- `SessionStart`：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/T1-warning-check.sh`
- `Stop`：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/T1-claim-detect-local-first.sh`

用法是把要包的 hook 寫在後面當參數，例如 `~/.claude/hooks/fable-gate.sh ~/.claude/hooks/T2-routing-gate.sh`；它判斷目前模型時，優先讀 statusline 寫在 `/tmp/cc-widget-cache/model-<session>.txt` 的快取，沒有就改讀 transcript，所以不裝 statusline 也能用。

**測試**：`hooks/fable-gate.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
