---
description: 更新指定 dir（或 cwd）的 docs/owner/STATE.md — 看對話 + git + PR API 推斷進度提 patch
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/beads-task-graph.test.sh -->

# State Update

更新 `<dir>/docs/owner/STATE.md`，`<dir>` 解析方式：

- Invoke 時帶 path arg（如 `/state-update <dir>` 或 prompt 內指定）→ 用該 path
- 未帶 → 用 cwd

`<dir>` 必須有 `.git`（git worktree 算）。否則輸出 `BD_CAPTURE: not-evaluated not a git project` 後退出。

## 流程

1. **Read** `<dir>/docs/owner/STATE.md`
   - 不存在 → 跳到 **Step 8 (Create)**
   - 路徑存在但 Read 失敗 → 輸出 `BD_CAPTURE: not-evaluated STATE read failed` 後退出
   - 存在且讀取成功 → 繼續

2. **Ship/merge 分流**
   - 若 frontmatter `current_change` 對應的 change 已 merge / ship（對話歷史、`git log` 訊息顯示）→ 提示 user「該 change 已 ship、改走 `/state-archive`」，輸出 `BD_CAPTURE: not-evaluated change already shipped` 後退出
   - 不確定 → 繼續

3. **推斷現況**
   - 對話歷史（最近做了什麼決策、卡哪）
   - `git -C <dir> log -10 --oneline`
   - `git -C <dir> status --short`
   - `git -C <dir> rev-parse --abbrev-ref HEAD`

4. **PR Stale-check**（Bitbucket repo 限定）
   - 先 `git -C <dir> fetch origin master --quiet`（也試 `main` fallback；網路失敗 graceful skip）— 本地 ref 可能 stale、stale-check 前要對齊 remote（[[CLAUDE.md「remote master = ground truth」]]）
   - 推 workspace/repo：`git -C <dir> remote get-url origin | sed -E 's#.*bitbucket\.org/([^/]+)/([^/]+)\.git$#\1/\2#'`
   - 非 Bitbucket（GitHub / GitLab / 無 origin）→ skip 整段 Step 4、不報錯
   - Grep PR id：`grep -oE "pull-requests/[0-9]+|#[0-9]{4,5}\b" <dir>/docs/owner/STATE.md | grep -oE "[0-9]+" | sort -u`
   - 對每個 PR id：`bash ~/.claude/skills/bitbucket-pr-review/scripts/<bitbucket-api-helper> /repositories/<workspace>/<repo>/pullrequests/<id> | jq -r .state`
   - API 回 ERR / null / 404 → 該 id 是訂單號或別的東西，skip 該 id
   - 找該 PR ref 在 STATE.md 內的第一個 mention、看上下文 100 char 內有沒有 OPEN / MERGED / DECLINED keyword
   - keyword 跟 API state 不一致 → 列進 Step 5 "Stale items"
   - Token 沒設 / 網路失敗 → graceful skip 整個 Step 4，不阻斷主流程

4.5. **Openspec / branch / feature stale-check**（無 PR ref 也要查）
   - 補 Step 4 「沒寫 PR ref 的 carry-over item」缺口（real-world case：2026-06-24 quantity-limit 整 feature 在 STATE 標「未 archive」、實際 master 已發布 + flag 退役 6 天，因為 STATE 沒寫 PR 號 Step 4 完全漏掉）
   - Grep STATE.md 提到的 openspec change dir：`grep -oE "openspec/changes/[a-z0-9-]+/" <dir>/docs/owner/STATE.md | sort -u`
   - Grep STATE.md 提到的 branch ref：`grep -oE "(feat|fix|refactor|chore|docs)/[a-z0-9-]+" <dir>/docs/owner/STATE.md | sort -u`
   - 對每個 change name / branch name 抽 keyword（去掉前綴 `feat/` / `openspec/changes/`、用 `-` 拆字）→ 跑兩 query：
     - `git -C <dir> log master --oneline -i --grep="<keyword>" | head -10`（找 merge commit）
     - `git -C <dir> grep -l "<CamelCase 或 snake_case 的核心 symbol>" master -- '*.ts' '*.tsx' '*.js' '*.cljs'`（找 master 主檔案）
   - 兩 query 都有 hit = 候選整段移除 / 標 SHIPPED；只有 git log 有 hit = 候選降級為 reminder；都無 hit = 仍 carry-over
   - 列進 Step 5 "Stale items" 附 grep 證據

