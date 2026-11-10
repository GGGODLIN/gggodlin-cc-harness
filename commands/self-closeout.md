---
description: 工作 session 任務收尾時，把「本 session 自己改的檔」commit、push（個人 repo）或留在 feature branch（公司 repo），不動其他 session 的東西。Use when 本 session 的任務已完成並驗證、準備回報結案；或使用者說「收掉你的部分」「self closeout」。Do not use for 全機收尾（那是使用者手打的 `/git-closeout`）、merge conflict、PR review，或任務尚未驗證完成的中途 commit。
argument-hint: 不帶參數；範圍由 closeout-provenance.py --self-repos 決定
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/self-closeout-contract.test.sh -->

# Self Closeout

收自己的桌子，不碰別人的。範圍不是 cwd，是本 session 實際寫過的每個 repo，加上兩個固定共用 repo（`~/.claude`、`~/Desktop/projects/.claude`）；`~/.claude` 常從其他目錄被順手改到，只看 cwd 會漏掉它。

三類東西各有收法，不要用同一個條件判：

- **共用集合**（`memory/`、`trials/`、`friction/`、各 skill 的 `friction-log.md`、`references/failure-mode-taxonomy.md`、`~/.claude/settings.json`）：每個 session 都在寫，誰寫的證明不了也不必證明，整組收成一顆 checkpoint commit。授權來自這條規則，不來自作者判定。
- **一般檔案**：由 `~/.claude/scripts/closeout-provenance.py` 判是不是本 session 寫的。它讀本 session（含 subagent）的紀錄檔：Edit／Write 的路徑是高信心（`self_owned: true`），Bash 指令同時含路徑與寫入構造是低信心候選（`self_bash_only: true`），且寫入時間晚於該檔最後一次 commit。
- **push**：個人 repo 的 trunk 一律推。trunk 上別的 session 的 commit 也是使用者自己的，一起推並在報告點名。

不用檔案 mtime 或工具呼叫時間窗推歸屬：mtime 不帶寫入者身分，會把自己剛改的檔擋住，也會把別人在你跑長測試期間改的檔算成你的（2026-10-09 GPT-6 Pro 審查）。

## 流程

0. **記憶回看**
   回看本 session 上一次 self-closeout 回報之後的對話（這是本 session 第一次跑就從頭看），找出值得跨 session 留下、但還沒寫進 `~/.claude/memory/` 的項目。收尾時對話還在 context 裡；session 關掉後，沒寫的教訓只剩 session 紀錄，下次得重翻。符合任一條才算候選：
   - 使用者的糾正或可重用的偏好，已被接受。
   - 查證過的工具限制、踩坑或根因。
   - 已拍板、跨 session 有效的決策及理由。
   - 未來 session 需要、但 repo／git 查不到的專案狀態或約束。

   一般進度、只對這個任務有效的下一步、沒被接受的建議、使用者說不要記的內容、repo 文件或 commit 已寫清楚的事，都不算。agent 回報的「文件與現有程式碼不一致」也不寫進 memory，交給第 0b 步。每個候選先 `command grep -rliE '<關鍵字>' ~/.claude/memory/` 找既有檔：主題相同就併進去，沒有才新建，新建照 `~/.claude/memory/feedback_memory_cluster_maintenance.md` 掛索引。寫進去的檔由第 2 步的共用 checkpoint 一起收。

   **完成判準**：每個候選都已寫入或併入，或寫得出不寫的理由；第 6 步回報的「記憶」欄填得出來。完成後接第 0b 步。

0b. **文件落差登記**
   回看同一段對話，找出 agent 回覆裡列出的「文件與現有程式碼不一致」，包含本 session 派出的 subagent 或 worker 回報、由你轉述的。逐條 append 到 `~/.claude/friction/doc-drift.md` 的 `## 待折` 段；檔案不存在就先照 `~/.claude/friction/PROTOCOL.md`「落點」建立三段標題。不寫進 memory 的原因：memory 不會提醒，摩擦掃描只數 `friction/` 各檔的待折段，記在別處等於沒人會回來處理。

   每條一行，欄位照 PROTOCOL.md「紀錄格式」：
   ```
   - YYYY-MM-DD [source_ref=session:<id>#<turn>; signal_type=agent-observation; target=rule:<文件絕對路徑>; feedback_quote=N-A; why="<文件哪一行寫什麼、程式碼實際是什麼>"] <這次怎麼處理：照程式碼寫／未處理>。建議：<把文件改成現況，或確認是遷移中後在文件註明>
   ```
   不記兩種：本 session 已經把那份文件改對的，以及使用者說不要記的。

   **完成判準**：對話裡每一條回報的不一致都已 append，或寫得出不記的理由；第 6 步回報的「文件落差」欄填得出來。完成後接第 1 步。

