# `agent-dispatch` — 跨外殼終端 Worker 派工圖解

在獨立的 git worktree 與終端分頁（透過 Herdr）啟動完整的終端 worker（Claude Code、Codex CLI 或 pi），一次跑完一個 repo 的整包票，讓主 session 留在原目錄只負責派工、轉達、對帳與審查。完整規範見同目錄的 [`SKILL.md`](/skills/agent-dispatch/SKILL.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["需要派獨立終端 worker"]) --> Step0["Step 0：取得當次派工同意\n讀 references/harness-recommendations.md\n列出任務、repo、worker 數、外殼、配方、治理差異"]
  Step0 --> Consent{"使用者明確回覆\n「允許這次派工」？"}
  Consent -- "未回覆 / 拒絕 / main 自做" --> Stop(["停止派工（不建 worktree、不起分頁）"])
  Consent -- "同意（綁定當次參數）" --> Step1["Step 1：確認 Herdr 身分與開工位\n驗 HERDR_PANE_ID + HERDR_WORKSPACE_ID\n準備隔離 git worktree"]
  Step1 --> Step2["Step 2：寫 brief 並啟動 worker\n依 assets/brief-template.md 寫檔（逐字標使用者原話）\n執行 scripts/start-worker.sh"]

  subgraph Launch["scripts/start-worker.sh 依外殼分流"]
    direction LR
    HClaude["Claude Code（預設）\n套用 repo hook / skill / settings"]
    HCodex["Codex CLI\n不套用 CC hook，加更新選單關閉旗標"]
    HPi["pi\n不套用 CC hook，寫入 worktree .pi 重試設定"]
  end

  Step2 --> Launch
  Launch --> Step3["Step 3：背景等待與轉達\nscripts/agent-watch.sh 等 idle / blocked / done 後喚醒 main\n轉達訊息一律加 [main] 前綴"]
  Step3 --> Step4["Step 4：收工對帳\nscripts/worker-turns.py 抽取對話紀錄\n核對 human 裁決、commit、票檔勾選與 worktree 乾淨"]
  Step4 --> Step5["Step 5：主 session 跑 review-implement\n有缺陷則接回原 session 續修；開 PR 後關閉 worker 分頁"]
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`SKILL.md`](/skills/agent-dispatch/SKILL.md) | Step 0–5 完整派工、等待、對帳與續接規範 |
| [`scripts/start-worker.sh`](/skills/agent-dispatch/scripts/start-worker.sh) | 驗證 Herdr 身分、依外殼（`claude`／`codex`／`pi`）開分頁、送出 brief、啟動背景監看並回傳 JSON 收據 |
| [`scripts/agent-watch.sh`](/skills/agent-dispatch/scripts/agent-watch.sh) | 背景等待 worker 進入 `idle`／`blocked`／`done`，只喚醒收據記載的 parent pane |
| [`scripts/worker-turns.py`](/skills/agent-dispatch/scripts/worker-turns.py) | 從指定 `session_id` 的紀錄檔分離 `[main]` 轉達與真人輸入，並取出最後交付訊息 |
| [`assets/brief-template.md`](/skills/agent-dispatch/assets/brief-template.md) | 交付給 worker 的任務 brief 範本（區分使用者原話與 main 判讀） |
| [`references/harness-recommendations.md`](/skills/agent-dispatch/references/harness-recommendations.md) | 模型 × 外殼推薦表骨架（供 Step 0 呈現同意訊息時參考） |
| [`references/herdr-notes.md`](/skills/agent-dispatch/references/herdr-notes.md) | Herdr 狀態語意、信任確認框與三種外殼續接細節筆記 |
