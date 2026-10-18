# `/trial-review` — 觀察期到期檢討與摩擦歸因圖解

統一盤點到期的工具／規則觀察期（trials）與累積達門檻的摩擦紀錄（friction logs），用真實觸發數據與事件歸因封包決定每項要「留（KEEP）、改（MODIFY）還是撤（KILL）」，落檔後經獨立審計才算結案。完整規範見同目錄的 [`trial-review.md`](/folder-level/.claude/commands/trial-review.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["執行 /trial-review\n（或由 hooks/trial-review.sh 到期提醒觸發）"]) --> Step0["Step 0：撈取到期候選清單\n掃描 trials/active.md 到期項目\n＋ friction-review-state.py 達門檻的摩擦帳本\n直接認領第一候選開跑（不先停下來問選哪題）"]

  Step0 --> Kind{"候選類型？"}

  Kind -- "一般工具 / Hook Trial" --> GatherTrial["Step 1A：收集觀察期行為證據\n查 git log / hook 觸發紀錄 / session 實測表現\n（只寫進文件不算採用證據）"]
  Kind -- "摩擦帳本（Friction Log）" --> GatherFriction["Step 1B：分群、來源核實與事件歸因\n① 依 target 與根因分群，核對原話與測試出處\n② 跑 scripts/friction-outcome-packet.py 打包上下文\n③ 派 routed-judge 判 NEW_ACTIONABLE / ALREADY_FIXED / NOT_SKILL_CAUSED"]

  GatherTrial --> Present["整理 3–4 句短背景＋唯一拍板問句\n（a. KEEP 轉正 / b. MODIFY 調整 / c. KILL 移除 / d. 延一輪）"]
  GatherFriction --> Present

  Present --> UserPick{"使用者拍板決定"}
  UserPick --> Step2["Step 2：結案執行\n① 更新 trials/active.md 並用 hooks/trial-archive-resources.py 歸檔至 archived.md\n② 若拍板折入規則/skill → 走 skill-creator 或 gate-authoring\n③ 漏抓案例同步回寫 references/failure-mode-taxonomy.md"]
  Step2 --> Step3["Step 3：Self-Verify 獨立審計（必跑）\n將變更清單與 rubric 交給 skill-verify-auditor\n（hooks/skill-verify-once-gate.py 限制單次配額）"]
  Step3 --> Step4(["Step 4：輸出結案總結並推進下一候選"])
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`/folder-level/.claude/commands/trial-review.md`](/folder-level/.claude/commands/trial-review.md) | Step 0–4 完整檢討、摩擦分群歸因、歸檔與 Self-Verify 規範 |
| [`/folder-level/.claude/hooks/trial-review.sh`](/folder-level/.claude/hooks/trial-review.sh) | Session 啟動時檢查到期 trial 與待審摩擦並發出提醒的 hook |
| [`/folder-level/.claude/hooks/trial-archive-resources.py`](/folder-level/.claude/hooks/trial-archive-resources.py) | 將結案項目搬移至 `archived.md` 並同步更新獨立索引 `archived.index.md` 的輔助程式 |
| [`/scripts/friction-outcome-packet.py`](/scripts/friction-outcome-packet.py) ／ [`/folder-level/.claude/hooks/friction-review-state.py`](/folder-level/.claude/hooks/friction-review-state.py) | 摩擦事件的 session 上下文安全打包器與待折門檻計數器 |
| [`/friction/PROTOCOL.md`](/friction/PROTOCOL.md) ／ [`/examples/trials/active.md`](/examples/trials/active.md) | 摩擦紀錄格式協議與觀察期帳本範例 |