1. **列出範圍**
   ```bash
   python3 ~/.claude/scripts/closeout-provenance.py --self-repos
   ```
   每一行是一個 repo。清單含本 session 用 Edit／Write 碰過的 repo、含寫入標記的 Bash 指令碰過的 repo，加上兩個固定共用 repo。判定 scope 看 repo 的 git root（`git -C <repo> rev-parse --show-toplevel`），不看路徑前綴：git root 就是 `~/Desktop/work/acme` 本身時為 personal（使用者的私人治理層、無 remote）；git root 在 `~/Desktop/work/acme/` 底下的巢狀 repo（`acme-dashboard-v2`、`acme-saas-v2-service` 等）為 work scope；`~/Desktop/work/` 其他位置直接跳過並回報；其餘為 personal。

   **完成判準**：每個 repo 都有 scope 標記，沒有 repo 被略過，兩個固定共用 repo 都在清單裡。

2. **每個 repo 分四欄：共用 checkpoint、本 session 成果、保留、未收**
   ```bash
   python3 ~/.claude/scripts/closeout-provenance.py --repo <repo> --plan <scratchpad>/closeout
   ```
   必須以前景同步執行（禁止設 `run_in_background: true`），等當次 `--plan` 成功跑完並讀回該 repo 的完整輸出後，才准進入第 3 步。不要改跑 `--json` 或表格模式：完整報告常上百 KB，大多是別的 session 的檔，讀進 context 只為了把它們判成未收。`--plan` 已在腳本裡套完下面除「context 保留條件」與「Bash 認領」以外的規則，只印要動手的路徑與計數：`shared.pathspec_file`（共用 checkpoint 白名單檔）、`self_owned`、`self_bash_only`、`held_staged_differs`、`held_vendor_managed`、`staged_foreign`、`unclaimed`（未收數）、`branch`、`has_origin`、`has_upstream`、`detail`（完整報告檔，回報異常時才給連結）。規則如下，命中第一條就停：
   - `vendor_managed: true`（`skills/.trash/`、`skills/synced/` 這類同步機制搬進來的東西）→ 保留，不收。
   - 本輪 context 裡有明確保留條件（使用者說先不 commit、檔案在等另一個 session 的 audited commit、ignore.jsonl 以 `"ref": "*"` 交給其他工具）→ 保留，寫出條件。
   - `staged_differs: true`（同一個檔同時有 staged 與不同的工作樹內容）→ 保留。整包 add 會把暫存的那一版蓋掉，那一版可能是 HEAD 和工作樹都沒有的內容。
   - `shared: true`（只在兩個固定共用 repo 內成立；普通專案自己的 `memory/` 或 `settings.json` 不算）→ 進「共用 checkpoint」白名單。`co_written`、`codex_touched`、寫入工具種類不再構成拒收理由。
   - `self_owned: true` → 進「本 session 成果」白名單。
   - `self_bash_only: true` → 你必須能從本 session 的 context 指出那次 Bash 改檔，指得出來才進「本 session 成果」白名單，指不出來就照未收處理。
   - 其餘（無寫入者、一般檔的 co_written 或 codex_touched）→ 未收，留給 `/git-closeout`。

   如果 `staged_foreign` 非空，先保留該 repo 的提交，繼續處理其他 repo；不要取消別人的暫存，也不要把別人的路徑加入本次白名單。

   **完成判準**：每個 dirty path 恰好落在四欄之一。

