# `/trial-review` — 觀察期到期檢討與摩擦歸因圖解

統一盤點到期的工具／規則觀察期（trials）與累積達門檻的摩擦紀錄（friction logs），用真實觸發數據與事件歸因封包決定每項要「留（KEEP）、改（MODIFY）還是撤（KILL）」，落檔後經獨立審計才算結案。完整規範見同目錄的 [`trial-review.md`](/folder-level/.claude/commands/trial-review.md)。

## 運作流程圖

![/trial-review 觀察期到期檢討與摩擦歸因流程](/folder-level/.claude/commands/trial-review-flow.svg)

<details>
<summary>展開查看 Mermaid 結構原始碼（供 Agent／文字搜尋對照）</summary>

```mermaid
flowchart LR
  subgraph S1["Stage 1 · 到期候選與摩擦盤點"]
    Step0["Step 0：掃描到期 Trial 與達門檻摩擦帳本"] --> Step1A["Step 1A：收集工具／Hook 真實行為證據"] --> Step1B["Step 1B：摩擦帳本分群與來源權威核對"]
  end
  subgraph S2["Stage 2 · 事件歸因與拍板決定"]
    Gate1["GATE 1：事件歸因封包與規則變更分類閘"] --> Decide["呈現 3–4 句短背景與 KEEP/MODIFY/KILL 選單"]
    Gate1 -.-> FoldIn["拍板折入規則／Skill／Hook（選用）"]
  end
  subgraph S3["Stage 3 · 歸檔與獨立審計"]
    Archive["Step 2：搬移至 archived.md 並更新索引"] --> Verify["GATE 2：Self-Verify 獨立審計守門閘"]
  end
  Step1B --> Gate1
  Decide --> Archive
  FoldIn -.-> Archive
```

</details>

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`/folder-level/.claude/commands/trial-review.md`](/folder-level/.claude/commands/trial-review.md) | Step 0–4 完整檢討、摩擦分群歸因、歸檔與 Self-Verify 規範 |
| [`/folder-level/.claude/hooks/trial-review.sh`](/folder-level/.claude/hooks/trial-review.sh) | Session 啟動時檢查到期 trial 與待審摩擦並發出提醒的 hook |
| [`/folder-level/.claude/hooks/trial-archive-resources.py`](/folder-level/.claude/hooks/trial-archive-resources.py) | 將結案項目搬移至 `archived.md` 並同步更新獨立索引 `archived.index.md` 的輔助程式 |
| [`/scripts/friction-outcome-packet.py`](/scripts/friction-outcome-packet.py) ／ [`/folder-level/.claude/hooks/friction-review-state.py`](/folder-level/.claude/hooks/friction-review-state.py) | 摩擦事件的 session 上下文安全打包器與待折門檻計數器 |
| [`/friction/PROTOCOL.md`](/friction/PROTOCOL.md) ／ [`/examples/trials/active.md`](/examples/trials/active.md) | 摩擦紀錄格式協議與觀察期帳本範例 |
