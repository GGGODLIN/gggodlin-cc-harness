# `/review-spec` — 規格四級審查與 YAGNI 定價圖解

在規格（spec）進入拆票或實作前，依風險等級執行第 1–4 級對抗式審查與 YAGNI（砍除過度設計）需求定價，並強制隔離作者辯護理由、把所有爭議收斂到最後一輪一次拍板。完整規範見同目錄的 [`review-spec.md`](/commands/review-spec.md)。

## 運作流程圖

![/review-spec 規格四級審查與 YAGNI 定價流程](/commands/review-spec-flow.svg)

<details>
<summary>展開查看 Mermaid 結構原始碼（供 Agent／文字搜尋對照）</summary>

```mermaid
flowchart LR
  subgraph S1["Stage 1 · CLAIM 隔離與級別路由"]
    Parse["解析輸入與貫穿守則（剝除作者自評）"] --> AutoTier["未指定級別時於 Tier 1–2 自選"] --> Probe["對照七大失敗模式探針表"]
  end
  subgraph S2["Stage 2 · 分級審查與 Permit 邊界"]
    Gate1["GATE 1：Tier 分流與雙跑 Permit 邊界"] --> ClaudeTiers["Claude 側對抗審查（Tier 1–3）"]
    Gate1 -.-> ExtYagni["Tier 4 外部跨模型 ／ YAGNI 定價"]
  end
  subgraph S3["Stage 3 · 共用收斂與最後拍板"]
    Converge["共用收斂：先修誤讀與無爭議缺陷"] --> FinalTable["GATE 2：最後一輪拍板表（一列一題 a/b/c）"]
  end
  Probe --> Gate1
  ClaudeTiers --> Converge
  ExtYagni -.-> Converge
```

</details>

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`/commands/review-spec.md`](/commands/review-spec.md) | Tier 1–4 與 YAGNI 軸完整流程、貫穿守則與呈現紀律 |
| [`/agents/architecture-critic.md`](/agents/architecture-critic.md) | Tier 2／Tier 3 派出的對抗式架構審查 subagent（套用 [`/review-standards/`](/review-standards/catalog.md) 架構鏡頭） |
| [`/references/failure-mode-taxonomy.md`](/references/failure-mode-taxonomy.md) | 審查時對照的 F1–F7 失敗模式探針表 |
| [`/hooks/review-spec-tier1-nudge.sh`](/hooks/review-spec-tier1-nudge.sh) | 偵測 spec 完成時提醒執行 `/review-spec` 的 hook |
| [`/commands/tests/review-spec-execution-contract.test.sh`](/commands/tests/review-spec-execution-contract.test.sh) | 驗證自選規則、Tier 3/4 授權邊界與 YAGNI packet 隔離的契約測試 |
