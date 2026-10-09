想知道「宣稱完成卻沒附預期／實際對照」有多常發生，得先有數據；這支 hook 靜默記錄每個回合有沒有照驗證格式回報。

**安裝**：把 `hooks/verify-audit-silent-log.sh` 複製到 `~/.claude/hooks/verify-audit-silent-log.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`~/.claude/hooks/verify-audit-silent-log.sh`

**需要自己接**：後端標記 CC_VENDOR（見 `WIRING.md`）。
