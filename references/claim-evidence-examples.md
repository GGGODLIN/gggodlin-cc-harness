# 宣稱與證據層級對位 — 舉例集

`~/.claude/CLAUDE.md`「工作紀律」證據對位規則的完整舉例，2026-07-06 從 always-on 搬出（context 稅審計）。判斷模糊時讀本檔對照。

- 「完成 / 全部 / 完整掃過 / 已覆蓋」的枚舉指令：`grep -c` / `ls | wc -l` 等計數輸出
- range 讀檔後的「某段沒有 X」反例（2026-09-05）：`sed -n '15,36p' SKILL.md` 後宣稱「preflight 整段讀完確認沒抓 commit」，實際 `feature_base_sha` 在第 50 行、同段 Done 條件內；正確寫法是「第 15–36 行內沒看到 X，第 37 行起未讀」，或讀到下一個同級標題再下結論
- 「機制能抓到 / 會運作」：要至少一次**真實資料**的命中測試輸出；語法檢查（`bash -n` / `node --check`）不算
- 行為 / 頻率 / 採用 / 成熟度宣稱的行為數據：session jsonl 計數 / git log / 實際執行輸出；memory 與 md 只能撐「存在 / 設計意圖」級宣稱，拿不到數據就明寫「庫存上有、採用未驗證」
- 「沒做的部分」條目類型：主動跳過的 file / 認定 out-of-scope 的 edge case / 看到但沒碰的相關問題；無條目 = 已主動驗證 0 個 silent skip
- trivial task 免列定義：< 3 行 / 純改字 / 純 typo
- Remote ground truth 操作細節：查 PR 狀態 / feature ship / branch 差異前先 `git fetch origin <branch>`；想寫「保守保留」「無法 stale-check」「未 archive 不確定」前先跑一次驗證（grep / git log / api 三秒事）
- status claim 對偶出處：[[feedback_memory_not_evidence_for_behavior_claims]]——STATE.md / docs / memory 寫的「PR OPEN / 未 ship / 未 archive / 未發布」屬 claim，要 API 查詢 / `git log` / master grep 才算 evidence
- 「現有 code 缺 X」先搜的工具現況：semble 已全電腦裝、所有 repo 第一次 search 自動 index（~250ms）
- 枚舉不用裸 `grep -r` 的原因：Bash tool 的 `grep` 是 CC 注入的 ugrep shim、帶 `--ignore-files`，同一份資料會隨 cwd 與路徑寫法回出不同計數，且假陰性方向是「看起來乾淨」；用 `command grep -r` 或 `find … -print0 | xargs -0 command grep -l` 繞過（2026-09-30 從 CLAUDE.md 證據對位段搬出）
