# project-conventions

專案自己的慣例（`CLAUDE.md`、project rules）如何併入審查。本檔不改變專案規範能否覆蓋使用者底線這件事，那條沿用各流程現狀。

## 適用

角色：code-reviewer、typescript-reviewer、python-reviewer。被審的 repo 有 `CLAUDE.md` 或 project rules。

When available, also check project-specific conventions from `CLAUDE.md` or project rules:

- File size limits (e.g., 200-400 lines typical, 800 max)
- Emoji policy (many projects prohibit emojis in code)
- Immutability requirements (spread operator over mutation)
- Database policies (RLS, migration patterns)
- Error handling patterns (custom error classes, error boundaries)
- State management conventions (Zustand, Redux, Context)

反向過時檢查（code 改動讓文件過時）：

- 如果這次 diff 改動了檔案路徑、腳本／CLI 指令、環境變數、設定鍵名或常數預設值，導致本次已讀入的 `CLAUDE.md` 或專案規則檔裡某一行敘述變成過時資訊，附上 `文件檔名:行號` 與 `diff 檔名:行號` 報出。只對本次已讀入的規則檔核對，不另外掃描整個 repo 的其他文件。

防本 PR 自改規則開脫（以比較範圍起點為準）：

- 語言 reviewer 的預設 diff 可能只過濾程式檔（如 `*.ts`、`*.py`），看不到規則檔在同一比較範圍內被改過。套用任何已讀入的 `CLAUDE.md` 或專案規則檔前，先跑 `git diff <比較範圍> -- <規則檔路徑>` 檢查該檔是否在本次比較範圍內被修改；若有修改，新增的放寬、排除或例外條款不得用來豁免同一個 PR 自己的程式碼，須用比較範圍起點（base）上的版本判定是否違規，並標出同 PR 自改規則。

Adapt your review to the project's established patterns. When in doubt, match what the rest of the codebase does.
