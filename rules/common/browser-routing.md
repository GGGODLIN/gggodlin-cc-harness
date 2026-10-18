# Browser routing

- 一般 browser／網頁操作預設用 LCU MCP（`mcp__lcu__js`），依目前 server 的 initialization instructions 與 tool descriptors 操作。
- LCU 使用已批准接線的日常 Chrome。只操作任務指定或自己建立的分頁，不讀無關頁面、cookies、passwords、history 或 session stores；分頁 ID 與元素指向以真實回件為準，不猜測。
- 如果 LCU MCP 未載入、未連線或缺少能力，就停止並回報具體阻塞，不自動改用 Cua、OBU、Agent Chrome 或直接啟動原 runtime；「不自動」只限 agent 自己改道，使用者明確指定某個工具時就照用，不拿本檔擋。登記成功不等於目前 session 已重載。
🔌 接線點：瀏覽器自動化 — 見 WIRING.md
- 如果任務重點是 console、network、performance、Lighthouse、heap 或隔離瀏覽器診斷，直接使用 chrome-devtools；它不作一般操作入口。它以 Chrome Beta 開 `~/.cache/chrome-devtools-mcp/agent-profile`，用到才開、session 結束就關；改回正式版 Chrome 或常駐開著，點連結會被它搶走。
- Open Browser Use，以及 Agent Chrome 的開機自動啟動與 9223 連線已退役，不重新啟用；還原材料另存於作者本機，公開版不附。Cua 安裝暫保留作還原，不是預設路徑。
