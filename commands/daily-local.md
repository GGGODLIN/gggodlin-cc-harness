---
# 本檔在契約測試底下：bash ~/.claude/commands/tests/daily-local-routing-contract.test.sh
description: 跑每日本機分析 workflow（按 weekday 判頻率，channel 清單以 local-analysis.js 的 CHANNELS 為準）
---

先判斷目前角色：

- 如果你已收到 workflow 分派的單一 channel 任務（含 channel 名、source 或 runner、report 路徑），就只執行該子任務，不再啟動 recap 或 Workflow，也不接手 main 的 digest／ledger 流程。轉送的 `/daily-local` 是整體請求來源，不是要求每個 channel 重啟整套分析。
- 子任務指定的報告是允許的輸出；read-only 限制的是分析來源。LLM channel 將完整正文放入 `report_markdown` 回傳，不寫報告檔；依賴落檔的狀態資料放入 `deferred_writeback`，由 main 按 hook 的 `pending_reports` 接線保存與回寫。
- 如果沒有單一 channel 任務，才由 main session 執行下列啟動步驟。

執行每日本機分析：

1. 用 Bash 取今天日期與星期：`date +'%F %u'`（%F=YYYY-MM-DD、%u=weekday 1-7）。
2. **Read `~/.claude/hooks/daily-local-analysis-trigger.sh`，照 hook 的啟動與排檔規則逐條執行。**
3. 依 hook 規則同時啟動 routed recap 背景 Bash，並呼叫 Workflow tool；Workflow `scriptPath` = `~/.claude/workflows/local-analysis.js`，`args` 必須直接傳 `{"date":"<%F 結果>","weekday":<%u 結果數字>,"external_recap":true}`。recap Bash 與 Workflow 都完成後才產 digest。

第 3 步為什麼是「去讀 hook」而不是把規則抄在這裡：那份規則是**單一來源**，抄一份到本檔就會變兩份、改一邊漏一邊。走關鍵字（「每日本機分析」）觸發時 hook 會自動注入那份規則；走本 command 時 hook 不觸發，所以要顯式去讀。兩條路因此永遠用同一份規則。

⚠️ workflow **不回傳 digest**（2026-07-30 起）——它只做偵測，回傳結構化 channel 清單 + `reconcile_cmd`。digest 與三檔排檔由 main session 產。ledger 寫回**只走腳本**（`ledger-reconcile.py` 的 `--findings` / `--decide` 配 `--apply`），不要用 Write / Edit / python 直接改 `pending-actions.jsonl`。架構理由見 `~/.claude/workflows/local-analysis.js` 的「合成 agent 已移除」註解段。
