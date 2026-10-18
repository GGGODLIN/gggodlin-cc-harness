模型在有未處理錯誤時仍宣稱「完成了」；這支 hook 在回合結束時偵測這種宣稱並提醒補證據。

**安裝**：把 `hooks/T1-claim-detect-local-first.sh` 複製到 `~/.claude/hooks/T1-claim-detect-local-first.sh`，保留執行權限。
同時把 `hooks/T1-system-prompt-v7.txt` 與 `hooks/claim-detect-keywords.json` 複製到同一個資料夾；少了 `T1-system-prompt-v7.txt`，模型判斷那一層會直接跳過（原因寫在 hook 的 warn log）；少了 `claim-detect-keywords.json`，未處理錯誤與完成宣稱合取提醒（Layer C）與測試都無法運作。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`~/.claude/hooks/fable-gate.sh ~/.claude/hooks/T1-claim-detect-local-first.sh`
這支 hook 透過 `hooks/fable-gate.sh` 包裝註冊；不裝 fable-gate 時，把指令裡的包裝器拿掉即可。

**需要自己接**：跨模型後端（見 `WIRING.md`）。

**測試**：`hooks/T1-claim-detect-local-first.llm.test.sh`、`hooks/T1-claim-detect-local-first.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
