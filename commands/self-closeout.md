---
description: 工作 session 任務收尾時，把「本 session 自己改的檔」commit、push（個人 repo）或留在 feature branch（公司 repo），不動其他 session 的東西。Use when 本 session 的任務已完成並驗證、準備回報結案；或使用者說「收掉你的部分」「self closeout」。Do not use for 全機收尾（那是使用者手打的 `/git-closeout`）、merge conflict、PR review，或任務尚未驗證完成的中途 commit。
argument-hint: 不帶參數；範圍由 closeout-provenance.py --self-repos 決定
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/self-closeout-contract.test.sh -->

# Self Closeout

收自己的桌子，不碰別人的。範圍不是 cwd，是本 session 實際寫過的每個 repo，加上兩個固定共用 repo（`~/.claude`、`~/Desktop/projects/.claude`）；`~/.claude` 常從其他目錄被順手改到，只看 cwd 會漏掉它。

三類東西各有收法，不要用同一個條件判：

- **共用帳本**（`memory/`、`trials/`、`friction/`、各 skill 的 `friction-log.md`、`references/failure-mode-taxonomy.md`、`~/.claude/settings.json`）：本指令不收，整組留給 `/git-closeout` 統一備份。
- **一般檔案**：由 `~/.claude/scripts/closeout-provenance.py` 判是不是本 session 寫的。它讀本 session（含 subagent）的紀錄檔：Edit／Write 的路徑是高信心（`self_owned: true`），Bash 指令同時含路徑與寫入構造是低信心候選（`self_bash_only: true`），且寫入時間晚於該檔最後一次 commit。
- **push**：個人 repo 的 trunk 一律推。trunk 上別的 session 的 commit 也是使用者自己的，一起推並在報告點名。

不用檔案 mtime 或工具呼叫時間窗推歸屬：mtime 不帶寫入者身分，會把自己剛改的檔擋住，也會把別人在你跑長測試期間改的檔算成你的（2026-10-09 GPT-6 Pro 審查）。

## 流程

0. **記憶回看**
   回看本 session 上一次 self-closeout 回報之後的對話（這是本 session 第一次跑就從頭看），找出值得跨 session 留下、但還沒寫進 `~/.claude/memory/` 的項目。收尾時對話還在 context 裡；session 關掉後，沒寫的教訓只剩 session 紀錄，下次得重翻。符合任一條才算候選：
   - 使用者的糾正或可重用的偏好，已被接受。沒明講的三種也算：反覆微調後停下的落點（記落點，不記過程）、在 agent 給的選項裡選定或否決了 agent 的推薦、使用者點名確認、而新來的 agent 很可能做成別種的選擇（只回一句「好」「可以」帶過 agent 自己報告的做法不算，那不是使用者在表達偏好）。
   - 查證過的工具限制、踩坑或根因。
   - 已拍板、跨 session 有效的決策及理由。
   - 未來 session 需要、但 repo／git 查不到的專案狀態或約束。

   一般進度、只對這個任務有效的下一步、沒被接受的建議、使用者說不要記的內容、repo 文件或 commit 已寫清楚的事，都不算。值只出現在某個元件的程式碼裡不算寫清楚：下一個 agent 做別的元件時讀不到它。候選只對本場工作的那一個 repo 成立（它的外觀或行為規則）時不寫進 memory，交給第 0a 步。agent 回報的「文件與現有程式碼不一致」也不寫進 memory，交給第 0b 步。每個候選先 `command grep -rliE '<關鍵字>' ~/.claude/memory/` 找既有檔：主題相同就併進去，沒有才新建，新建照 `~/.claude/memory/feedback_memory_cluster_maintenance.md` 掛索引。寫進共用帳本的檔不在本指令收，留給 `/git-closeout`。

   **完成判準**：每個候選都已寫入或併入、交給第 0a 步，或寫得出不寫的理由；第 6 步回報的「記憶」欄填得出來。完成後接第 0a 步。

