# `model-onboard` — 第三方模型接入與五階段評估圖解

把新的第三方模型接進本機模型池，並用五個獨立階段（接線、十二道探針、agentic 能力、真實 Claude Code 整合、回歸關卡與裁決）分離「接線漏層」「上游限流」「CC 整合退化」與「模型能力不足」，避免把環境或請求層故障誤判成模型不能用。完整規範見同目錄的 [`SKILL.md`](/skills/model-onboard/SKILL.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["接入新模型 / 新 provider"]) --> Stage1["階段一：WIRE 登記與額度盤點\n讀 references/wiring-layers.md（🔌 跨模型後端）\n實打 /v1/models 與單發請求確認 model ID\n記錄額度來源與是否跟既有模型共用額度"]
  Stage1 --> Stage2["階段二：SMOKE 十二道接線探針（必跑）\n每道預設跑 3 次，採三態判定：\nPASS（有效樣本過半）/ FAIL（200 但內容錯）/ N/A（429/5xx 請求層失敗）"]
  Stage2 --> StopBench{"停點 1：定位是否需要\nagentic 多步工具能力？"}

  StopBench -- "需要" --> Stage3["階段三：BENCH 能力評估\n讀 references/bench-suite.md\n跑多步工具鏈與真實工作量題組"]
  StopBench -- "僅單次來回（翻譯/摘要/分類）" --> SkipBench["標註『未測能力，定位僅限單次來回』"]

  Stage3 --> Stage4["階段四：LIVE 真實 CC Session 測試\n讀 references/live-session.md\n實測 context window、ToolSearch、stop hook 與風格遵從"]
  SkipBench --> Stage4

  Stage4 --> WantChain{"是否要排進\n日常免費備援鏈（free chain）？"}
  WantChain -- "是" --> RegressGate["入鏈關卡：三段回歸題組\n讀 references/regress-gate.md\n① v1 日常短任務對照凍結基準\n② v3 分析類查證題組\n③ 真實工作量盲評題組"]
  WantChain -- "否（僅保留獨立 alias）" --> Stage5

  RegressGate --> StopChain["停點 2：帶著回歸報告\n請使用者拍板 chain priority"]
  StopChain --> Stage5["階段五：VERDICT 裁決與登記\n依 references/verdict-template.md 填表\n過 skill-verify-auditor 檢查"]
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`SKILL.md`](/skills/model-onboard/SKILL.md) | 五階段主流程、入鏈關卡條件、自我檢查 rubric 與三個拍板停點 |
| [`references/wiring-layers.md`](/skills/model-onboard/references/wiring-layers.md) | 本機模型池接線層次地圖（含 🔌 [跨模型後端](/WIRING.md#跨模型後端) 接點） |
| [`references/bench-suite.md`](/skills/model-onboard/references/bench-suite.md) | 階段三多步工具鏈題組的跑法與判讀 |
| [`references/live-session.md`](/skills/model-onboard/references/live-session.md) | 階段四在真實 Claude Code session 內檢查整合層退化的步驟 |
| [`references/regress-gate.md`](/skills/model-onboard/references/regress-gate.md) | 排入日常備援鏈前的 v1／v3／真實工作量三段回歸題組規範 |
| [`references/traps.md`](/skills/model-onboard/references/traps.md) ／ [`LESSONS.md`](/skills/model-onboard/LESSONS.md) | 常見供應商限流、參數相容性與多輪工具簽章踩坑紀錄 |
| [`references/verdict-template.md`](/skills/model-onboard/references/verdict-template.md) | 最終裁決報告的固定表格模板 |