5. **Propose patch**：列建議改動、每項標 reason：
   - frontmatter (`current_change` / `status` / `next_action` / `last_session`)
   - Recent Decisions（新增）
   - Blockers（新增 / 移除 / 變狀態）
   - Resume Notes（覆寫成「下次開 session 該做什麼」）
   - **⚠️ Stale items**（Step 4 抓到的）：每條附「STATE.md 標 X、API 真實 Y」對照

6. **Wait for confirmation**：user yes / 修改 / 拒絕。若 user 拒絕或沒有任何寫入，輸出 `BD_CAPTURE: not-evaluated STATE patch not applied` 後退出

7. **Confirm 後 Edit 寫入**
   - 用 Edit 精確改 section、**不要 Write 覆蓋整檔**（會把 user 手動維護的其他段落洗掉）
   - User 給過的精確值（DSN / port / 完整命令列 / 路徑 / seed / version pin）逐 byte 照抄
   - 逐項記錄哪些 Edit 已成功；任一 Edit 失敗或只有部分 Edit 成功 → 停止後續 Edit、不進 Step 7.5 / Step 9，列出已寫入／未寫入項目並固定輸出 `BD_CAPTURE: not-evaluated STATE patch incomplete`
   - 全部 Edit 成功後接 **Step 7.5（stall 計數維護）**，再進 **Step 9（bd 條件捕捉）**

7.5. **Stall 計數維護**（催辦 bookkeeping；resume-session 讀 `stall:` ≥3 時升級成拍板問句）
   - 對象＝追蹤表的開放支線 row（與 Step 9 候選同母體：next_action、Blockers、Resume Notes、Follow-ups 的追蹤列）。marker 為 row 尾 HTML 註解 `<!-- stall:N -->`，與 `<!-- bd:<id> -->` 並存互不影響
   - 本輪 patch 有實質更新的 row → 移除其 stall marker（歸零）；未觸及的既有追蹤 row → N+1（無 marker 視為 0、寫入 `<!-- stall:1 -->`）
   - 計數註解是純機器 bookkeeping、不動 row 文字：直接 Edit、不另走一輪確認（Step 6 確認保護的是內容，不含計數註解）；回報末尾附一行摘要（例：`STALL: +1 ×3（最高 stall:2）; reset ×1`）
   - user 拒絕 patch（Step 6 退出）→ 本輪不計、不動任何 marker。已知限制：零 patch 輪不經過本步、不計輪——活躍 repo 裡其他 row 幾乎每輪有變動，可接受
   - 完成判準：本輪結束時每個追蹤 row 恰有 0 或 1 個 stall marker，且被更新的 row 為 0 個。完成後接 Step 9

8. **Create from template**（STATE.md 不存在時）
   - Derive 內容自當前對話 / git status / git log，先產生完整 draft 給 user；跳過 Step 4 / 5（新檔無 stale 可驗）
   - 確認前不得建立目錄、改 .gitignore 或寫檔。user 拒絕 → 輸出 `BD_CAPTURE: not-evaluated STATE create not approved` 後退出
   - User 確認完整 draft 後才依序執行：
     1. `mkdir -p <dir>/docs/owner`
     2. `grep -qxF 'docs/owner/' <dir>/.gitignore 2>/dev/null || { [ -s <dir>/.gitignore ] && [ -n "$(tail -c1 <dir>/.gitignore)" ] && echo >> <dir>/.gitignore; echo 'docs/owner/' >> <dir>/.gitignore; }`
     3. Write 建立 STATE.md
   - 寫入成功後接 **Step 9（bd 條件捕捉）**；任一建立動作失敗 → 輸出 `BD_CAPTURE: not-evaluated STATE create failed` 後退出

