# `implement` — 票券執行與收尾控制流圖解

把已拆好的票券（tickets）按依賴順序逐批實作、強制對齊測試義務，並在收尾時完成跨軸審查與架構圖核對。完整規範見同目錄的 [`SKILL.md`](/skills/implement/SKILL.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["開始 /implement"]) --> Preflight["1. Preflight 盤點\n讀取 spec / ADR / design / 票券依賴圖\n計算無阻塞 frontier"]
  Preflight --> AskOnce["一次問完執行參數\n① 執行方式：Subagent-Driven 或 Inline\n② 測試路線：tdd / regression-closeout / 逐票決定"]
  AskOnce --> Manifest["寫入 TDD 決策清單\nscripts/tdd-policy.mjs record-batch\n（hooks/matt-tdd-gate.sh 守門）"]
  Manifest --> Frontier{"還有未完成\nfrontier 票？"}

  Frontier -- "有（Inline）" --> InlineWork["主 session 逐票實作\n若該票標 required → 先跑 /tdd"]
  Frontier -- "有（Subagent-Driven）" --> DispatchWorker["平行派 routed-impl subagent\nPrompt 必帶票檔絕對路徑\n（禁 worker 再向下派 agent）"]
  InlineWork --> TickVerify["單票驗收＋勾選票檔\n更新 Verification Log"]
  DispatchWorker --> TickVerify
  TickVerify --> Frontier

  Frontier -- "全部完成" --> Closeout1["3. Closeout 收尾\n步驟 1–2：共用比較器自檢＋全套測試"]
  Closeout1 --> Closeout3["步驟 3：條件式安全假設探針\n（碰外部 API / SDK / 硬體限制時觸發）"]
  Closeout3 --> Closeout4["步驟 4：程式碼與範圍審查\n語言 reviewer ＋ review-implement（Scope / YAGNI）"]
  Closeout4 --> Repair{"有認證缺陷？"}
  Repair -- "有（每根因最多 2 次）" --> FixLoop["最小修補 → 重跑全套測試\n→ 只重審受影響軸"]
  FixLoop --> Repair
  Repair -- "無（PASS / WAIVED）" --> VisualGate["步驟 5：架構視覺 Gate\n🔌 架構圖產生與審批（見 WIRING.md）\n核對 intent 圖 vs actual-delta 圖"]
  VisualGate --> Done(["步驟 6：交付最終摘要\n（不自動推播或關閉終端）"])
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`SKILL.md`](/skills/implement/SKILL.md) | 主流程定義（Preflight、Frontier 迴圈、Closeout 6 步） |
| [`scripts/tdd-policy.mjs`](/skills/implement/scripts/tdd-policy.mjs) | 產生與查詢批次測試決策清單（`manifest`），供 [`/hooks/matt-tdd-gate.sh`](/hooks/matt-tdd-gate.sh) 在改碼前攔截未宣告 TDD 義務的寫入 |
| [`references/regression-closeout.md`](/skills/implement/references/regression-closeout.md) | 選擇「實作後補回歸測試」路線時的收尾檢查清單 |
| [`/skills/review-implement/SKILL.md`](/skills/review-implement/SKILL.md) | Closeout 步驟 4 呼叫的 Scope／YAGNI 對抗式審查流程 |
| [`/WIRING.md#架構圖產生與審批`](/WIRING.md#架構圖產生與審批) | Closeout 步驟 5 的 🔌 接線點說明（預設推薦 Archify ＋ Plannotator） |
