各種治理訊號（規則用量、摩擦、壞路徑、上游更新）散在不同地方，沒人會每天去看；daily-local 每天跑一次本機分析，彙整成一份報告。

入口是 `/daily-local` command（[`/commands/daily-local.md`](/commands/daily-local.md)）與 [`/hooks/daily-local-analysis-trigger.sh`](/hooks/daily-local-analysis-trigger.sh)；各 channel 的程式在 [`/social-info/scripts/local-analysis/`](/social-info/scripts/local-analysis/)，報告寫到 social-info 的 `reports/local-analysis/`。原作者的 repo 路徑寫死在 `local-analysis.js` 的 `SI` 常數與各 channel 腳本裡，換位置要一起改。

## 運作流程圖

```mermaid
flowchart TD
  Trigger(["Session 啟動或手動跑 /daily-local\nhooks/daily-local-analysis-trigger.sh 檢查當日是否已跑"]) --> StartWf["啟動 workflows/local-analysis.js\n傳入 date 與 weekday"]

  StartWf --> Filter["Phase 1：Scan（依頻率篩選到期頻道）\ndaily 每天跑 ／ weekly-tue 週二跑 ／ interval-7d 滿 7 天跑"]

  subgraph Channels["平行執行 30 個本機分析頻道"]
    direction LR
    ShellCh["Shell 頻道（直接寫報告或靜默 __SILENT__）\n• agnix-daily / skill-collision-daily\n• hash-reflow / free-pool / codex-cdp\n• rules-size-weekly / skill-upstream-check\n• failure-mode-daily / skill-changes-daily"]
    LlmCh["LLM 頻道（回傳結構化報告文字供 main 落檔）\n• recap-daily（挖掘規則糾正與違規）\n• memory-audit（記憶健康度 A–F 維度）\n• distill-weekly（提煉重複模式）"]
  end

  Filter --> Channels
  Channels --> Phase2["Phase 2：EvidenceBatchAudit\n抽樣回答紀錄 → 平行派 4 位 evidence-level-auditor\n核對宣稱是否附齊同句證據"]
  Phase2 --> Reconcile["交回主 Session 收尾與對帳\n① 寫入 pending_reports\n② 跑 ledger-reconcile.py 更新 pending-actions.jsonl（count≥3 升高等級）\n③ 產出當日 Digest（只推最需拍板的 Top 項目）"]
```

## 核心隨附檔案

| 檔案 | 角色 |
|---|---|
| [`/workflows/local-analysis.js`](/workflows/local-analysis.js) | 30 個頻道的排程條件、模型路由與兩階段（`Scan` → `EvidenceBatchAudit`）編排腳本 |
| [`/commands/daily-local.md`](/commands/daily-local.md) ／ [`/hooks/daily-local-analysis-trigger.sh`](/hooks/daily-local-analysis-trigger.sh) | 手動與自動觸發入口、落檔後的帳本對帳與 Digest 合成規則 |
| [`/social-info/scripts/local-analysis/`](/social-info/scripts/local-analysis/) | 各頻道實作腳本（含 `recap-daily.sh`、`distill-weekly.sh`、`rules-size-weekly.sh`、`ledger-reconcile.py` 等） |
| [`/cc-skill-doctor/scripts/skill-doctor-weekly.sh`](/cc-skill-doctor/scripts/skill-doctor-weekly.sh) | 每週掃描 skill 健檢與觸發健康度的子頻道腳本 |