9. **條件式 bd 支線捕捉**（常態接線；2026-08-07 beads trial KEEP 結案）
   - 候選只取本次 user 已確認 patch 中**新增或實質更新**的 `next_action`、Blockers、Resume Notes、Follow-ups；不要重掃整份 STATE.md。只有候選合計含 **≥2 條彼此獨立或互卡的開放支線**（各自可獨立推進、或明確在等另一條）才捕捉。單一普通 Follow-up 不建庫
   - 未達門檻 → 回報末尾固定輸出 `BD_CAPTURE: not-needed`
   - 無法評估（例如 user 未確認 patch、STATE.md 沒有成功寫入）→ 固定輸出 `BD_CAPTURE: not-evaluated <原因>`
   - 達門檻時（STATE.md prose 照舊完整寫，bd 只是附加索引、不取代任何文字）：
     1. **preflight 在任何 bd mutation 前完成**：重新 Read 整份 STATE.md，掃**整份 STATE.md 所有 marker**並建立 `id → row` map；任何 id 出現於兩個 row → `BD_CAPTURE: skipped-error duplicate-source-id <id>; created none` 後停止。再按精確標題分組所有無 marker 候選；同一輪有兩個以上候選同名 → `BD_CAPTURE: skipped-error duplicate-source-title <標題>; created none` 後停止
     2. `<dir>/.beads/` 不存在且 STATE 已有 marker → `BD_CAPTURE: skipped-error stale-marker missing-beads-db; created none`；沒有 marker 才跑 `bd init --stealth`
     3. 跑 `bd list --json --readonly --limit 0` 全量讀取既有 beads，client-side 排除 closed / terminal 項目。接著在仍未做 create/update 前，逐一驗證所有候選既有 marker：id 必須存在且未關閉；否則 `BD_CAPTURE: skipped-error stale-marker <id>; created none`，保留原 row 等 user 修復、不自動重建
     4. 以整份 STATE 的 marker id 初始化 `used_ids`。對**所有無 marker 候選先完成綁定規劃**，此階段不得 create/update：對 client-side 未關閉集合比對精確標題，0 筆規劃 create、恰好 1 筆規劃沿用、>1 筆 → `BD_CAPTURE: skipped-error ambiguous-title-match <標題>; created none`。規劃沿用的 id 若已在 `used_ids` → `duplicate-source-id`，不得共用
     5. 全部綁定規劃無誤後才依固定順序執行：有 marker 的候選用 `bd update` 同步標題、priority、defer / due；規劃沿用者沿用該 id；規劃 create 者執行 `bd create`，成功後把新 bead **立即加入 client-side 未關閉集合**，再處理下一候選
     6. 將沿用或新建的 id 用 Edit 回填到對應 STATE row：`<!-- bd:<id> -->`；同一 row 已有 marker 時只更新、不追加第二個。Edit 失敗 → 先 rollback 本輪新插入 marker，再重新 Read 驗證這些 marker 已移除；驗證成功輸出 `BD_CAPTURE: skipped-error marker-write-failed rollback-ok <id>; created <已建立 id 或 none>`，驗證失敗輸出 `BD_CAPTURE: skipped-error marker-write-failed rollback-failed <id>; created <已建立 id 或 none>`，不得輸出 created / existing 成功終態
     7. 每次成功綁定後才把 id 加進 `used_ids`，並記錄本輪新插入的 marker 供失敗 rollback；互卡支線才補 `bd dep add <被卡者> <前置>`；日期表示「此前不值得出現」用 defer，只有硬截止才用 due
     8. 所有候選處理完後重新 Read STATE.md，做**全部 marker 回讀驗證**：每個候選恰有一個 marker、所有 id 跨整份 STATE row 唯一、每個 id 都存在且未關閉。任一不符 → 先移除本輪新插入的 marker 並驗證 rollback，再輸出 `BD_CAPTURE: skipped-error marker-verify-failed; created <已建立 id 或 none>`；rollback 失敗時原因加 `rollback-failed`
   - 只有全部 bd 操作與全部 marker 回讀驗證都成功，才可輸出成功終態：所有候選都是既有任務 → `BD_CAPTURE: existing <id 列表>`；至少建立一筆 → `BD_CAPTURE: created <新 id 列表>; existing <沿用 id 列表或 none>`
   - 任一 bd 指令、marker Edit 或回讀驗證失敗 → 不 retry、不阻塞 STATE.md 收尾，固定輸出 `BD_CAPTURE: skipped-error <原因>; created <已建立 id 或 none>`，不得把部分成功冒充完整捕捉
   - ⚠️ `bd close` 必帶 `--reason`（位置參數形式是 silent no-op）
   - `bd remember` 不用
   - 本步驟是 bd 檢查點的**唯一 owner**：save-session 經 Step 6 dispatch 到這裡，只驗收 `BD_CAPTURE` 收據，不自行執行 `bd create`

## 規則

- 不要 commit STATE.md
- STATE.md 是 gitignored、動了不影響 team
- 已有檔案 → incremental update（Edit），不要 Write 整檔
- User 給過的精確值逐 byte 照抄、不要摘要改寫
- Stale-check 對訂單號 / 非 PR id 自動 graceful skip（API ERR 處理）

## Template（新建用）

```markdown
---
current_change: <change/feature name, e.g. openspec change dir name>
status: planning|executing|verifying|blocked
next_action: <one sentence — the exact next step>
last_session: YYYY-MM-DD
---

## Current Position
Branch: <branch>
<spec/plan pointer if any>
Phase: <if applicable>

## Recent Decisions
- YYYY-MM-DD: <decision> — <why>

## Blockers
- <blocker or "none">

## Resume Notes
<next session 開頭第一件事>
```
