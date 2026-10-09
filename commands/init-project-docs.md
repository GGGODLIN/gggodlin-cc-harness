---
description: 在目前的 git repo 建立 docs/owner/STATE.md 與帳本 log 骨架、加入本地 exclude，並把帳本生命週期指針寫入 repo CLAUDE.md
argument-hint: 不帶參數，使用目前 cwd
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/init-project-docs-contract.test.sh -->

# Init Project Docs

在目前 cwd 對應的 git repo 建立 `docs/owner/` 初始骨架。這個 command 只處理新 repo；如果 `docs/owner/STATE.md` 已存在，就停止，不要覆蓋現有內容。

## 流程

1. 確認目前 cwd 是 `~/Desktop/work/*` 或 `~/Desktop/projects/*` 底下的 git repo。不要用目前字串路徑直接寫入，讓 shared helper 解析 canonical repo root。
2. 執行：

   ```bash
   python3 ~/.claude/scripts/ledger-bootstrap.py init-project-docs "$PWD"
   ```

3. 確認輸出列出的 repo root 與預期一致，並確認以下檔案已建立或保留：
   - `docs/owner/STATE.md`
   - `docs/owner/factcheck-log.md`
   - `docs/owner/proofread-log.md`
   - `docs/owner/syndication-log.md`
   - `docs/owner/friction-log.md`
4. 確認 `docs/owner/` 只寫進該 repo 的 `.git/info/exclude`，沒有改 `.gitignore`。
5. 確認 repo `CLAUDE.md` 只有一份以下指針段，且內容指向規則正本：

   ```markdown
   ## 帳本生命週期

   > 帳本生命週期：規則見 `~/.claude/references/ledger-lifecycle.md`；門檻以 `~/.claude/scripts/ledger-lifecycle/registry.json` 為準。
   ```

6. 回報建立、保留與接線驗證結果；不要 commit。

**完成判準**：`STATE.md`、四個 log 檔頭、`.git/info/exclude` 的 `docs/owner/`、以及 repo `CLAUDE.md` 的帳本指針都能逐項驗證；任一項失敗就列出缺口，不把部分建立報成完成。
