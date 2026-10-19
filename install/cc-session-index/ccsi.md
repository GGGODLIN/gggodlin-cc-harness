跨 session 要找回以前的決策、踩坑或某個檔案在哪場對話被改過時，直接 grep 數十 GB 的 `.jsonl` 太慢，而預設分詞器或純英文 embedding 模型又搜不到中文子字串；`ccsi` 用單一 Python 檔建立 SQLite FTS5 `trigram` 索引與跨工具（Claude Code／Codex／Pi）正規化事件流。


把 `cc-session-index/ccsi` 連到 `~/.local/bin/ccsi`（確保 `~/.local/bin` 在 `PATH` 內），先執行 `ccsi index` 建立初次索引（若連結的 SQLite 低於 3.34.0 或未啟用 FTS5 `trigram` 會明確報錯）。定時增量更新（LaunchAgent／cron）與環境變數覆寫見 `cc-session-index/README.md` 與 `cc-session-index/README.zh-TW.md`（或獨立 repo `https://github.com/GGGODLIN/cc-session-index`）。
