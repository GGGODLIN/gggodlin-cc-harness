# `/advisor` — 跨模型單次顧問外包圖解

在不切換當前 session 主力模型的前提下，把單一架構取捨、方案盲審或卡關問題打包交給另一顆高階模型（Fable 顧問席、網頁版 GPT Pro 或 Codex CLI），只收回獨立意見與差異對照，不在本機留下任何檔案改動。完整規範見同目錄的 [`advisor.md`](/commands/advisor.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["執行 /advisor"]) --> Step0["Step 0–1：整理任務目的與材料策略\n從當前對話抽離問題背景、候選方案與必要原碼\n（不要求使用者背分類參數）"]
  Step0 --> Step2["Step 2：讀取額度並產生推薦\n檢查當前主模型與額度狀態（🔌 額度資料來源）"]
  Step2 --> Step3["Step 3：呈現三種顧問席選單並等待使用者選擇"]

  Step3 --> Pick{"使用者選定哪一席？"}
  Pick -- "未回答 / 取消" --> Stop(["停止，不派出任何顧問"])

  Pick -- "選項 1：Claude Fable 顧問席" --> Seat1["派 advisor-seat subagent\ndescription 帶 <fable-ok> 通過 hooks/fable-gate.sh"]
  Pick -- "選項 2：網頁版 GPT Pro" --> Seat2["走 🔌 ChatGPT 網頁版席位（見 WIRING.md）\n材料模式把必要原文內嵌進四段式 prompt"]
  Pick -- "選項 3：Codex CLI 獨立推理" --> Seat3["以唯讀 sandbox 執行 Codex CLI\n跑完從 rollout 檔核實 model / effort / sandbox_policy"]

  Seat1 --> Step5["Step 5：原文呈現顧問回答\n用一句話標出『顧問看法跟主 session 哪裡不同』"]
  Seat2 --> Step5
  Seat3 --> Step5

  Step5 --> Step6(["Step 6：列出分歧點供使用者逐條裁決\n（顧問本身零改檔權限）"])
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`/commands/advisor.md`](/commands/advisor.md) | Step 0–6 完整選席、四段式打包格式、收據核驗與裁決流程 |
| [`/agents/advisor-seat.md`](/agents/advisor-seat.md) | 選項 1 派出的唯讀顧問 subagent 定義檔 |
| [`/hooks/fable-gate.sh`](/hooks/fable-gate.sh) | 保護高單價 Fable 模型的 PreToolUse 守門 hook（驗證 `<fable-ok>` 標記與白名單角色） |
| [`/scripts/advisor-extract-context.py`](/scripts/advisor-extract-context.py) | 協助從 session 紀錄抽取顧問所需上下文的輔助腳本 |
| [`/config/gpt-models.env`](/config/gpt-models.env) | 外部 GPT 顧問與審查席位的模型名稱設定檔 |
