# Effort / 思考深度 — 使用者側操作參考

2026-07-06 從 `~/.claude/rules/common/performance.md` 搬出（always-on context 稅審計）；規則檔只留給 agent 的指令、本檔留給使用者查操作。

- 思考深度用 effort 控制：`/effort low|medium|high|xhigh|max`（session 內切換），或 settings.json `effortLevel` 持久化（`max` / `ultracode` 僅 session 有效）
- 單回合加深：prompt 加 `ultrathink` 關鍵字；口語引導「think carefully step by step」（加深）/「respond quickly」（變淺）
- 思考開關：Option+T，或 settings `alwaysThinkingEnabled`；展開思考視圖 Ctrl+O