0a. **專案規則提案**
   處理第 0 步交過來、只對那一個 repo 成立的候選。它們不進 memory 的原因：全域記憶在別的專案也會被讀到，而那個 repo 的 agent 開工時讀的是 repo 自己的規則檔。使用者明說每個專案都適用的，留在第 0 步進 memory。

   每個候選先過一句測試：新來的 agent 在這個 repo 做另一個元件或畫面時，還會犯同樣的錯嗎？不會就跳過；會才成為提案。對照：這一頁的標題文字、這一張圖再放大一點 → 跳過；卡片的圓角、彈出選單的開啟速度這類同類元件還會再出現的值 → 提案。每條提案寫四件事：
   - 使用者原話，逐字；反覆微調寫最後停下的值。
   - 建議的規則文字：寫到同類元件都適用，不寫成只管這一個元件，也不放大成整個專案的禁令。
   - 理由：用使用者自己講的。沒講就寫你的推測並標 `inferred`，等使用者確認；寫錯的理由會被下一個 agent 套到不適用的地方。
   - 建議落點：context 裡已知的該 repo 規則檔與段落；沒有合適的就寫「落點待定」。

   這一步只提案：不改該 repo 的任何檔、不 commit，使用者授權過自由 commit 也一樣。規則檔可能屬於上游或有自己的範圍，而寫錯的規則會在之後每場 session 重複生效。使用者回覆要寫哪幾條，才照該 repo 的慣例寫入。

   **完成判準**：每個專案範圍的候選都已列成提案，或寫得出跳過的理由；沒有任何一條被寫進 memory 或該 repo；第 6 步回報的「專案規則提案」填得出來。完成後接第 0b 步。

0b. **文件落差登記**
   回看同一段對話，找出 agent 回覆裡列出的「文件與現有程式碼不一致」，包含本 session 派出的 subagent 或 worker 回報、由你轉述的。逐條 append 到 `~/.claude/friction/doc-drift.md` 的 `## 待折` 段；檔案不存在就先照 `~/.claude/friction/PROTOCOL.md`「落點」建立三段標題。不寫進 memory 的原因：memory 不會提醒，摩擦掃描只數 `friction/` 各檔的待折段，記在別處等於沒人會回來處理。

   每條一行，欄位照 PROTOCOL.md「紀錄格式」：
   ```
   - YYYY-MM-DD [source_ref=session:<id>#<turn>; signal_type=agent-observation; target=rule:<文件絕對路徑>; feedback_quote=N-A; why="<文件哪一行寫什麼、程式碼實際是什麼>"] <這次怎麼處理：照程式碼寫／未處理>。建議：<把文件改成現況，或確認是遷移中後在文件註明>
   ```
   不記四種：(1) 本 session 已經把那份文件改對的；(2) 使用者說不要記的；(3) 沒有進行中上游 PR 計畫的第三方上游作者文件小落差（fork repo 先跑 `git blame` 確認該段屬使用者自寫還是上游作者，非自寫且無上游 PR 計畫就免記）；(4) 已結案、未追蹤的 `.scratch/` 歷史施工票草稿。

   **完成判準**：對話裡每一條回報的不一致都已 append，或寫得出不記的理由；第 6 步回報的「文件落差」欄填得出來。完成後接第 1 步。

1. **列出範圍**
   ```bash
   python3 ~/.claude/scripts/closeout-provenance.py --self-repos
   ```
   每一行是一個 repo。清單含本 session 用 Edit／Write 碰過的 repo、含寫入標記的 Bash 指令碰過的 repo，加上兩個固定共用 repo。判定 scope 看 repo 的 git root（`git -C <repo> rev-parse --show-toplevel`），不看路徑前綴：git root 就是 `~/Desktop/work/acme` 本身時為 personal（使用者的私人治理層、無 remote）；git root 在 `~/Desktop/work/acme/` 底下的巢狀 repo（`acme-dashboard-v2`、`acme-saas-v2-service` 等）為 work scope；`~/Desktop/work/` 其他位置直接跳過並回報；其餘為 personal。

   **完成判準**：每個 repo 都有 scope 標記，沒有 repo 被略過，兩個固定共用 repo 都在清單裡。

