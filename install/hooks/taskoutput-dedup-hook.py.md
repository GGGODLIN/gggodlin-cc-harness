反覆讀同一個背景任務的輸出，會把一樣的內容一再塞進 context；這支 hook 偵測重複內容並改成簡短提示。

**安裝**：把 `hooks/taskoutput-dedup-hook.py` 複製到 `~/.claude/hooks/taskoutput-dedup-hook.py`，保留執行權限。
同時複製它用到的同名檔：`hooks/taskoutput-dedup-hook-fault.py`。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `TaskOutput`）：`python3 ~/.claude/hooks/taskoutput-dedup-hook.py`
- `SessionStart`：`python3 ~/.claude/hooks/taskoutput-dedup-hook.py`

**測試**：`hooks/taskoutput-dedup-hook.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
