查看設定時直接呼叫 Read 或 cat 讀取 .env／.dev.env 會把資料庫密碼或 API 金鑰明文印進對話；這支 gate 攔截直接讀取秘密檔，只放行看變數名或白名單非敏感變數。

**安裝**：把 `hooks/dotenv-read-gate.py` 複製到 `~/.claude/hooks/dotenv-read-gate.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `Read|Bash`）：`python3 ~/.claude/hooks/dotenv-read-gate.py`

**測試**：`hooks/dotenv-read-gate.test.py`。
