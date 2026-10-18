# typescript-security

TypeScript／JavaScript 的安全檢查。嚴重度照下列標註，與搬遷前 typescript-reviewer 的判定一致；typescript-reviewer 的 CRITICAL 項會擋合併。

## 適用

角色：typescript-reviewer。改動碰到 `eval`／`new Function`、HTML 賦值、SQL 或 NoSQL 查詢、檔案路徑、物件合併、`child_process`，或憑證。路徑只是提示：副檔名 `.ts`、`.tsx`、`.js`、`.jsx` 先列為候選，語意相關就套用。

## CRITICAL -- Security
- **Injection via `eval` / `new Function`**: User-controlled input passed to dynamic execution — never execute untrusted strings
- **XSS**: Unsanitised user input assigned to `innerHTML`, `dangerouslySetInnerHTML`, or `document.write`
- **SQL/NoSQL injection**: String concatenation in queries — use parameterised queries or an ORM
- **Path traversal**: User-controlled input in `fs.readFile`, `path.join` without `path.resolve` + prefix validation
- **Prototype pollution**: Merging untrusted objects without `Object.create(null)` or schema validation
- **`child_process` with user input**: Validate and allowlist before passing to `exec`/`spawn`
- **Hardcoded secrets**（嚴重度 CRITICAL）：成員、成立條件與例外都在 `review-standards/must-report.md`，那份是程式碼審查必套，本檔不另定義。
