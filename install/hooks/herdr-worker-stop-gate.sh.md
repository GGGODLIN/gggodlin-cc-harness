在 Herdr 終端機（具備 `HC_TERMINAL_ID`）主控 session 結束回合前，檢查名下是否仍有未掛監看或已完工待收的子 worker，防止漏收背景工作；非 Herdr 環境會靜默放行。

**安裝**：把 `hooks/herdr-worker-stop-gate.sh` 複製到 `~/.claude/hooks/herdr-worker-stop-gate.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`~/.claude/hooks/herdr-worker-stop-gate.sh`

**測試**：`hooks/herdr-worker-stop-gate.test.py`。
