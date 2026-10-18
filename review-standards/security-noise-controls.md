# security-noise-controls

控制安全 finding 噪音的三塊：常見誤報、預設不報的類別、先分路徑階級再定嚴重度。內容整理自搬遷前 `agents/security-reviewer.md` 的 Common False Positives、Excluded-by-default categories 與「先分路徑階級，再定嚴重度」三段，原文保留；Excluded-by-default 八條是這個角色「預設不報」的範圍，政策不變。

## 適用

角色：security-reviewer。每次安全審查都套，不看路徑、不看語意。其他角色不套用，各角色自己的不報範圍照自己的定義檔。

## Common False Positives

- Environment variables in `.env.example` (not actual secrets)
- Test credentials in test files (if clearly marked)
- Public API keys (if actually meant to be public)
- SHA256/MD5 used for checksums (not passwords)
- 範例 / demo 目錄、test fixture、產生出來的碼（generated）、外部塞進來的 vendored 碼 — 先分類再判是不是漏洞
- 本來就設計成可以執行使用者程式碼的擴充點（plugin hook、eval-by-design 的 sandbox 入口）— 那是規格不是缺陷，除非隔離本身破了

憑證類誤報的成員、條件與例外以必報清單為準（`review-standards/must-report.md`），這裡不另定。

**Always verify context before flagging.**

## Excluded-by-default categories (2026-07-11, from anthropics/claude-code-security-review)

Do NOT report these unless there is proven, concrete impact in this specific diff — they drown high-impact findings in noise:

- Denial of service / resource exhaustion (memory, CPU) concerns
- Missing rate limiting as a standalone finding (the Code Pattern table's rate-limit row applies to new externally-facing endpoints, not to every function)
- Generic "input should be validated" without a demonstrated exploit path
- Open redirect without a chained impact
- self-XSS 或其他沒有跨越信任邊界的影響（2026-08-01, from openai/codex-security severity-policy）
- 缺 header / cookie flag / CSP / TLS 這類衛生問題，但講不出具體利用鏈
- 「跟別的東西串起來也許就危險」——串接假設超過一層就不報
- 只展示了 bug class 的存在，沒有實際可達的利用路徑

If one of these genuinely matters (e.g. user-triggerable unbounded LLM calls = wallet DoS, `security-llm-features` 第 6 條), state the concrete impact chain — the category alone is not a finding.

## 先分路徑階級，再定嚴重度（2026-08-01, from openai/codex-security threat-model-guidance）

primary product / runtime 路徑，vs 只給開發者的 script、測試、範例、prototype、一次性工具。**後者的 finding 除非有證據顯示它真的被部署、或被特權流程呼叫，否則寫成 note、不進 CRITICAL / HIGH。** 判斷靠 repo 證據（有沒有進 build、有沒有被 route / job / CI 引用），不靠目錄名猜。

級別本身怎麼算，一律照 `~/.claude/references/severity-calibration.md`（標準目錄的 `severity-calibration` 列，原位置登記）——不要憑感覺發 CRITICAL / HIGH。
