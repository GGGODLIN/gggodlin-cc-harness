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

1. **列出範圍**
   ```bash
   python3 ~/.claude/scripts/closeout-provenance.py --self-repos
   ```
   每一行是一個 repo。清單含本 session 用 Edit／Write 碰過的 repo、含寫入標記的 Bash 指令碰過的 repo，加上兩個固定共用 repo。判定 scope 看 repo 的 git root（`git -C <repo> rev-parse --show-toplevel`），不看路徑前綴：git root 就是 `~/Desktop/work/acme` 本身時為 personal（使用者的私人治理層、無 remote）；git root 在 `~/Desktop/work/acme/` 底下的巢狀 repo（`acme-dashboard-v2`、`acme-saas-v2-service` 等）為 work scope；`~/Desktop/work/` 其他位置直接跳過並回報；其餘為 personal。

   **完成判準**：每個 repo 都有 scope 標記，沒有 repo 被略過，兩個固定共用 repo 都在清單裡。

2. **每個 repo 分四欄：共用 checkpoint、本 session 成果、保留、未收**
   ```bash
   python3 ~/.claude/scripts/closeout-provenance.py --repo <repo> --json
   ```
   每個 dirty path 依序套下面的規則，命中第一條就停：
   - `vendor_managed: true`（`skills/.trash/`、`skills/synced/` 這類同步機制搬進來的東西）→ 保留，不收。
   - 本輪 context 裡有明確保留條件（使用者說先不 commit、檔案在等另一個 session 的 audited commit、ignore.jsonl 以 `"ref": "*"` 交給其他工具）→ 保留，寫出條件。
   - `staged_differs: true`（同一個檔同時有 staged 與不同的工作樹內容）→ 保留。整包 add 會把暫存的那一版蓋掉，那一版可能是 HEAD 和工作樹都沒有的內容。
   - `shared: true`（只在兩個固定共用 repo 內成立；普通專案自己的 `memory/` 或 `settings.json` 不算）→ 進「共用 checkpoint」白名單。`co_written`、`codex_touched`、寫入工具種類不再構成拒收理由。
   - `self_owned: true` → 進「本 session 成果」白名單。
   - `self_bash_only: true` → 你必須能從本 session 的 context 指出那次 Bash 改檔，指得出來才進「本 session 成果」白名單，指不出來就照未收處理。
   - 其餘（無寫入者、一般檔的 co_written 或 codex_touched）→ 未收，留給 `/git-closeout`。

   `staged_foreign` 非空只代表暫存區有別的路徑的內容，不再讓整個 repo 停下；第 3 步用限定路徑的 commit 繞開它。

   **完成判準**：每個 dirty path 恰好落在四欄之一。

3. **限定路徑 commit，再核對 commit 內容**
   ```bash
   git -C <repo> add -- <白名單每個路徑>
   git -C <repo> commit --only -m "<訊息>" -- <白名單每個路徑>
   git -C <repo> show --stat --format= HEAD
   ```
   `<repo>` 一律寫絕對路徑、一條指令只碰一個 repo；用變數或一條指令串兩個 `git -C` 會被 commit gate 擋下。新檔要先 `add` 才進得了 `--only`；`--only` 只提交列出路徑的工作樹內容，暫存區裡別的路徑原封不動留給它的主人。共用 checkpoint 自成一顆，訊息固定 `chore(closeout): checkpoint shared ledgers`；本 session 成果照 Conventional Commits，一個邏輯單元一顆。禁用 `git add -A`、`git add .`、`git commit -a`。

   **完成判準**：每顆 commit 的 `git show --stat --format=` 檔案清單與該顆的白名單完全相等。

4. **push（personal 且在 trunk 上時）**
   ```bash
   git -C <repo> fetch origin
   git -C <repo> log --format='%h %s' origin/<trunk>..<trunk>
   git -C <repo> push
   ```
   repo 沒有 `origin` 或 trunk 沒有 upstream 時跳過 push，報告寫「無 remote，已本機保存」。列出的 commit 不必全是本次剛產生的：個人 repo 的 trunk 上任何 commit 都是使用者自己透過某個 session 產生，照常 push，報告點名「含 N 顆非本 session 的 commit：<hash>…」；main 的 pre-push inclusion gate 照常守。push 被拒（remote 有新 commit）就 `git -C <repo> merge origin/<trunk>` 再 push 一次，不 rebase、不 force；merge 衝突就停、標 BLOCKED。push 與收 dirty 分開判：某個檔這輪保留，不影響已 commit 的成果推出去。

   work scope：不 push、不開 PR、不在 `stage`／`main`／`master` 產生 commit；commit 停在當前 feature branch，等使用者決定。在 trunk 上有自己的改動時，先開 `feat/<描述>` branch 再 commit。

   **完成判準**：personal repo 的 `origin/<trunk>..<trunk>` 為空或已明確回報無 remote；work scope 的 trunk 沒有新 commit。

5. **自己開的 worktree**
   本 session 用 EnterWorktree 或 `git worktree add` 開的 worktree，commit 已整合進 trunk 且乾淨時才移除；別人的 worktree 不碰。

6. **回報**
   ```text
   Self closeout：<DONE 或 BLOCKED>
   repo：<path>（scope：personal／work）
   已收：<N 檔，commit <hash>…>；共用 checkpoint：<N 檔，commit <hash>> 或 0
   已推：origin/<trunk>（含 N 顆非本 session 的 commit：<hash>…）／無 remote，已本機保存／work scope 留在 <branch> 等你
   保留：<path（原因：等 audited commit／使用者指定先不 commit／同檔暫存與工作樹不同版／vendor 產物／交給其他工具）>…或 0
   未收：<path（原因：無寫入者／co_written／codex_touched）>…或 0
   ```
   每個 repo 一段。保留或未收非零時不寫「乾淨」，寫「本輪已收完，仍有 N 檔保留／未收」；只有 fresh `git status` 為空才寫乾淨。

## 邊界

- 共用 checkpoint 收的是「使用者允許整組保存的共用狀態」，不是「只追加的檔」；MEMORY.md 會瘦身、trials 會在 active 與 archived 之間搬段，所以 `trials/` 底下相依的 active、archived、index、detail 一起收，不拆半。
- 共用 checkpoint 不代表其他 session 的任務通過驗收，它只是備份點。
- 一般檔案這支只收「證明得了是自己的」變更；證明不了就跳過，寧可留給全機收，不猜。provenance 涵蓋不到 hook／script 直接寫的檔，用相對路徑加 `cd` 上層目錄的寫法也會漏，漏掉的顯示為無寫入者。
- 不對其他 session 發 SendMessage，也不等它們；ListAgents 只在需要判斷 worktree 是否有人用時讀一次。
- 多帳號 config dir（`~/.claude-team-*`、`~/.claude-max`）的 `.git` 是 `~/.claude/.git` 的 symlink，只從 `~/.claude` 正本操作，不在替代目錄 add。
- 2026-10-09 檢討：近 20 天 124 份回報只有 19 份未收為零，殘留來自 co_written、Bash 盲區、push 死結三條舊規則，本版據此改寫；證據在該日 session 的副檔。
