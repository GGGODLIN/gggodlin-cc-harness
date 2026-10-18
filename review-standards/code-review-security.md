# code-review-security

跨語言的一般安全檢查。嚴重度照下列標註，與搬遷前 code-reviewer 的判定一致；安全類 finding 的嚴重度另照 `references/severity-calibration.md` 的四格事實加矩陣算（見 code-reviewer 定義檔的輸出契約）。

## 適用

角色：code-reviewer。改動碰到憑證、查詢組字、HTML 輸出、檔案路徑、狀態變更的端點、驗證與授權、相依套件或 log 內容。任何語言都先列為候選，語意相關就套用。

## Security (CRITICAL)

These MUST be flagged — they can cause real damage:

- **SQL injection** — String concatenation in queries instead of parameterized queries
- **XSS vulnerabilities** — Unescaped user input rendered in HTML/JSX
- **Path traversal** — User-controlled file paths without sanitization
- **CSRF vulnerabilities** — State-changing endpoints without CSRF protection
- **Authentication bypasses** — Missing auth checks on protected routes
- **Insecure dependencies** — Known vulnerable packages
- **Exposed secrets in logs** — Logging sensitive data (tokens, passwords, PII)
- **Hardcoded credentials**（嚴重度 CRITICAL）：成員、成立條件與例外都在 `review-standards/must-report.md`，那份是程式碼審查必套，本檔不另定義。
