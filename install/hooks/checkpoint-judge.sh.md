使用者說「記下來」「收尾」時，模型常只口頭答應沒有真的存檔；這支 hook 在回合結束與 compact 前判斷是否該寫 checkpoint 或 memory 並提醒。

**安裝**：把 `hooks/checkpoint-judge.sh` 複製到 `~/.claude/hooks/checkpoint-judge.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreCompact`（matcher `manual`）：`~/.claude/hooks/checkpoint-judge.sh`
- `PreCompact`（matcher `auto`）：`~/.claude/hooks/checkpoint-judge.sh`
- `Stop`：`~/.claude/hooks/checkpoint-judge.sh`

**需要自己接**：後端標記 CC_VENDOR（見 `WIRING.md`）。

**測試**：`hooks/checkpoint-judge.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
