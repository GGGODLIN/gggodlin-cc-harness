把整個大目錄丟給常駐的語意搜尋 MCP 會在它的程序裡留下很大的索引；這支 hook 擋下對聚合根目錄的搜尋，要求縮小範圍。

**安裝**：把 `hooks/semble-root-block.py` 複製到 `~/.claude/hooks/semble-root-block.py`，保留執行權限。

**註冊**：在 `~/.claude/settings.json` 的 `hooks` 加入下列項目（與公開版 `settings.json` 相同）：
- `PreToolUse`（matcher `mcp__semble__search|mcp__semble__find_related`）：`/usr/bin/python3 -I ~/.claude/hooks/semble-root-block.py`

**需要自己接**：程式碼搜尋（見 `WIRING.md`）。

**測試**：`hooks/semble-root-block.test.sh`；裡面的路徑照原作者的機器寫，換環境可能要改。
