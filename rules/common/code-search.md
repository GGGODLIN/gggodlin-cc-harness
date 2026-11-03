# Code search

🔌 接線點：全機文件定位 — 見 WIRING.md

**定位 / 理解**（定義、邏輯、模糊意圖）→ 本機原碼先 `mcp__code_search__search`：同一中英文 query 並行 Semble＋sgrep、每邊預設 10 段，合併去重並保留來源；先看後端狀態與路徑／行號，再 Read 原碼。入口未載入時暫用 `mcp__semble__search`。遠端 repo 用 `mcp__semble__search`；已知 file:line 要找相似 code 用 `mcp__semble__find_related`。

**程式碼歷史動機**（使用者問「這段 code 為什麼寫成這樣」，或準備移除目的不明但仍可能承擔契約的防禦性程式碼如 retry／timeout／sleep／特例 guard）→ 如果要回答該段歷史原因或動手移除該防禦行為，就在下結論或修改前讀 `~/.claude/references/verification-recipes-and-probes.md` 的「程式碼歷史動機追查」，先查局部 `git blame -L`／`git log -S`，不足時才沿 PR／票號擴查，並分開回報「當初為何加入」與「目前由誰保證」。

**完整枚舉**（改名前引用盤點、audit、所有 caller）→ 使用 `command grep`（或 `find <root> -type f -print0 | xargs -0 command grep -l`），並排除 out/、.shopify/ 等 build dir。不要用裸 `grep`——Bash tool 的 `grep` 是 CC 注入的 ugrep shim、帶 `--ignore-files`，會依 `.gitignore` 靜默漏檔。搜尋未命中或 index 尚未就緒時，改用 `command grep`＋Read。如果對 `~`、`~/.claude`、`~/Desktop/projects` 等含大量對話／快取產物的根目錄做一般跨目錄搜尋（且調查目標本身不是這些子目錄），就加上 `--exclude-dir={.git,node_modules,.venv,out,.shopify,projects,cache,plugins,snapshot,jobs}`；如果搜尋指令撞 Bash 120s 逾時被轉入背景（`moved to background`），就必須在同一輪立即呼叫 `TaskStop` 終止該背景搜尋，不留孤兒程序空轉。

**Session 歷史檢索**（我之前怎麼做的、上次為什麼放棄某做法、某決策發生在哪個 session）→ `ccsi search "<query>" -k 5`（加 `-C 2` 展開同檔前後已索引紀錄、加 `--exclude-session <UUID前綴>` 排除當前 session、加 `--vendor {cc,codex,pi}` 篩來源）。SQLite FTS5 全文索引，涵蓋 `~/.claude/projects/**/*.jsonl`（含 subagent 與 workflow transcript）、Codex 與 Pi，launchd 約每 15 分鐘自動增量（剛發生的對話若未入庫可先 `ccsi index`）。trigram tokenizer：查詢至少要有一個 `>=3` 字元的詞或雙引號片語（純 2 字中文詞會報錯 exit 2，可連寫成片語或拉長詞組），且多詞必須在同一則訊息共現（不確定時拆成多次短查詢）。需要看未入 FTS 的 `tool_result` 或更長全文時，再用 `ccsi events --session <id>` 或讀命中原檔。

**散文 / 筆記檢索**（memory、wiki、skill / command / agent 定義、部落格文章、work-notes 等 Markdown）→ 固定使用 Bash CLI：

```bash
🔌 接線點：程式碼搜尋 — 見 WIRING.md
```

`<path>` 直接指定語料根目錄，例如 `~/.claude` 或 `~/Desktop/work/work-notes`。中文 query 可用；排序不準時查看前 5 筆。
