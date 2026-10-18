# Git 工作流程

- Branch 命名：`feat/`, `fix/`, `docs/`, `refactor/`
- Commit 前確認沒有 lint 錯誤
- **Commit 一律自動、不問**（含公司 repo）：完成一段工作就 commit；一個 commit 一個邏輯單元，不累積巨大 WIP，不使用籠統的 `chore: sync`；一個 Bash 只放一條 git 指令（不串兩個 `git -C`、不用 `$(…)` 或 heredoc 組 commit message），否則 commit gate 會擋、白費一次呼叫
- 多個 session 共用同一 repo 時，commit 前先用 `git diff --cached --name-only` 確認 index 只含本 session 的檔案；可用 pathspec 時以 `git commit -- <files>` 限定，若 gate 不允許 pathspec，就先單獨 `git add`、驗 index，再用普通 commit
- **個人單人 repo 預設 direct-to-main**：完成驗證後，直接讓本任務 commits 進入並 push `main`；不要因 branch、worktree 或 `gh pr create` 已獲授權，就把 feature branch＋PR 當成預設交付路徑。只有使用者明確要求、repo 是多人協作，或 repo 明訂必須經 PR review 時才走 PR。
- **任務收尾跑 `/self-closeout`**：本 session 的任務驗證完成、準備回報結案時，先 invoke `/self-closeout` 收自己改過的檔（範圍是本 session 寫過的每個 repo，不是 cwd）；它只 commit 證明得了是自己的變更，其餘留給使用者手打的 `/git-closeout` 全機收。不對其他 session 發 SendMessage。
- **Native pre-push inclusion**：feature session 仍自行執行 `/self-closeout`；native `pre-push` 只做 push 前 `main` inclusion 檢查，push 後仍要用 `/self-closeout` 的第 4 步核對發布範圍；全機 reconciliation 由使用者手打 `/git-closeout`。`--no-verify` 不在保證範圍；force push 仍須既有 human confirm。
- client hook 不提供 remote force race 或 final-read race 的原子保證；remote API、被刪除或修改的 hook 也不在 native gate 保證範圍。
- 安裝後另設 worktree-specific core.hooksPath 會繞過，/git-closeout 要查；命令列 -c core.hooksPath 也會繞過。
- **Branch／worktree 只負責隔離**：如果實作或 review 需要非 `main` branch，收尾仍從最新 `origin/main` 的 clean checkout 套入本任務 commits並直接 push `main`。shared checkout 有其他 session 的未提交改動時不得碰它；改用 clean worktree。無法安全 fast-forward 時停止並回報，不得自行降級成開 PR。
- **多 GitHub 帳號路由**：gh 同時登入 `example-work-account`（active、工作）、`example-owner`（個人）、`example-old-account`（舊）。**不要跑 `gh auth switch`**，它改全域 active、會影響其他 session。個人 repo（remote 是 `example-owner/*`）的 git push／pull 走 SSH remote（`git@github.com:example-owner/…`，本機 SSH key 已綁 example-owner）；新 clone 或新 `gh repo create` 的個人 repo 一律用 SSH URL。個人 repo 的 gh API 操作（`gh pr create`／`gh repo view` 等）用 `GH_TOKEN=$(gh auth token -u example-owner) gh …` 逐條指定，不切帳號。工作 repo 維持 https 走 gh active 帳號。push 遇 `Repository not found` 先看 remote 是 https 還是 SSH，不要先猜帳號
- **Push 與開 PR 分兩檔，判定依據是路徑，不是 repo 名**：
  - 個人 repo（`~/.claude`、`~/code/*`、`~/Desktop/projects/*`）→ `git push`、`gh pr create` 不必問
  - 公司 repo（**`~/Desktop/work/` 全樹**，無論該 repo 是否已在本檔出現過）→ `git push` 與 `gh pr create` / PR 開單**一律先問**
- **上游貢獻第一次公開前，先審再問**（優先於上面「個人 repo 不必問」）：對別人 repo（owner 不是 `example-owner`）的貢獻，內容第一次公開前——推到公開 fork、`gh pr create`（含 `--dry-run`，它也可能 push）、`gh pr comment`、`gh pr edit`、PR review 留言，改用其他工具也算——走下面三步；一次確認可涵蓋「push 這版＋開這個 PR」。審查點若只放在開 PR，fork 一推內容就已公開，審了也擋不住
  1. 先跑 `~/.claude/scripts/upstream-pr-bundle.sh --repo <repo> --base <上游基準，如 upstream/main> --title <標題> --body-file <內文檔> --out <scratchpad 檔>` 打包，再把它印出的 `BUNDLE_PATH`／`BUNDLE_TOTAL_LINES` 兩行原樣交給 `upstream-pr-reviewer`。這支 agent 只有 Read：它要讀別人寫的內容，被騙也發不出東西，所以不改派帶全套工具的 agent 代審
  2. `VERDICT: CLEAR` 或 `ISSUES` 帶著它的三欄回報進第 3 步；`INCOMPLETE`（讀檔失敗、內容截斷）、subagent 失敗或空輸出都算沒查完、不算通過，先補齊或向使用者講明缺口
  3. 問使用者時依序貼：公開風險與未查項、目標 repo 與基準分支、待送 commit SHA、標題與內文全文。使用者同意的是這一組；之後任何一項變了（含主 session 修稿、分支多了 commit），舊同意作廢，只就變動部分補審再問（打包時加 `--since <上次審過的打包檔>`，只輸出差異；歷史被改寫時腳本自動退回整包）
  - 這是降低疏漏的流程、不是防外洩保證：靠 agent 遵守，沒有 hook 攔截；審查員判斷是機率性的，讀得到記憶也可能漏
- **仍要 confirm（所有 repo 一律）**：`push --force` / `--force-with-lease`、`reset --hard`、`checkout .` / `restore .`、`branch -D`、`rebase`、`commit --amend` 已 push 過的 commit、`gh repo delete`、使用者已明確選擇 PR 路徑後的 `gh pr merge`、多人協作 repo 直推 `main` / `master`
