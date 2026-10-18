# `~/Desktop/projects/` 工作習慣

這個資料夾我用來研究 / 探索各種東西（看資料、跑 script、做 POC、寫筆記）。**只有其中一部分會轉化為正式專案**——當需要寫 code 或寫文件且未來想繼續開發時，才建立獨立專案。

## 規則：何時開新資料夾

當使用者要做以下任一類東西時，**預設建在 `~/Desktop/projects/<kebab-case-name>/`** 並 `git init`：

- 新工具 / utility / script，超過單一檔案
- 新 chrome extension / browser plugin
- 新 web app / mobile app / CLI tool
- 任何「未來想繼續開發」的東西

**不要**：
- 把多檔案專案散在 `~/Desktop/projects/` 根目錄
- 放在 `~/.claude/scripts/`（除非是純 Claude Code 環境工具，例如 hook / cmux 整合）
- 放 `/tmp/` 或當前 cwd 內 inline

## 例外

- **純 Claude Code 環境擴展**（hook / skill / cmux 工具）→ `~/.claude/scripts/` 或 plugins 系統
- **一次性 throwaway script** → 同 cwd 或 `/tmp/` OK
- **既有 project 內衍生子工具** → 該 project 內 subdirectory，不另起新 project
- **純研究 / POC**（不寫 code 或只 single-file 探索）→ 直接在 `~/Desktop/projects/` 根目錄或 `/tmp/` 即可

## 不確定時

如果不清楚這次的東西要算「研究」還是「專案」，**問一句「這個要不要做成獨立 project？」**比假設要好。

## Vibe coding 模式：git / GitHub 操作授權

`~/Desktop/projects/` 下面的所有專案都是**個人 vibe coding 專案**，原則上 agent 可以自由操作 git / github，不用每步 confirm。**本段是全域 `~/.claude/CLAUDE.md`「Git 工作流程」個人 repo 條的細則展開，不是 override**——全域已把個人 repo 的 commit / push / 開 PR 設為自動，本段只補這棵樹下的細節。

### 預設可自動執行（不用 confirm）

- `git add` + `git commit`（寫合理的 conventional commit message）
- `git push`（含建立 remote tracking；推到上游貢獻用的公開 fork 例外，依全域 git-workflow「上游貢獻第一次公開前，先審再問」）
- `git checkout -b <branch>` 建 feature branch
- `gh repo create`（公開 repo；private 要 confirm）
- `gh pr create` 開 PR（只限目標是自己的 repo；上游 PR 同上例外）
- `gh pr view` 查 PR；`gh pr comment` 只限自己的 repo（上游 PR 留言同上例外）
- `git pull` / `git fetch`

### 仍要 confirm 才能做（破壞性 / 不可逆）

- `git push --force` / `--force-with-lease` 任何 branch
- `git reset --hard` / `git checkout .` / `git restore .`（會丟未 commit 改動）
- `git branch -D` 刪 branch
- `git rebase` / `git rebase -i`（會改寫歷史）
- `git commit --amend` 已 push 過的 commit
- `gh repo delete`
- `gh pr merge`（合併到 main 是有意義的決策）
- 直接 push to `main` / `master` 在**多人協作 repo**（單人 repo OK）

### 仍維持的習慣

- Commit 前確認沒 lint / type error（否則先修）
- Conventional commits（feat / fix / docs / chore / refactor / test）
- 每個 commit 一個邏輯單元，不要把無關改動塞同一個
- 完成一段工作就 commit，別累積巨大 WIP
- Co-Authored-By trailer 保留

## Vibe coding 模式：做完的標準

- 「最小改動」以使用者說的結果為準，不以本輪找到的缺陷為準。使用者要「修到體驗正常」，修完本輪看得到的那一塊就結案，等於自己把目標縮小了。
