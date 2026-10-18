各種治理訊號（規則用量、摩擦、壞路徑、上游更新）散在不同地方，沒人會每天去看；daily-local 每天跑一次本機分析，彙整成一份報告。

入口是 `/daily-local` command（[`/commands/daily-local.md`](/commands/daily-local.md)）與 [`/hooks/daily-local-analysis-trigger.sh`](/hooks/daily-local-analysis-trigger.sh)；各 channel 的程式在 [`/social-info/scripts/local-analysis/`](/social-info/scripts/local-analysis/)，報告寫到 social-info 的 `reports/local-analysis/`。原作者的 repo 路徑寫死在 `local-analysis.js` 的 `SI` 常數與各 channel 腳本裡，換位置要一起改。

## 運作流程圖

![local-analysis（/daily-local）30 頻道本機治理分析流程](/workflows/local-analysis-flow.svg)

<details>
<summary>展開查看 Mermaid 結構原始碼（供 Agent／文字搜尋對照）</summary>

```mermaid
flowchart LR
  subgraph S1["Stage 1 · 觸發與 Shell 頻道掃描"]
    Trigger["Session 啟動或手動 /daily-local"] --> Phase1["Phase 1：依頻率篩選當日到期頻道"] --> ShellCh["平行執行確定性 Shell 掃描頻道"]
  end
  subgraph S2["Stage 2 · LLM 頻道與證據審計"]
    Gate1["GATE 1：Phase 2 宣稱證據層級抽樣審計"] --> LlmCh["執行高判斷力 LLM 分析頻道"]
    Gate1 -.-> Weekly["每週發布候選與上游漂移巡檢"]
  end
  subgraph S3["Stage 3 · 帳本對帳與 Digest"]
    Reconcile["ledger-reconcile.py 待辦帳本對帳升級"] --> Digest["GATE 2：主 Session 落檔與 Top 拍板摘要"]
  end
  ShellCh --> Gate1
  LlmCh --> Reconcile
  Weekly -.-> Reconcile
```

</details>

## 核心隨附檔案

| 檔案 | 角色 |
|---|---|
| [`/workflows/local-analysis.js`](/workflows/local-analysis.js) | 30 個頻道的排程條件、模型路由與兩階段（`Scan` → `EvidenceBatchAudit`）編排腳本 |
| [`/commands/daily-local.md`](/commands/daily-local.md) ／ [`/hooks/daily-local-analysis-trigger.sh`](/hooks/daily-local-analysis-trigger.sh) | 手動與自動觸發入口、落檔後的帳本對帳與 Digest 合成規則 |
| [`/social-info/scripts/local-analysis/`](/social-info/scripts/local-analysis/) | 各頻道實作腳本（含 `recap-daily.sh`、`distill-weekly.sh`、`rules-size-weekly.sh`、`ledger-reconcile.py` 等） |
| [`/cc-skill-doctor/scripts/skill-doctor-weekly.sh`](/cc-skill-doctor/scripts/skill-doctor-weekly.sh) | 每週掃描 skill 健檢與觸發健康度的子頻道腳本 |
