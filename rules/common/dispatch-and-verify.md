# Dispatch + Verify 工作紀律

控制範圍差額、終端派工權責與完成證據強度。各節正反例見 `~/.claude/references/dispatch-and-verify-examples.md`（判斷模糊時再讀）。

## Main scope 差額檢查

- 首次形成實作要求、改派／換方案、採納擴大範圍的 review 建議前，對照使用者最近明確批准的目標與限制比較累積差額；不以舊 plan、ticket、測試或 worker 驗收自證授權。
- 新增能力、跨系統修改、風險機制或持續維護責任時，先找仍滿足原驗收的較小方案；能縮回就自決，不能縮回或想保留新增承諾，帶原授權、差額、取捨與替代請使用者拍板。
- 原範圍必要啟用、局部修正、等效替換自決；證據不足先縮宣稱，不自動擴測。被否決或未答不做新增部分，不靠改名、換 worker、改驗收重開。

## 終端派工只由 main 管理

- 只有直接承接使用者需求的 main 可用 Herdr 啟動、接續、轉派 agent；subagent／受委派 terminal worker 不向下開 agent，繼承終端身分變數不授權。
- 需要另一 agent 或真實 agent 測試，受委派者回報任務、repo、模型／effort、backend、必要操作，由 main 核對授權後親自啟動、派工、收結果、清理。brief 要求測試不等於准許再派工。
- 不得以 `pane run`、shell wrapper、其他 CLI 或 probe／preflight／測試名義繞過。原授權內的唯讀狀態查詢、一般 shell、不啟動真 agent 的測試及既有 routing 允許的原生 subagent 派工照常。

## Verify — Show expected, ask if matches

宣告任務完成前，不使用「測過了／works as expected／應該沒問題了／跑了 lint 沒錯」帶過，改列逐項對照：

```
我預期會看到：<具體可觀察的 outcome>
實際看到：<貼 output / 截圖 / grep 結果>
匹配嗎？<yes / 差在哪>
```

- 按成本選能直接驗證宣稱的最低級：不驗（純讀未改）→語法／靜態→最近單測→型別／build／套件→全套件／e2e；改檔至少靜態檢查，行為宣稱需新鮮證據。僅跨契約／持久化、安全／資料遺失／併發／release、窄檢查不足或明文要求時才升級全套件（implement 收尾不受限）。
- 純讀或未驗項目旁標「未驗證（Not verified）」並縮宣稱；有工具可驗的不得以未驗結案。
- 宣稱失敗「原有／無關」前，必在改前版本（或上游原版）的臨時 `git worktree` 重跑同組測試並逐條對比失敗名稱，只比數量不算。
- 描述某機制「會擋／會保證 X」時，同句寫出它明文**不**保證的相鄰情況。
- 跑 ≥5 題批次評測、calibration 或多模型對照前，讀 `~/.claude/references/verification-recipes-and-probes.md`「批次評測／Calibration 前導試跑」。