2. **每個 repo 分三欄：本 session 成果、保留、未收**
   ```bash
   python3 ~/.claude/scripts/closeout-provenance.py --repo <repo> --plan <scratchpad>/closeout
   ```
   必須以前景同步執行（禁止設 `run_in_background: true`），等當次 `--plan` 成功跑完並讀回該 repo 的完整輸出後，才准進入第 3 步。不要改跑 `--json` 或表格模式：完整報告常上百 KB，大多是別的 session 的檔，讀進 context 只為了把它們判成未收。`--plan` 已在腳本裡套完下面除「context 保留條件」與「Bash 認領」以外的規則（含公開／未知可見性 repo 的 `.scratch/` 預設歸入 `held_public_scratch`），只印要動手的路徑與計數：`shared.count`（共用帳本數）、`shared.pathspec_file`（共用帳本清單檔）、`self_owned`、`self_bash_only`、`staged_deletions`、`held_staged_differs`、`held_public_scratch`、`held_vendor_managed`、`staged_foreign`、`unclaimed`（不含共用帳本）、`branch`、`has_origin`、`has_upstream`、`detail`（完整報告檔，回報異常時才給連結）。規則如下，命中第一條就停：
   - `vendor_managed: true`（`skills/.trash/`、`skills/synced/` 這類同步機制搬進來的東西）→ 保留，不收。
   - 本輪 context 裡有明確保留條件（使用者說先不 commit、檔案在等另一個 session 的 audited commit、ignore.jsonl 以 `"ref": "*"` 交給其他工具）→ 保留，寫出條件。
   - `staged_differs: true`（同一個檔同時有 staged 與不同的工作樹內容）→ 保留。整包 add 會把暫存的那一版蓋掉，那一版可能是 HEAD 和工作樹都沒有的內容。
   - 公開 repo 的 `.scratch/` 內部材料（兩個固定共用 repo 除外）：`has_origin: true` 且路徑位於 `.scratch/` 底下、使用者本輪未明示要公開時，先核對遠端 repo 可見性（個人 `example-owner/*` 用 `GH_TOKEN=$(gh auth token -u example-owner) gh repo view --json visibility`，私有 repo 不擋）；遠端為 `PUBLIC` 或無法確認為 `PRIVATE` 時 → 保留。所有權只證明檔案是本 session 寫的，不證明內容適合公開（`.scratch/` 常含本機路徑、session 編號與審查原話）。
   - `shared: true`（只在兩個固定共用 repo 內成立；普通專案自己的 `memory/` 或 `settings.json` 不算）→ 未收，留給低頻的 `/git-closeout` 統一備份。收尾只保證「本機是最新且含本 session 改動」；每個 session 都在共用 checkout 原地 commit 共用帳本，正是共用 `main` 反覆分岔的來源。`--plan` 仍會印 `shared.pathspec_file`，不要拿它 `git add`。
   - `self_owned: true` → 進「本 session 成果」白名單。
   - `self_bash_only: true` → 你必須能從本 session 的 context 指出那次 Bash 改檔，指得出來才進「本 session 成果」白名單，指不出來就照未收處理。
   - 其餘（無寫入者、一般檔的 co_written 或 codex_touched）→ 未收，留給 `/git-closeout`。

   如果本 session 在該 repo 沒有待提交白名單（0 檔），即使 `staged_foreign` 非空也直接跳過提交、不算異常；不要取消別人的暫存，也不要把別人的路徑加入本次白名單。有待提交白名單時，只有命中第 3 步必須走共用暫存區的例外（鎖定核心檔或 `staged_deletions`）且 `staged_foreign` 非空，才先保留該 repo 的提交，繼續處理其他 repo；其餘一般檔與非鎖定受控檔改走第 3 步的點名直交（`git commit --only`），不受 `staged_foreign` 阻擋。

   **完成判準**：每個 dirty path 恰好落在三欄之一。

