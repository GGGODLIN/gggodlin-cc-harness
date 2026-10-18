新 repo 沒有 STATE 檔與帳本，進度只留在對話裡；這支 hook 在 session 開始時提醒建立，並尊重永久忽略清單。

**安裝**：把 `hooks/ledger-bootstrap.sh` 複製到 `~/.claude/hooks/ledger-bootstrap.sh`，保留執行權限。
同時把實際執行的 `scripts/ledger-bootstrap.py` 複製到 `~/.claude/scripts/ledger-bootstrap.py`，並把 `scripts/ledger-lifecycle/registry.json` 複製到 `~/.claude/scripts/ledger-lifecycle/registry.json`；少了這兩份檔案，薄殼 `.sh` 會因 `2>/dev/null` 靜默無效。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `SessionStart`：`~/.claude/hooks/ledger-bootstrap.sh`

**測試**：`hooks/ledger-bootstrap-settings.test.sh`、`hooks/ledger-bootstrap.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
