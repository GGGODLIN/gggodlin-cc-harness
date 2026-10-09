---
description: 將目前的 git repo 以 canonical absolute path 加入 ledger bootstrap 永久忽略清單，停止 SessionStart 提醒
argument-hint: 不帶參數，使用目前 cwd
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/ledger-ignore-contract.test.sh -->

# Ledger Ignore

當目前 repo 不想納入 `docs/owner/` 帳本規則時，使用 shared parser 寫入永久忽略清單。忽略清單一行一個絕對路徑；不要手動用 repo 名稱或子路徑代替 canonical repo root。

## 流程

1. 確認目前 cwd 是 `~/Desktop/work/*` 或 `~/Desktop/projects/*` 底下的 git repo。
2. 執行：

   ```bash
   python3 ~/.claude/scripts/ledger-bootstrap.py add-ignore "$PWD"
   ```

3. 從 helper 輸出讀回 canonical absolute repo root，確認它是要忽略的 repo。
4. 確認 `~/.claude/state/ledger-bootstrap-ignore.txt` 含該完整路徑且只出現一次；再次執行也不得新增重複行。
5. 回報忽略清單的完整路徑與 repo root；不要修改 repo 檔案，也不要 commit。

**完成判準**：shared helper 成功回報 canonical repo root，忽略檔有一行對應的絕對路徑，且重跑後仍只有一行；非 git repo 或工作目錄外的 repo 應停止並列出原因。
