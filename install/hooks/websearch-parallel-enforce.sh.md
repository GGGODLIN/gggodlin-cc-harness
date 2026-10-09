只用 WebSearch API 查證時，搜尋引擎的排序常把轉載文排到官方文件前面；這支 gate 要求同一查詢先用瀏覽器讀過搜尋頁才放行 WebSearch。

**安裝**：把 `hooks/websearch-parallel-enforce.sh` 複製到 `~/.claude/hooks/websearch-parallel-enforce.sh`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `WebSearch`）：`~/.claude/hooks/websearch-parallel-enforce.sh`

**需要自己接**：瀏覽器自動化（見 `WIRING.md`）。

**測試**：`hooks/websearch-parallel-enforce.test.py`；裡面的路徑照原作者的機器寫，換環境可能要改。