3. **優先點名直交（`--only`），鎖定檔或暫存刪除才走共用暫存區**
   - **預設路徑（點名直交，不碰共用暫存區）**：只要本顆白名單不含鎖定核心檔（`~/.claude` 與專案 `.claude/` 底下的 `hooks/agent-contract-validator-gate*`、`hooks/agent-contract-gate-permit.sh`、`hooks/T2-routing-gate*`、`hooks/review-spec-yagni-permit*`、`scripts/agent-contract-*`）、不含 `staged_deletions`、不含 symlink，且 repo 已有 `HEAD`（非首次 unborn 提交），就走點名直交——直接以 `HEAD` 與白名單檔案建立 commit，完全不碰共用 `.git/index` 裡其他 session 的暫存。若白名單含 Git 尚未追蹤的新增檔，先單獨登記追蹤再直交：
     ```bash
     git -C <repo> add --intent-to-add -- <新增檔每個路徑>
     git -C <repo> commit --only -m "<訊息>" -- <白名單每個路徑>
     git -C <repo> show --stat --format= HEAD
     ```
     （若白名單皆為已追蹤檔案，跳過 `--intent-to-add` 直接執行 `commit --only`；不可省略 `--only` 寫成裸 pathspec 提交。）
   - **例外路徑（鎖定核心檔或 `staged_deletions` 走共用暫存區）**：鎖定核心檔的 permit 綁定暫存區項目，且已在暫存區標為刪除的路徑（如 `--plan` 的 `staged_deletions`，或由 `git rm`／`git rm --cached` 產生的 `D ` 暫存刪除）無法由 `--only` 提交，因此這兩類改走共用暫存區。動手執行任何 `git add` 前，先單獨跑一次 `git -C <repo> diff --cached --name-only`：暫存區含本 session 成果白名單以外的路徑（包括別人暫存的共用帳本）→ 直接停止該 repo 的提交並列為保留，不執行 `git add`、也不取消別人的暫存。對 `staged_deletions` 保留原暫存狀態、**不對它們執行 `git add`**（否則 `git rm --cached` 留在磁碟或已進 `.gitignore` 的檔案會被重新納管或因忽略規則報錯）；只對其餘需要暫存的新增／修改路徑直接寫路徑執行 `git add`（若整顆白名單皆為已暫存刪除則跳過 `git add`，直接核對 `diff --cached`），讀回暫存區後只有暫存區路徑與本顆白名單完全相等時才 commit：
     ```bash
     git -C <repo> add -- <白名單每個路徑>
     git -C <repo> diff --cached --name-only
     git -C <repo> commit -m "<訊息>"
     git -C <repo> show --stat --format= HEAD
     ```
     如果核對時出現白名單外路徑，停止該 repo 的提交並列為保留，不取消別人的暫存。這條例外路徑在核對到無 pathspec 的 `git commit` 落地之間仍有已知未解的並行競態窗口（其他 session 可能在核對後才改動共用 index），因此提交後仍要比對檔案清單；若 `git commit` 因並行 session 已搶先將暫存變更收走而回 `Exit code 1`，結案摘要須分開標示「本次新增 commit 0 檔（已由並行 session 收走）」，且用最新一次 `--plan` 的輸出按第 6 步計算未收 `K`（不自行執行 `git reset` 退回暫存）。

   `<repo>` 一律寫絕對路徑，一個 Bash call 只放一條 git 指令。本 session 成果照 Conventional Commits，一個邏輯單元一顆。禁用 `git add -A`、`git add .`、`git commit -a`。

   **完成判準**：提交後 `git show --stat --format=` 檔案清單與該顆白名單完全相等（走共用暫存區例外路徑時提交前 index 路徑亦須完全相等）；不符時保留差異並回報，不自行改寫已產生的 commit。

