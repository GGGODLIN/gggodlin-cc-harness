<!-- Modified from the original work at https://github.com/anthropics/skills/tree/main/skills/skill-creator (Apache-2.0, copyright Anthropic, PBC). See THIRD_PARTY_NOTICES.md. -->
# `skill-creator` — Skill 撰寫與對抗式行為驗證圖解

新建或修改任何 skill／command 時的單一規範來源（SSOT）：先做三層漸進揭露結構設計，再依編輯性質分流——行為規則變更必須走新鮮 subagent 的 `RED → GREEN → REFACTOR` 實測迴圈，機械性路徑或旗標同步則走確定性檢查。完整規範見同目錄的 [`SKILL.md`](/skills/skill-creator/SKILL.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["新建或修改 skill / command"]) --> Understand["1. 盤點具體觸發情境與重用資源\n拆三層：frontmatter 摘要 → SKILL.md 主幹（<500 行）\n→ references/、scripts/、assets/"]
  Understand --> Classify{"2. 判定本次修改性質"}

  Classify -- "Mechanical Edit\n（改檔名、移路徑、同步 CLI --help 旗標）" --> MechCheck["確定性檢查（免跑 RED/GREEN）\n① 變更行所有路徑與連結存在\n② 指令旗標對照 --help\n③ grep 確認舊名稱零殘留"]
  Classify -- "Behavioral Edit 或新建\n（改規則、決策樹、觸發語、模糊分類）" --> RedPhase["3a. RED Baseline（動手改檔前！）\n派 fresh subagent 跑誘發壓力情境\n觀察未改版如何失守（讀到待測檔算無效）"]

  RedPhase --> RedCheck{"RED 是否重現問題？"}
  RedCheck -- "未重現（基線已合規）" --> StopAsk(["停下回報使用者「無法證明有問題」\n由使用者決定是否仍要改"])
  RedCheck -- "已重現缺口" --> EditSkill["3b. 撰寫 / 修改 SKILL.md\n外部指標用『如果 X，就在 Y 前讀 Z』句型\n模糊形容詞改寫為可觀察條件"]
  EditSkill --> GreenPhase["3c. GREEN 驗證\n派 fresh subagent 重跑同一壓力情境\n確認有實際工具呼叫與外部產物證據"]
  GreenPhase --> RefactorPhase["3d. REFACTOR 找漏洞\n用偷懶或邊界情境測試，修補後重跑回歸"]

  MechCheck --> SelfVerify["4. 契約測試與 Self-Verify\n跑 scripts/quick_validate.py 與專屬 contract test\n有 Self-Verify 段則過 skill-verify-auditor"]
  RefactorPhase --> SelfVerify
  SelfVerify --> Inventory(["5. 更新 skills/INVENTORY.md 登記表"])
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`SKILL.md`](/skills/skill-creator/SKILL.md) | 漸進揭露設計原則、frontmatter 規範、RED/GREEN/REFACTOR 行為驗證與本地治理規則 |
| [`references/workflows.md`](/skills/skill-creator/references/workflows.md) | 多步驟工作流與條件分支的結構設計模式 |
| [`references/output-patterns.md`](/skills/skill-creator/references/output-patterns.md) | 輸出範本與品質標準的寫法範例 |
| [`scripts/init_skill.py`](/skills/skill-creator/scripts/init_skill.py) ／ [`scripts/quick_validate.py`](/skills/skill-creator/scripts/quick_validate.py) | 初始化 skill 目錄結構與驗證 frontmatter 格式的工具腳本 |
| [`scripts/tests/skill-authoring-contract.test.sh`](/skills/skill-creator/scripts/tests/skill-authoring-contract.test.sh) | 鎖定 RED 先於改檔、確定性檢查分流與外部指標句型的契約測試 |
| [`/hooks/skill-description-gate.sh`](/hooks/skill-description-gate.sh) ／ [`/hooks/skill-verify-once-gate.py`](/hooks/skill-verify-once-gate.py) | 攔截超長 description 與保護 Self-Verify 單次審計配額的機械 hook |
