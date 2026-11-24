# Desktop app routing

- 如果任務要操作非瀏覽器的 Mac app（點按鈕、打字、讀畫面），或使用者說「computer use」，預設入口、LCU 阻塞時停止回報、「不自動改道只限 agent、使用者指定工具就照用」都照 `browser-routing.md` 的 LCU 條款；其中 `site_status_blocked` 的 OBU 例外只適用網頁。
- 先從真實回件確認目標 app／視窗與新鮮元素指向，再操作並讀回結果；工具成功回覆不代替畫面或磁碟後置條件，Unicode 鍵盤插入不能因沒有錯誤就判成功。
- LCU 阻塞時同樣不自動改用 Peekaboo；macOS 安全與隱私權限不代點。
- 只有使用者明確指定 Cua 時，才依 `reference_cua_driver_macos_gui_automation_2026_09_30.md` 操作。
