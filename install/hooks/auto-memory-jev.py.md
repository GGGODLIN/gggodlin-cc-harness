該記下來的偏好或決定常在 session 結束後就消失；這支 hook 在回合結束後背景判斷是否值得記，並在下一則提問時提醒。

**安裝**：把 `hooks/auto-memory-jev.py` 複製到 `~/.claude/hooks/auto-memory-jev.py`，保留執行權限。
同時複製它用到的同名檔：`hooks/auto-memory-jev-question.json`、`hooks/auto-memory-jev.md`。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`python3 ~/.claude/hooks/auto-memory-jev.py stop`
- `UserPromptSubmit`：`python3 ~/.claude/hooks/auto-memory-jev.py deliver`

**測試**：`hooks/auto-memory-jev.harness.test.py`、`hooks/auto-memory-jev.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
