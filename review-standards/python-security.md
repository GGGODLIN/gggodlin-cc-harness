# python-security

Python 程式碼的安全檢查。嚴重度照下列標註，與搬遷前 python-reviewer 的判定一致。

## 適用

改動碰到 SQL 查詢、shell 指令、檔案路徑、`eval`／`exec`、反序列化、YAML、加密或憑證。路徑只是提示：`auth`、`api`、`db`、`settings` 這類目錄先列為候選，但語意相關就套用。

## 檢查項（CRITICAL）

- **SQL Injection**: f-strings in queries — use parameterized queries
- **Command Injection**: unvalidated input in shell commands — use subprocess with list args
- **Path Traversal**: user-controlled paths — validate with normpath, reject `..`
- **Eval/exec abuse**, **unsafe deserialization**
- **Weak crypto** (MD5/SHA1 for security), **YAML unsafe load**

硬編金鑰不在本檔定義：成員、成立條件與例外都在 `review-standards/must-report.md`，那份是程式碼審查必套。
