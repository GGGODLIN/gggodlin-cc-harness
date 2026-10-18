<!-- Modified from the original work at https://github.com/anthropics/skills/tree/main/skills/skill-creator (Apache-2.0, copyright Anthropic, PBC). See THIRD_PARTY_NOTICES.md. -->
# `skill-creator` — Skill 撰寫與對抗式行為驗證圖解

新建或修改任何 skill／command 時的單一規範來源（SSOT）：先做三層漸進揭露結構設計，再依編輯性質分流——行為規則變更必須走新鮮 subagent 的 `RED → GREEN → REFACTOR` 實測迴圈，機械性路徑或旗標同步則走確定性檢查。完整規範見同目錄的 [`SKILL.md`](/skills/skill-creator/SKILL.md)。

## 運作流程圖

![skill-creator 漸進揭露與對抗式行為驗證流程](/skills/skill-creator/skill-creator-flow.svg)

<details>
<summary>展開查看 Mermaid 結構原始碼（供 Agent／文字搜尋對照）</summary>

```mermaid
flowchart LR
  subgraph S1["Stage 1 · 三層結構與修改分類"]
    Step1["1. 盤點觸發情境與三層漸進揭露"] --> Step2["2. 判定行為規則或機械性修改"] --> Author["依可觀察條件撰寫指引條文"]
  end
  subgraph S2["Stage 2 · RED-GREEN-REFACTOR 閘門"]
    Gate1["GATE 1：改檔前新鮮 Subagent RED 基線"] --> GreenRef["GREEN 實測與 REFACTOR 補洞"]
    Gate1 -.-> Mech["機械性修改確定性檢查路線（選用）"]
  end
  subgraph S3["Stage 3 · 契約測試與庫存登記"]
    Step4["4. 執行專屬契約測試與格式驗證"] --> Verify["GATE 2：Self-Verify 單次審計與庫存登記"]
  end
  Author --> Gate1
  GreenRef --> Step4
  Mech -.-> Step4
```

</details>

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`SKILL.md`](/skills/skill-creator/SKILL.md) | 漸進揭露設計原則、frontmatter 規範、RED/GREEN/REFACTOR 行為驗證與本地治理規則 |
| [`references/workflows.md`](/skills/skill-creator/references/workflows.md) | 多步驟工作流與條件分支的結構設計模式 |
| [`references/output-patterns.md`](/skills/skill-creator/references/output-patterns.md) | 輸出範本與品質標準的寫法範例 |
| [`scripts/init_skill.py`](/skills/skill-creator/scripts/init_skill.py) ／ [`scripts/quick_validate.py`](/skills/skill-creator/scripts/quick_validate.py) | 初始化 skill 目錄結構與驗證 frontmatter 格式的工具腳本 |
| [`scripts/tests/skill-authoring-contract.test.sh`](/skills/skill-creator/scripts/tests/skill-authoring-contract.test.sh) | 鎖定 RED 先於改檔、確定性檢查分流與外部指標句型的契約測試 |
| [`/hooks/skill-description-gate.sh`](/hooks/skill-description-gate.sh) ／ [`/hooks/skill-verify-once-gate.py`](/hooks/skill-verify-once-gate.py) | 攔截超長 description 與保護 Self-Verify 單次審計配額的機械 hook |
