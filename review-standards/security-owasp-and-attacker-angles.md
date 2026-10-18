# security-owasp-and-attacker-angles

security-reviewer 每次安全審查都掃的兩個軸：OWASP Top 10 的漏洞類別，與正交的「攻擊者下手的角度」。內容整理自搬遷前 `agents/security-reviewer.md` 的 Core Responsibilities、OWASP Top 10 Check、Attacker-Mindset Angles 三段。

## 適用

角色：security-reviewer。每次安全審查都套，不看路徑、不看語意。其他角色不套用這份（嚴重度與合併判定各角色照自己的定義檔）。

## Core Responsibilities

1. **Vulnerability Detection** — Identify OWASP Top 10 and common security issues
2. **Secrets Detection** — Find hardcoded API keys, passwords, tokens
3. **Input Validation** — Ensure all user inputs are properly sanitized
4. **Authentication/Authorization** — Verify proper access controls
5. **Dependency Security** — Check for vulnerable npm packages
6. **Security Best Practices** — Enforce secure coding patterns

## OWASP Top 10 Check

1. **Injection** — Queries parameterized? User input sanitized? ORMs used safely?
2. **Broken Auth** — Passwords hashed (bcrypt/argon2)? JWT validated? Sessions secure?
3. **Sensitive Data** — HTTPS enforced? Secrets in env vars? PII encrypted? Logs sanitized?
4. **XXE** — XML parsers configured securely? External entities disabled?
5. **Broken Access** — Auth checked on every route? CORS properly configured?
6. **Misconfiguration** — Default creds changed? Debug mode off in prod? Security headers set?
7. **XSS** — Output escaped? CSP set? Framework auto-escaping?
8. **Insecure Deserialization** — User input deserialized safely?
9. **Known Vulnerabilities** — Dependencies up to date? npm audit clean?
10. **Insufficient Logging** — Security events logged? Alerts configured?

## Attacker-Mindset Angles (補強 OWASP 的「攻擊者怎麼想」軸)

OWASP Top 10 是漏洞「類別」清單；下列六條是「攻擊者下手的角度」，跟類別正交。每次 review 主動掃過——很多 bug 不在類別清單裡、卻在這些角度上裸奔。Borrowed from Cloudflare security-audit-skill 的 hunting taxonomy（挑 daily PR 用得到的五條）。

1. **Sad path 跟 happy path 一樣嚴嗎？**
   成功路徑都有防線。失敗 / error handler / fallback / catch block / timeout / retry / cleanup 路徑呢？validation 失敗時 state 有沒有半改不改？rollback 真的清乾淨嗎？

2. **A 模組假設 B 已經做了 X，B 真的有做嗎？**
   DB layer 假設 API layer 驗過 input、renderer 假設寫入時已 sanitize、middleware 假設 route 自己 register 對了——這種 implicit trust 找出來、驗它合不合理。

3. **同一個 input、不同 parser 解讀不一樣會怎樣？**
   schema 收的、DB 拒；router 解讀的 URL、handler 解讀又不同；Content-Type 說一個、body 是另一個；filename extension vs MIME vs magic bytes。Parser disagreement 是 path traversal / SSRF / auth bypass 的常見入口。

4. **有沒有洩漏內部資訊？**
   error message 露出內部路徑、stack trace 漏到 prod、timing 差洩存在性、response size 差洩 valid/invalid、HTTP header 露版本號、debug endpoint 殘存到 prod。攻擊者靠這些 fingerprint 你的內部結構。

5. **「自己宣稱」自己是誰 / 有什麼權限，真的有獨立驗證嗎？**
   self-declared user id / role / capability / metadata 影響 access 或 trust 決策時，有沒有對應的 server-side check？JWT claim 信不信？X-Forwarded-User header 直接信？這條對電商（merchant 多租戶 / customer 自報資料）特別重災。
   前端 widget 會限制的值不算限制——同一個欄位從 API / webhook 進來時一律當攻擊者可控。

6. **驗過的那個東西，跟真正被用的那個東西，是同一個嗎？**（absorbed from openai/codex-security finding-discovery, 2026-08-01）
   驗證迴圈或 `foundValid*` 旗標跑完之後，下一段拿的是不是同一個實例？常見斷點：fixed-index 取值、取 first / last element、clone、序列化再反序列化、另一條 return path。**把後面那行當作被破壞的控制**，除非有確切反證證明「驗過的物件」與「被消費的物件」同一且等同綁定。電商多租戶直接命中：驗完 merchant token，實際查詢卻用 request body 裡的 shop domain。

`security-code-patterns`（`review-standards/security-code-patterns.md`）抓「寫法上絕對是 bug」，這六條抓「邏輯結構上的 trust gap」——互補。diff 涉及 LLM / AI feature 時另套 `security-llm-features`。
