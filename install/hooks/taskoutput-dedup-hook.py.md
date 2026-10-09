反覆讀同一個背景任務的輸出，會把一樣的內容一再塞進 context；這支 hook 偵測重複內容並改成簡短提示。

**安裝**：把 `hooks/taskoutput-dedup-hook.py` 複製到 `~/.claude/hooks/taskoutput-dedup-hook.py`，保留執行權限。
同時複製它用到的同名檔：`hooks/taskoutput-dedup-hook-fault.py`。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PostToolUse`（matcher `TaskOutput`）：`python3 ~/.claude/hooks/taskoutput-dedup-hook.py`
- `SessionStart`：`python3 ~/.claude/hooks/taskoutput-dedup-hook.py`

**啟用**：只註冊不會生效，還要建立啟用檔 `~/.claude/cache/taskoutput-dedup.enable.json`（可用環境變數 `TASKOUTPUT_DEDUP_ENABLE` 改位置）。條件全部成立才啟用：一般檔案、屬於自己、權限 600、內容只有 `version`（填 1）、`started_at`、`expires_at` 三個欄位（後兩者是 Unix 秒數），且現在還沒超過 `expires_at`。到期就自動停用，這是刻意的試用期設計。例如啟用 7 天：

```bash
python3 -c 'import json,time;n=time.time();print(json.dumps({"version":1,"started_at":n,"expires_at":n+7*86400}))' > ~/.claude/cache/taskoutput-dedup.enable.json
chmod 600 ~/.claude/cache/taskoutput-dedup.enable.json
```

**測試**：`hooks/taskoutput-dedup-hook.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
