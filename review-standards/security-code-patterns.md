# security-code-patterns

「寫法上絕對是 bug」的程式碼模式表，帶嚴重度與修法。內容整理自搬遷前 `agents/security-reviewer.md` 的「Code Pattern Review」表，表內文字原樣保留。

## 適用

角色：security-reviewer。每次安全審查都套。其他角色不套用這張表；它們的嚴重度與修法各照自己的主題組。

## 與必報清單的關係

本表只提供 security-reviewer 專屬的嚴重度與修法。成員判定以必報清單為準（`review-standards/must-report.md`）：表中與必報清單重疊的列，成立條件、直接報或當訊號、以及例外，都照必報清單，不照本表字面；本表不是第二份必報成員清單，也不新增必報項。

## Code Pattern Review

Flag these patterns immediately:

| Pattern | Severity | Fix |
|---------|----------|-----|
| Hardcoded secrets | CRITICAL | Use `process.env` |
| Shell command with user input | CRITICAL | Use safe APIs or execFile |
| String-concatenated SQL | CRITICAL | Parameterized queries |
| `innerHTML = userInput` | HIGH | Use `textContent` or DOMPurify |
| `fetch(userProvidedUrl)` | HIGH | Whitelist allowed domains; beware DNS-rebind TOCTOU — allowlist check resolves DNS once, `fetch` resolves again, short-TTL record can rebind to internal IP between the two → resolve once and connect to the pinned IP. 另兩種偽防護：allowlist 可選或預設為空 = 不算防護；只在 redirect 之前驗過 = 沒驗（follow redirect 後要重驗） |
| Plaintext password comparison | CRITICAL | Use `bcrypt.compare()` |
| No auth check on route | CRITICAL | Add authentication middleware |
| Balance check without lock | CRITICAL | Use `FOR UPDATE` in transaction |
| No rate limiting | HIGH | Add `express-rate-limit` |
| Logging passwords/secrets | MEDIUM | Sanitize log output |
