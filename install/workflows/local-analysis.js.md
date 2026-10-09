各種治理訊號（規則用量、摩擦、壞路徑、上游更新）散在不同地方，沒人會每天去看；daily-local 每天跑一次本機分析，彙整成一份報告。


入口是 `/daily-local` command（`commands/daily-local.md`）與 `hooks/daily-local-analysis-trigger.sh`；各 channel 的程式在 `social-info/scripts/local-analysis/`，報告寫到 social-info 的 `reports/local-analysis/`。原作者的 repo 路徑寫死在 `local-analysis.js` 的 `SI` 常數與各 channel 腳本裡，換位置要一起改。