3. **先 add、核對 index，再 commit**
   每顆 commit 分開執行下列指令；讀回暫存區後，只有暫存區路徑與本顆白名單完全相等時才 commit。本 session 成果的白名單通常只有幾個檔，直接寫路徑：
   ```bash
   git -C <repo> add -- <白名單每個路徑>
   git -C <repo> diff --cached --name-only
   git -C <repo> commit -m "<訊息>"
   git -C <repo> show --stat --format= HEAD
   ```
   共用 checkpoint 可能有上百個檔，改用 `--plan` 給的白名單檔，核對時只看差異（沒有輸出＝完全相等）；context 保留條件命中的路徑先從該檔刪掉：
   ```bash
   git -C <repo> add --pathspec-from-file=<shared.pathspec_file>
   git -C <repo> diff --cached --name-only | diff - <shared.pathspec_file>
   git -C <repo> commit -m "chore(closeout): checkpoint shared ledgers"
   git -C <repo> show --name-only --format= HEAD | diff - <shared.pathspec_file>
   ```
   如果核對時出現白名單外路徑，停止該 repo 的提交並列為保留，不取消別人的暫存。普通 commit 會提交整個 index，所以不能省略這一步；不使用 `--only` 或 pathspec 提交，避免與 gate 的暫存區檢查衝突。這次核對不保證其他 session 在核對後不會改 index，提交後仍要比對檔案清單；若 `git commit` 因並行 session 已搶先將暫存變更收走而回 `Exit code 1`，結案摘要須分開標示「本次新增 commit 0 檔（已由並行 session 收走）」，且未收 `K` 一律取自最新一次 `--plan` 的 `unclaimed` 計數（不自行執行 `git reset` 退回暫存）。

   `<repo>` 一律寫絕對路徑，一個 Bash call 只放一條 git 指令。共用 checkpoint 自成一顆，訊息固定 `chore(closeout): checkpoint shared ledgers`；本 session 成果照 Conventional Commits，一個邏輯單元一顆。禁用 `git add -A`、`git add .`、`git commit -a`。

   **完成判準**：提交前 index 路徑、提交後 `git show --stat --format=` 檔案清單都與該顆白名單完全相等；不符時保留差異並回報，不自行改寫已產生的 commit。

4. **push（personal 且在 trunk 上時）**
   先核對第 2 步 `--plan` 輸出的 `has_origin` 與 `has_upstream`：如果 `has_origin: false`（repo 沒有 `origin`），直接跳過下方全部 git 指令（不跑 `git fetch origin` 或 `git push`），報告寫「無 origin，已本機保存」（或「無 remote，已本機保存」）；如果 `has_origin: true` 但 `has_upstream: false`（目前 trunk 沒有設定有效 tracking upstream），同樣跳過下方 git 指令，報告寫「有 origin 但目前分支未設 upstream，已本機保存」。確認 `has_origin: true` 且 `has_upstream: true` 時，比照第 3 步「一個 Bash call 只放一條 git 指令」，將下列三步拆成三個獨立的 Bash tool call 依序執行並逐步確認結果（禁止用 `&&` 串接在同一個 Bash 呼叫）：
   ```bash
   git -C <repo> fetch origin
   ```
   ```bash
   git -C <repo> log --format='%h %s' origin/<trunk>..<trunk>
   ```
   ```bash
   git -C <repo> push
   ```
   ```bash
   git -C <repo> rev-parse HEAD origin/<trunk>
   ```
   push 後讀回 `rev-parse` 兩行確認 `HEAD` 與 `origin/<trunk>` SHA 完全相等。列出的 commit 不必全是本次剛產生的：個人 repo 的 trunk 上任何 commit 都是使用者自己透過某個 session 產生，讀回 `git log` 對帳確認後照常 push，報告點名「含 N 顆非本 session 的 commit：<hash>…」；main 的 pre-push inclusion gate 照常守。push 被拒（remote 有新 commit）就單獨跑 `git -C <repo> merge origin/<trunk>` 確認成功後再單獨 `git -C <repo> push` 一次，不 rebase、不 force；merge 衝突就停、標 BLOCKED。push 與收 dirty 分開判：某個檔這輪保留，不影響已 commit 的成果推出去。

   work scope：不 push、不開 PR、不在 `stage`／`main`／`master` 產生 commit；commit 停在當前 feature branch，等使用者決定。在 trunk 上有自己的改動時，先開 `feat/<描述>` branch 再 commit。

   **完成判準**：personal repo 的 `origin/<trunk>..<trunk>` 為空且 `HEAD == origin/<trunk>`，或已明確回報「無 origin（無 remote）」／「有 origin 但目前分支未設 upstream」；work scope 的 trunk 沒有新 commit。

