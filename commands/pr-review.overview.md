# `/pr-review` — 多軸對抗式 PR 審查與雙閘門圖解

把單一或多個 PR／分支範圍拉進隔離的 git worktree，依變更性質自動選出 Claude 側審查席位並提示可選的跨模型外部席，經授權 gate 放行後平行審查、交叉驗證、重錨行號，最後由報表投影腳本產出比較報告。完整規範見同目錄的 [`pr-review.md`](/commands/pr-review.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["執行 /pr-review"]) --> Prep["Step 1–2.06：解析目標與抓取 PR 資料\nscripts/pr-review-targets.py 處理單目標 / 多目標 / --merged\nREST 分頁拉完整變更清單（防 100 檔截斷）"]
  Prep --> Worktree["Step 2.5–2.55：建立隔離审查 Worktree\ngit worktree 對齊 PR HEAD SHA\n區分 Authored（本 PR 改動）與 Inherited（基底混入）"]
  Worktree --> SpecGate["Step 2.6–2.97：前置掃描與條件收集\n① Formal Spec Gate（抽規範條款）\n② sem 影響半徑 ＋ react-doctor 機械檢查\n③ 對照 review-standards/catalog.md 判定適用標準"]
  SpecGate --> Matrix["Step 2.98：選席矩陣與授權檢查\nscripts/pr-review-c4.py authorize-dispatch\nClaude 側席位自動放行；外部額度席需當輪確認"]

  Matrix --> Dispatch["Step 3：平行派出已選審查席\n（hooks/pr-review-c4-dispatch-gate.py 攔截未授權席位）"]

  subgraph Seats["可選審查席位（互不讀對方輸出）"]
    direction LR
    SClaude["Claude 側席位\ntypescript/python/code-reviewer\nsecurity-reviewer\nspec-compliance-reviewer"]
    SCodex["Codex 席位（選用）\nscripts/pr-review-codex-set.mjs\n一般審查軸 ＋ 對抗攻擊軸"]
    SWeb["外部網頁模型席（選用）\n🔌 ChatGPT 網頁版席位 / Gemini"]
  end

  Dispatch --> Seats
  Seats --> Verify["Step 4–4.8：交叉驗證與確定性後處理\n① 跨軸挑戰單方發現（Lone-Finding）\n② 核對變更檔案覆蓋率（ENH-A）與行號重錨（ENH-B）\n③ 對帳上一輪 PR 審查是否已修（Step 4.7）"]
  Verify --> Report["Step 5–6.5：產出比較報告與回流登記\nscripts/pr-review-report-projection.py\n（hooks/pr-review-report-write-gate.py 守門）\n漏抓類型追加至 references/failure-mode-taxonomy.md"]
  Report --> Cleanup(["Step 7：移除臨時 worktree 並還原設定"])
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`/commands/pr-review.md`](/commands/pr-review.md) | Step 1–8 完整審查步驟、報告格式與錯誤處理 |
| [`/review-standards/catalog.md`](/review-standards/catalog.md) | 34 份審查標準的主目錄（必載底線、語言專屬規則、安全性與 AI 生成變更檢查） |
| [`/scripts/pr-review-targets.py`](/scripts/pr-review-targets.py) ／ [`/scripts/pr-review-profile.py`](/scripts/pr-review-profile.py) | 多目標輸入正規化、容量門檻計算與 repo 專屬規範讀取 |
| [`/scripts/pr-review-c4.py`](/scripts/pr-review-c4.py) ＋ [`/hooks/pr-review-c4-dispatch-gate.py`](/hooks/pr-review-c4-dispatch-gate.py) | 選席授權狀態機與攔截未授權 reviewer 派工的 PreToolUse hook |
| [`/scripts/pr-review-report-projection.py`](/scripts/pr-review-report-projection.py) ＋ [`/hooks/pr-review-report-write-gate.py`](/hooks/pr-review-report-write-gate.py) | 驗證各席狀態與覆蓋率後才放行寫入報告的投影腳本與寫入守門 hook |
| [`/scripts/pr-review-codex-set.mjs`](/scripts/pr-review-codex-set.mjs) ／ [`/scripts/pr-review-gemini-web.py`](/scripts/pr-review-gemini-web.py) | 外部跨模型審查席位的啟動、輪詢與收件腳本 |
