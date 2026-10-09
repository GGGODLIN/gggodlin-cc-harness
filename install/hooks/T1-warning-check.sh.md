T1 宣稱偵測 hook 出錯時只寫在 log 裡，沒人看到就一直壞著；這支 hook 在 session 開始時把當天的警告帶出來。

**安裝**：把 `hooks/T1-warning-check.sh` 複製到 `~/.claude/hooks/T1-warning-check.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `SessionStart`：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/T1-warning-check.sh`
這支 hook 透過 `hooks/fable-gate.sh` 包裝註冊；不裝 fable-gate 時，把指令裡的包裝器拿掉即可。

**需要自己接**：跨模型後端（見 `WIRING.md`）。