5. **自己開的 worktree**
   本 session 用 EnterWorktree 或 `git worktree add` 開的 worktree，commit 已整合進 trunk 且乾淨時才移除；別人的 worktree 不碰。

6. **回報**
   為維持正常收尾回報精簡，沒有異常時整份回報只有一行，多個 repo 用「；」接在同一行（注意：第 1 步列出的 repo 只要有未收 `K > 0` 或保留項目，即使本輪收 `0` 檔也必須列在該行，不得省略）：
   ```text
   Self closeout：DONE｜記憶：新增 N、併入 M／0（<一句理由>）｜文件落差：新增 N／0｜<repo 名> 收 N 檔＋checkpoint M 檔，已推／本機保存／留在 <branch>｜未收 K
   ```
   未收只寫數字、不列路徑：那些是別的 session 的檔，交給 `/git-closeout`。下列任一成立就是異常，該 repo 改用下方完整段落（不使用外層 code block 包住，確保 `file:///` 連結可點），其餘 repo 照舊擠在一行：
   - BLOCKED：merge 衝突，或提交前後的檔案清單與白名單不符。
   - `staged_foreign` 非空，該 repo 的提交被擋下。
   - personal repo 的 `branch` 不是 trunk。
   - 本 session 的檔沒進 commit：`self_owned` 或 `self_bash_only` 的路徑最後落在保留或未收（使用者本輪明說先不 commit 的除外），或本 session 碰過的 repo 因 scope 被跳過。

   - Self closeout：<DONE 或 BLOCKED>
   - 記憶：新增 N、併入 M（<檔名>…）／0（<一句理由>）
   - 文件落差：新增 N（doc-drift.md）／0
   - repo：<path>（scope：personal／work）
   - 異常：<命中哪一條、需要使用者做什麼>
   - 已收：<N 檔，commit <hash>…>；共用 checkpoint：<N 檔，commit <hash>> 或 0
   - 已推：origin/<trunk>（含 N 顆非本 session 的 commit：<hash>…）／無 origin，已本機保存／有 origin 但目前分支未設 upstream，已本機保存／work scope 留在 <branch> 等你
   - 保留：<path（原因：等 audited commit／使用者指定先不 commit／同檔暫存與工作樹不同版／交給其他工具）>…或 0
   - 未收：<數字>（明細見 [closeout 明細](file:///<detail 檔絕對路徑>)）

   「記憶」不論哪種格式都要寫，不跳過；「文件落差」同樣不跳過。兩種格式都不寫「乾淨」，除非 fresh `git status` 為空。

## 邊界

- 共用 checkpoint 收的是「使用者允許整組保存的共用狀態」，不是「只追加的檔」；MEMORY.md 會瘦身、trials 會在 active 與 archived 之間搬段，所以 `trials/` 底下相依的 active、archived、index、detail 一起收，不拆半。
- 共用 checkpoint 不代表其他 session 的任務通過驗收，它只是備份點。
- 一般檔案這支只收「證明得了是自己的」變更；證明不了就跳過，寧可留給全機收，不猜。provenance 已支援同段 `cd <repo>` 配相對路徑與 `--out`／`--output`，但涵蓋不到不帶輸出路徑參數的 hook／固定路徑 script 直接寫的檔（如 `--workflow-output`、`--run-id`），這類漏掉的顯示為無寫入者並留待 `/git-closeout`。
- 不對其他 session 發 SendMessage，也不等它們；ListAgents 只在需要判斷 worktree 是否有人用時讀一次。
- 多帳號 config dir（`~/.claude-team-*`、`~/.claude-max`）的 `.git` 是 `~/.claude/.git` 的 symlink，只從 `~/.claude` 正本操作，不在替代目錄 add。
- 2026-10-09 檢討：近 20 天 124 份回報只有 19 份未收為零，殘留來自 co_written、Bash 盲區、push 死結三條舊規則，本版據此改寫；證據在該日 session 的副檔。
