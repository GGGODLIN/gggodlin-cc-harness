---
paths:
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
---
# TypeScript/JavaScript Testing

> This file extends the Testing section in `~/.claude/CLAUDE.md` with TypeScript/JavaScript specific content.

## E2E Testing

- 瀏覽器 E2E 先經 `e2e-route` 入口選路：**TesterArmy `e2e`** 為新版框架，**Playwright** 為舊版流程。
- 既有 Playwright 案例、設定與依賴保留原位，不因選用新版而批量遷移；新增或擴充常駐案例時依當次選定的套件目錄撰寫。

