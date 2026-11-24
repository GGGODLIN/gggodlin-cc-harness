# Trial 觀察期紀律

- 開新 trial（工具 / 觀察期 / hook 試用 / 任何 review 期觀察）→ 必 append H2 entry 到 `~/Desktop/projects/.claude/trials/active.md`——它是 trial-review.sh hook 提醒的**唯一** ledger、漏登 = 漏接提醒，不能只設被動標記在 memory / docs。寫入前先讀 active.md 檔頭的格式正本照填
- Review 日**預設開案 +7 天**，使用者另指定才用別的天期；觀察窗內樣本不足時，review 日照常跑並用「延一輪」處理
- **自建工具上線比照外部工具開 trial**：自己寫的 CLI / script / hook 接進日常路徑就開——symlink 進 PATH、寫進 always-on 規則、掛 launchd 排程、註冊成 MCP，任一即算上線。沒有安裝指令可包的自建工具，直接 append H2 + 寫 detail 檔。漏了這條，自建工具不觸發任何 trial 入口，也就沒有 review 日會問「它到底有沒有在用」
