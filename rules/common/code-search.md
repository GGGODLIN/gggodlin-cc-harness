# Code search

🔌 接線點：全機文件定位 — 見 WIRING.md

**定位 / 理解**（定義、邏輯、模糊意圖）→ 本機原碼先 `mcp__code_search__search`：同一中英文 query 並行 Semble＋sgrep、每邊預設 10 段，合併去重並保留來源；先看後端狀態與路徑／行號，再 Read 原碼。入口未載入時暫用 `mcp__semble__search`。遠端 repo 用 `mcp__semble__search`；已知 file:line 要找相似 code 用 `mcp__semble__find_related`。

**程式碼歷史動機**（使用者問「這段 code 為什麼寫成這樣」，或準備移除目的不明但仍可能承擔契約的防禦性程式碼如 retry／timeout／sleep／特例 guard）→ 如果要回答該段歷史原因或動手移除該防禦行為，就在下結論或修改前讀 `~/.claude/references/verification-recipes-and-probes.md` 的「程式碼歷史動機追查」，先查局部 `git blame -L`／`git log -S`，不足時才沿 PR／票號擴查，並分開回報「當初為何加入」與「目前由誰保證」。

**完整枚舉**（改名前引用盤點、audit、所有 caller）→ 使用 `command grep`（或 `/usr/bin/grep`、`find <root> -type f -print0 | xargs -0 command grep -l`）。不要用裸 `grep -r`——Bash tool 的 `grep` 是 CC 注入的 ugrep shim、帶 `--ignore-files`，會依 `.gitignore` 靜默漏檔。搜尋未命中或 index 尚未就緒時，改用 `command grep`＋Read。目標含 build 目錄就加 `--exclude-dir`。根目錄是 `/`、`~`、`~/.claude`、`~/Desktop/projects` 這類多 repo 根時，先縮到相關 repo；縮不了就照[枚舉範圍與逾時](/references/code-search-enumeration.md)排除產物目錄（`~/.claude` 必含 `projects`）與超過 5 GB 的子目錄，結論列出排除項。撞 Bash 120s 逾時轉背景（`moved to background`）就同輪 `TaskStop`，之後只准縮小範圍重跑一次，仍逾時就停手回報沒搜到的範圍，不換寫法反覆重搜。

**歷史決策與 Session 檢索**（我之前怎麼做的、上次為什麼放棄某做法、某決策發生在哪場、口語別名或兩字短詞）→ **預設先跑 `tri-recall "<問題或關鍵詞>" -k 8`**（`--json` 結構化、`--no-expand` 略過雙語擴寫）：一次唯讀聯查 QMD＋`ccsi --short-scan`＋`claude-mem` 並優先更正結論。單點快查對話原文或篩 vendor 用 `ccsi search "<query>" -k 5`（`-C 2` 前後文、`--exclude-session <UUID前綴>`、`--vendor {cc,codex,pi}`；SQLite FTS5 trigram 涵蓋 CC/Codex/Pi，每 15m 增量，剛發生先 `ccsi index`；純 2 字中文加 `--short-scan` 或走 `tri-recall`；禁無界掃 `~/.claude/projects`）。看 `tool_result` 或長全文用 `ccsi events --session <id>` 或讀已知單一 `.jsonl`。

**散文 / 筆記檢索**（memory、wiki、skill／command／agent、blog、work-notes 等 Markdown）→ 固定使用 Bash CLI：

```bash
🔌 接線點：程式碼搜尋 — 見 WIRING.md
```

`[path]` 可省略（如 `~/.claude`、`~/Desktop/work/work-notes`）；未納管目錄自動轉多語 `semble`。大量改檔後跑 `qmd-docs sync`。
