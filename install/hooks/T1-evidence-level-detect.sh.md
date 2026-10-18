宣稱的強度常超過證據的強度（例如沒跑測試就說「已驗證」）；這支 hook 在回合結束時統計這類落差，給每週報告用。

**安裝**：把 `hooks/T1-evidence-level-detect.sh` 複製到 `~/.claude/hooks/T1-evidence-level-detect.sh`，保留執行權限。
同時把 `hooks/T1-evidence-level-prompt-v2.txt` 複製到同一個資料夾；少了它，hook 會在 warn log 記錄找不到 prompt 並直接略過。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`~/.claude/hooks/T1-evidence-level-detect.sh`

**需要自己接**：跨模型後端（見 `WIRING.md`）。

**測試**：`hooks/T1-evidence-level-detect.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
