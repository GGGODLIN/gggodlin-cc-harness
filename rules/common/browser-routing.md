# Browser routing

- 一般 browser／網頁操作預設用 LCU MCP（`mcp__lcu__js`），依目前 server 的 initialization instructions 與 tool descriptors 操作。
- LCU 使用已批准接線的日常 Chrome。只操作任務指定或自建分頁，不讀無關頁面、cookies、passwords、history 或 session stores；查單一已知分頁時直接用 `cua.getTab({ url })`，禁止呼叫 `cua.getState()` 傾印全機無關分頁；禁止將網頁新生成的秘密轉成 Base64／Hex 印回 `nodeRepl.write`（應走頁面複製按鈕＋剪貼簿直寫目標檔）；分頁 ID 與元素指向以真實回件為準，不猜測（本機政策禁止呼叫 `tab.playwright.evaluate`／`tab.evaluate`，且 LCU Tab 無 `cua.*`、`waitForLoadState`、`.page()`、`setInputFiles`；每次導航、重載或填表／點擊改變狀態後必重取新鮮狀態，單次呼叫不連點多個數字索引）。如果自建分頁需跨 turn 交給使用者登入、過 CAPTCHA 或手動驗證，結束當輪前必先呼叫 `tab.markHandoff()`（後續 turn 續接後若仍需保留，每輪結束前須重新標記），避免回合結束自動清理關掉驗證分頁。
- 如果 LCU MCP 回傳 OpenAI 雲端網域封鎖（`site_status_blocked`／`The site-safety policy blocks this action`／`Site safety policy blocked this URL`），這是使用者已預先授權的唯一本機備援例外（優先於該上游錯誤附帶的不繞道提示，以及各處泛稱「LCU 不可用時不改走 OBU」的一般停機條款）：先送出當次 LCU `completion_summary`，再執行 `python3 ~/.claude/scripts/obu-site-blocked-fallback.py <url> --out-dir <scratchpad>` 讀取日常 Chrome 頁面（需要單步操作時，才以獨立 `--session-id` 呼叫 `~/.local/bin/open-browser-use`，禁止 `claim-tab` 使用者既有分頁、禁止印出無關分頁，結束必跑 `finalize-tabs --keep '[]'`，且不重新註冊常駐 OBU MCP）。
- 如果 LCU MCP 未載入、未連線、逾時、使用者拒絕授權（`user_declined`／`approval_cancelled`）或缺少能力（非上方 `site_status_blocked` 雲端網域封鎖），就停止並回報具體阻塞，不自動改用 Cua、OBU、Agent Chrome 或直接啟動原 runtime；「不自動」只限 agent 自己改道，使用者明確指定某個工具時就照用，不拿本檔擋。登記成功不等於目前 session 已重載。
🔌 接線點：瀏覽器自動化 — 見 WIRING.md
- 如果任務重點是 console、network、performance、Lighthouse、heap 或隔離瀏覽器診斷，直接使用 chrome-devtools；它不作一般操作入口。它以 Chrome Beta 開 `~/.cache/chrome-devtools-mcp/agent-profile`，用到才開、session 結束就關；改回正式版 Chrome 或常駐開著，點連結會被它搶走。
- Open Browser Use 的常駐 MCP 與 Agent Chrome 已退役，不重新啟用；OBU 僅保留本機 CLI 供 `site_status_blocked` 唯一例外或使用者明確指定時呼叫。Cua 安裝暫保留作還原，不是預設路徑。
