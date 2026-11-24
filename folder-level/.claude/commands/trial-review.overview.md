# `/trial-review` — 觀察期到期檢討與摩擦消費圖解

統一盤點到期的工具／規則觀察期（trials）、累積達門檻的摩擦紀錄（friction logs）與失敗模式提案，用真實觸發數據、修法實物查證與按需歷史比對決定每項要「留（KEEP／折入）、改（MODIFY／休眠）還是撤（KILL／否決）」，落檔後經獨立審計才算結案。完整規範見同目錄的 [`trial-review.md`](/folder-level/.claude/commands/trial-review.md)。

## 運作流程圖

![/trial-review 觀察期到期檢討與摩擦消費流程](/folder-level/.claude/commands/trial-review-flow.svg)

<details>
<summary>展開查看 Mermaid 結構原始碼（供 Agent／文字搜尋對照）</summary>

```mermaid
flowchart LR
  subgraph S1["Stage 1 · 到期候選與摩擦盤點"]
    Step0["Step 0：掃描到期 Trial、達門檻摩擦與結構 lint"] --> Step1A["Step 1A：收集工具／Hook 真實行為證據"] --> Step1B["Step 1B：摩擦帳本分群、實物查證與按需歷史比對"]
  end
  subgraph S2["Stage 2 · 推薦門檻與拍板決定"]
    Gate1["GATE 1：修法實物與人類訊號推薦門檻"] --> Decide["呈現 3–4 句短背景與拍板選單"]
    Gate1 -.-> FoldIn["拍板折入規則／Skill／Hook（選用）"]
  end
  subgraph S3["Stage 3 · 歸檔與獨立審計"]
    Archive["Step 2：鎖驗證批次寫入、歸檔與索引同步"] --> Verify["GATE 2：Self-Verify 獨立審計守門閘"]
  end
  Step1B --> Gate1
  Decide --> Archive
  FoldIn -.-> Archive
```

</details>

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`/folder-level/.claude/commands/trial-review.md`](/folder-level/.claude/commands/trial-review.md) | Step 0–4 完整檢討、摩擦分群消費、歸檔與 Self-Verify 規範 |
| [`/folder-level/.claude/hooks/trial-review.sh`](/folder-level/.claude/hooks/trial-review.sh) | Session 啟動時檢查到期 trial、待審摩擦與結構 lint 並發出提醒的 hook |
| [`/folder-level/.claude/hooks/trial-archive-resources.py`](/folder-level/.claude/hooks/trial-archive-resources.py) | 將結案項目搬移至 `archived.md` 並同步更新獨立索引 `archived.index.md` 的輔助程式 |
| [`/folder-level/.claude/hooks/friction-review-state.py`](/folder-level/.claude/hooks/friction-review-state.py) | 摩擦檔 24 小時時間鎖、原文快照比對、待折／休眠批次狀態轉換、90 天退場與結構 `lint／bootstrap` 輔助程式 |
| [`/friction/PROTOCOL.md`](/friction/PROTOCOL.md) ／ [`/examples/trials/active.md`](/examples/trials/active.md) | 摩擦紀錄格式協議與觀察期帳本範例 |