4. **push（personal 且在 trunk 上時）**
   先核對第 2 步 `--plan` 輸出的 `has_origin` 與 `has_upstream`：如果 `has_origin: false`（repo 沒有 `origin`），跳過下方 git 指令，報告寫「無 origin，已本機保存」（或「無 remote，已本機保存」）；如果 `has_origin: true` 但 `has_upstream: false`，同樣跳過，報告寫「有 origin 但目前分支未設 upstream，已本機保存」。兩者皆為 `true` 時，依序執行下列指令，每條各用一個 Bash call 並讀回結果：
   ```bash
   git -C <repo> fetch origin
   ```
   ```bash
   git -C <repo> rev-list --left-right --count <trunk>...origin/<trunk>
   ```
   ```bash
   git -C <repo> log --format='%h %s' origin/<trunk>..<trunk>
   ```
   `rev-list` 左欄是本機獨有的 commit 數，右欄是遠端獨有的 commit 數。`log` 用於核對發布範圍，報告點名「含 N 顆非本 session 的 commit：<hash>…」。如果 `<repo>` 有任何未提交／保留／未收髒檔，原地整合限於下列快轉指令。乾淨 checkout 也走同一套分支，避免覆寫 Git 忽略的檔案。全程不使用 `pull`，不 rebase、不 force。
   - **只領先（左欄非零、右欄為零）**：單獨跑 `git -C <repo> push`，main 的 pre-push inclusion gate 照常守。如果 push 因遠端有新 commit 被拒，先重新單獨跑 `git -C <repo> fetch origin`，再查兩欄計數與發布範圍，依最新結果走對應分支。
   - **只落後（左欄為零、右欄非零）**：單獨跑 `git -C <repo> merge --ff-only --no-autostash --no-overwrite-ignore origin/<trunk>`。
   - **分岔（兩欄皆非零）**：從剛 fetch 的 `origin/<trunk>` 開臨時 clean worktree，逐條單獨執行：
     1. `git -C <repo> worktree add --detach <scratchpad>/closeout-wt-<repo名> origin/<trunk>`
     2. `git -C <scratchpad>/closeout-wt-<repo名> merge --no-edit <trunk>`（若 merge 衝突，依序單獨跑 `git -C <scratchpad>/closeout-wt-<repo名> merge --abort` 與 `git -C <repo> worktree remove <scratchpad>/closeout-wt-<repo名>` 後停止、標 `BLOCKED`）
     3. `git -C <scratchpad>/closeout-wt-<repo名> push origin HEAD:refs/heads/<trunk>`（如果被拒，先重新單獨 fetch，再回報 `BLOCKED` 與臨時 worktree 路徑）
     4. `git -C <repo> worktree remove <scratchpad>/closeout-wt-<repo名>`
     5. 移除後重新單獨跑 `git -C <repo> fetch origin`，再單獨跑 `git -C <repo> merge --ff-only --no-autostash --no-overwrite-ignore origin/<trunk>`。
   - **已同步（兩欄皆為零）**：直接做最後核對。

   最後單獨跑 `git -C <repo> rev-parse HEAD origin/<trunk>`，確認兩行 SHA 相等。如果原地快轉因路徑重疊被 gate 擋下，或因 ignored／未追蹤檔被 Git 拒絕，保留那些檔案，並單獨跑 `git -C <repo> log --format='%h %s' origin/<trunk>..<trunk>` 核對發布結果：
   - **輸出為空（遠端已包含所有本機 commit）**：不標 `BLOCKED`（不展開異常段落叫使用者立刻停下來處理分岔），維持正常 `DONE` 單行回報，在該 repo 狀態欄寫「成果已推上 origin，本機未同步（留待夜間／`/git-closeout`）」。
   - **輸出非空（遠端仍缺本機 commit），或臨時 worktree 合併衝突／push 被拒**：標 `BLOCKED` 並在異常欄寫明路徑、實際原因與已知發布狀態，請使用者介入。

   push 與收 dirty 分開判：某個檔這輪保留，不影響已 commit 的成果推出去。

   work scope：不 push、不開 PR、不在 `stage`／`main`／`master` 產生 commit；commit 停在當前 feature branch，等使用者決定。在 trunk 上有自己的改動時，先開 `feat/<描述>` branch 再 commit。

   **完成判準**：personal repo 核對到 `HEAD == origin/<trunk>`（或原地快轉因非本輪髒檔受阻但確認 `origin/<trunk>..<trunk>` 為空、於正常回報註明「成果已推上 origin，本機未同步」），且用過的臨時 worktree 已移除。若遠端仍缺本機 commit、臨時 worktree 衝突或發布失敗，標 `BLOCKED` 並寫明原因。無 remote 或未設 upstream 時回報本機保存及原因。work scope 的 trunk 沒有新 commit。

5. **自己開的 worktree**
   本 session 用 EnterWorktree 或 `git worktree add` 開的 worktree，commit 已整合進 trunk 且乾淨時才移除；別人的 worktree 不碰。

