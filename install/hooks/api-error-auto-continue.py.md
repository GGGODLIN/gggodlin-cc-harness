互動 session 因可重試的 API 錯誤中斷時，要人回來手動打「繼續」；這支 hook 透過終端後端在原 pane 代打接續句。

**安裝**：把 `hooks/api-error-auto-continue.py` 複製到 `~/.claude/hooks/api-error-auto-continue.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `Stop`：`python3 ~/.claude/hooks/api-error-auto-continue.py stop`
- `StopFailure`：`python3 ~/.claude/hooks/api-error-auto-continue.py`

**需要自己接**：終端後端（見 `WIRING.md`）。

**測試**：`hooks/api-error-auto-continue.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
