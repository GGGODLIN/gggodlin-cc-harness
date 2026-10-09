# Code search

**定位 / 理解**（定義、邏輯、模糊意圖）→ 先 `mcp__semble__search`，NL query 與 exact 名稱都可使用。已知 file:line 要找相似 code → `mcp__semble__find_related`。

**完整枚舉**（改名前引用盤點、audit、所有 caller）→ 使用 `command grep`（或 `find <root> -type f -print0 | xargs -0 command grep -l`），並排除 out/、.shopify/ 等 build dir。不要用裸 `grep`——Bash tool 的 `grep` 是 CC 注入的 ugrep shim、帶 `--ignore-files`，會依 `.gitignore` 靜默漏檔。Semble 未命中或 index 尚未就緒時，改用 `command grep`＋Read。

🔌 接線點：session 歷史檢索 — 見 WIRING.md

**散文 / 筆記檢索**（memory、wiki、skill / command / agent 定義、部落格文章、work-notes 等 Markdown）→ 固定使用 Bash CLI：

```bash
🔌 接線點：程式碼搜尋 — 見 WIRING.md
```

`<path>` 直接指定語料根目錄，例如 `~/.claude` 或 `~/Desktop/work/work-notes`。中文 query 可用；排序不準時查看前 5 筆。
