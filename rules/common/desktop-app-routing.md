# Desktop app routing

- 如果任務要操作非瀏覽器的 Mac app（點按鈕、打字、讀畫面），或使用者說「computer use」，預設用 LCU MCP（`mcp__lcu__js`），依目前 server 的 initialization instructions 與 tool descriptors 操作。
- 先從真實回件確認目標 app／視窗與新鮮元素指向，再操作並讀回結果；工具成功回覆不代替畫面或磁碟後置條件，Unicode 鍵盤插入不能因沒有錯誤就判成功。
- 如果 LCU 未載入、未連線或遇到能力／核准阻塞，就停止並回報；不自動啟動 Cua、Peekaboo 或原 runtime 繞過正式接線。macOS 安全與隱私權限不代點。
- Cua 安裝暫保留作還原。只有使用者明確指定 Cua 時，才依 `reference_cua_driver_macos_gui_automation_2026_09_30.md` 的細節操作；不是預設路徑。
- 網頁照 `browser-routing.md`；專用診斷路徑與一般桌面／網頁操作分開。
