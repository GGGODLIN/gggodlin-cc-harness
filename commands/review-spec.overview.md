# `/review-spec` — 規格四級審查與 YAGNI 定價圖解

在規格（spec）進入拆票或實作前，依風險等級執行第 1–4 級對抗式審查與 YAGNI（砍除過度設計）需求定價，並強制隔離作者辯護理由、把所有爭議收斂到最後一輪一次拍板。完整規範見同目錄的 [`review-spec.md`](/commands/review-spec.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["執行 /review-spec [tier] <spec>"]) --> Parse["解析輸入與貫穿守則\n守則 0：CLAIM 隔離（只給 spec 與事實，不放作者自評）\n守則 1：架構視覺圖預檢（🔌 架構圖產生與審批）"]
  Parse --> HasTier{"呼叫時是否已指定\nTier（1/2/3/4/yagni）？"}

  HasTier -- "未指定 Tier" --> AutoPick["main 依『什麼時候選』欄\n在第 1、2 級間自選並立即執行\n（若符合第 3、4 級條件，於結尾附推薦指令，不代簽 permit）"]
  HasTier -- "已指定 Tier" --> RouteTier{"指定哪一級？"}
  AutoPick --> RouteTier

  RouteTier -- "Tier 1（預設地板）" --> T1["In-context 唱反調自審\n依 7 大失敗模式探針逐項挑刺"]
  RouteTier -- "Tier 2（中小型跨模組）" --> T2["派單一 architecture-critic\n（fresh context 無歷史包袱）"]
  RouteTier -- "Tier 3（核心架構 / 生產資料）" --> T3["多角度平行審查（架構＋安全＋領域）\n使用者親手送出 Tier 3 指令才可簽雙跑 permit"]
  RouteTier -- "Tier 4（關鍵高風險決策）" --> T4["外部跨模型審查\n🔌 ChatGPT 網頁版席位 / Codex CLI"]
  RouteTier -- "yagni（需求定價）" --> Yagni["組隔離 packet（spec ＋ 使用者原話對照 ＋ 研究數據）\n逐條分類：(a) 原話 / (b) 量測證據 → 保護\n(c) 模型推導 → 答不出具體損失就砍或降級"]

  T1 --> Converge["共用收斂：root / first_nail\n先區分題目誤讀、可直接修的缺陷、與真取捨"]
  T2 --> Converge
  T3 --> Converge
  T4 --> Converge
  Yagni --> Converge

  Converge --> FinalTable(["整理成最後一輪拍板表（一列一題 a/b/c）\n拍板後落檔寫入 spec 與審查紀錄"])
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`/commands/review-spec.md`](/commands/review-spec.md) | Tier 1–4 與 YAGNI 軸完整流程、貫穿守則與呈現紀律 |
| [`/agents/architecture-critic.md`](/agents/architecture-critic.md) | Tier 2／Tier 3 派出的對抗式架構審查 subagent（套用 [`/review-standards/`](/review-standards/catalog.md) 架構鏡頭） |
| [`/references/failure-mode-taxonomy.md`](/references/failure-mode-taxonomy.md) | 審查時對照的 F1–F7 失敗模式探針表 |
| [`/hooks/review-spec-tier1-nudge.sh`](/hooks/review-spec-tier1-nudge.sh) | 偵測 spec 完成時提醒執行 `/review-spec` 的 hook |
| [`/commands/tests/review-spec-execution-contract.test.sh`](/commands/tests/review-spec-execution-contract.test.sh) | 驗證自選規則、Tier 3/4 授權邊界與 YAGNI packet 隔離的契約測試 |