6. **回報**
   為維持正常收尾回報精簡，沒有異常時整份回報只有一行，多個 repo 用「；」接在同一行（注意：第 1 步列出的 repo 只要有未收 `K > 0` 或保留項目，即使本輪收 `0` 檔也必須列在該行，不得省略）：
   ```text
   Self closeout：DONE｜記憶：新增 N、併入 M／0（<一句理由>）｜專案規則提案：N／0｜文件落差：新增 N／0｜<repo 名> 收 N 檔，已推／本機保存／留在 <branch>｜未收 K
   ```
   第 0a 步有提案時，在這一行之後另起「專案規則提案」段，每條一行，最後一句問使用者要寫哪幾條；沒有提案就不出這段：
   ```text
   <編號>. 「<使用者原話>」→ <規則文字>｜理由：<使用者原話，或 inferred：…>｜落點：<檔與段落，或落點待定>
   ```
   兩種格式都取最新一次 `--plan`：未收 K = `unclaimed` + `shared.count`。未收只寫數字、不列路徑，留給 `/git-closeout`。下列任一成立就是異常，該 repo 改用下方完整段落（不使用外層 code block 包住，確保 `file:///` 連結可點），其餘 repo 照舊擠在一行：
   - BLOCKED：臨時 worktree 合併衝突、第 4 步的發布受阻（遠端仍缺本機 commit，即 `origin/<trunk>..<trunk>` 非空），或提交前後的檔案清單與白名單不符（單純原地快轉受阻但 `origin/<trunk>..<trunk>` 為空不算異常，照正常單行註明「成果已推上 origin，本機未同步」）。
   - 本 session 在該 repo 有待提交白名單、必須走共用暫存區例外路徑，且 `staged_foreign` 非空，該 repo 的提交被擋下（本場 0 檔待收，或已改由 `git commit --only` 成功提交時，不因 `staged_foreign` 標為異常）。
   - personal repo 的 `branch` 不是 trunk。
   - 本 session 的檔沒進 commit：`self_owned` 或 `self_bash_only` 的路徑最後落在保留或未收（使用者本輪明說先不 commit 的除外），或本 session 碰過的 repo 因 scope 被跳過。

   - Self closeout：<DONE 或 BLOCKED>
   - 記憶：新增 N、併入 M（<檔名>…）／0（<一句理由>）
   - 專案規則提案：N（另起一段列出）／0
   - 文件落差：新增 N（doc-drift.md）／0
   - repo：<path>（scope：personal／work）
   - 異常：<命中哪一條、需要使用者做什麼>
   - 已收：<N 檔，commit <hash>…>
   - 已推：origin/<trunk>（含 N 顆非本 session 的 commit：<hash>…）／無 origin，已本機保存／有 origin 但目前分支未設 upstream，已本機保存／work scope 留在 <branch> 等你
   - 保留：<path（原因：等 audited commit／使用者指定先不 commit／同檔暫存與工作樹不同版／公開 repo 內部 .scratch 材料／交給其他工具）>…或 0
   - 未收：<數字>（明細見 [closeout 明細](file:///<detail 檔絕對路徑>)）

   「記憶」不論哪種格式都要寫，不跳過；「專案規則提案」與「文件落差」同樣不跳過。兩種格式都不寫「乾淨」，除非 fresh `git status` 為空。

## 邊界

- 共用帳本（`shared: true`）不在這裡收，整組留給 `/git-closeout`：它會把 MEMORY.md 瘦身、trials 在 active 與 archived 之間搬段這類相依變更一起收，不拆半。
- 一般檔案這支只收「證明得了是自己的」變更；證明不了就跳過，寧可留給全機收，不猜。provenance 已支援同段 `cd <repo>` 配相對路徑與 `--out`／`--output`，但涵蓋不到不帶輸出路徑參數的 hook／固定路徑 script 直接寫的檔（如 `--workflow-output`、`--run-id`），這類漏掉的顯示為無寫入者並留待 `/git-closeout`。
- 不對其他 session 發 SendMessage，也不等它們；ListAgents 只在需要判斷 worktree 是否有人用時讀一次。
- 多帳號 config dir（`~/.claude-team-*`、`~/.claude-max`）的 `.git` 是 `~/.claude/.git` 的 symlink，只從 `~/.claude` 正本操作，不在替代目錄 add。
- 2026-10-09 檢討：近 20 天 124 份回報只有 19 份未收為零，殘留來自 co_written、Bash 盲區、push 死結三條舊規則，本版據此改寫；證據在該日 session 的副檔。
