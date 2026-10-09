# Browser routing

- 一般 browser／網頁操作預設用 LCU MCP（`mcp__lcu__js`），依目前 server 的 initialization instructions 與 tool descriptors 操作；不先 invoke `open-browser-use`。
- LCU 使用已批准接線的日常 Chrome。只操作任務指定或自己建立的分頁，不讀無關頁面、cookies、passwords、history 或 session stores；分頁 ID 與元素指向以真實回件為準，不猜測。
- 如果 LCU MCP 未載入、未連線或缺少能力，就停止並回報具體阻塞，不自動改用 Cua、OBU、Agent Chrome 或直接啟動原 runtime；登記成功不等於目前 session 已重載。
🔌 接線點：瀏覽器自動化 — 見 WIRING.md
- 如果任務重點是 console、network、performance、Lighthouse、heap 或隔離瀏覽器診斷，直接使用 chrome-devtools；Agent Chrome profile 保留給這條診斷路徑，不作一般操作入口。
- Cua／OBU 的安裝與 Agent Chrome profile 暫保留作還原。只有使用者明確指定 OBU 時才 invoke `open-browser-use`；該舊路徑仍只能由 Agent-only resolver 連到 `~/.cache/chrome-devtools-mcp/agent-profile`，找不到唯一 socket 就停止，不改連日常 Chrome。
