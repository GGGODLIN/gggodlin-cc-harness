# finding-discipline

提出 finding 前的查證紀律：宣稱「缺 X」「該處理 Y」前先搜，再附搜尋證據。內容整理自搬遷前 code-reviewer、typescript-reviewer 兩份定義檔的同名段落，以及 security-reviewer 的 Context-Gathering Discipline；各角色的差異留在「角色分支」，嚴重度與合併判定不在本檔，各角色照自己的定義檔。

## 適用

審查會提出「缺 X」「該處理 Y」「沒驗證」「沒測試」「重造輪子」「該用現成工具」這類 finding 時，每次都套。第二層必報項（見 `review-standards/must-report.md`）不在本檔的搜尋要求內：diff 本身就證明成立的缺陷直接報。

## 先搜再報（MANDATORY before flagging）

Before flagging findings of the form "missing X" / "should handle Y" / "no error handling" / "no validation" / "not tested" / "reinventing wheel" / "should use existing utility", you MUST verify the gap is real by searching the codebase first.

Search tools in preference order:
1. `mcp__semble__search` — semantic + BM25 code search (NL query 或 exact 名字都直接餵；已知 file:line 找相似 code 用 `mcp__semble__find_related`)
2. `Grep` with keyword/regex — always available fallback

Every such finding must attach:
- What you searched for (query + tool used)
- What you found (file:line citations, even for partial matches)
- Why the finding still stands despite what was found

If the pattern IS already handled elsewhere → do NOT flag. Drop it.

If genuinely missing → flag with search-proof. Examples:
> searched for "null check userId" via Grep + semble; only match at `src/middleware/auth.ts:42` covers the API entry path, not the new direct invocation in `src/jobs/sync.ts:88`

> searched "zod schema validation for request body" via semble; only hit is `src/routes/users.ts:14` using zod for POST /users; the new `PATCH /users/:id` handler in `src/routes/users.ts:88` has no equivalent validation

Scope exclusions (this rule does NOT apply to):
- Bugs within the diff itself (logic errors, typos visible in changed lines)
- Style / formatting

角色分支（只對該角色多一條例外，其他角色不套）：
- code-reviewer：Cross-file trust-boundary security issues requiring architectural reasoning
- typescript-reviewer：Type-system violations detectable by `tsc` (already covered by diagnostic commands)

Rationale: false-positive findings from insufficient context waste review cycles and erode trust. Search-before-flag raises the bar to real problems only.

## 信心過濾（角色：code-reviewer）

Report issues you would defend in review; skip the rest.

- **Skip** stylistic preferences unless they violate project conventions
- **Skip** issues in unchanged code unless they are CRITICAL security issues
- **Consolidate** similar issues (e.g., "5 functions missing error handling" not 5 separate findings)
- **Prioritize** issues that could cause bugs, security vulnerabilities, or data loss

## 角色分支：security-reviewer

角色：security-reviewer。搬遷前 security-reviewer 有自己的 Context-Gathering Discipline，觸發條件、舉證內容與「已受保護」的處理比上面的通用版更嚴，這些只對 security-reviewer 套用，不擴大到其他角色。上面「角色分支」兩條例外（code-reviewer 的跨檔信任邊界、typescript-reviewer 的 `tsc` 可抓型別錯誤）不適用 security-reviewer；上面的範圍排除（diff 內可見的邏輯錯誤、typo、風格）也不放寬下列「缺 X」類 finding，這類一律先搜，唯一跳過搜尋的是必報清單第二層。

Before flagging security findings of the form "missing validation" / "no auth check" / "unsanitized input" / "missing rate limit" / "no CSRF protection", you MUST verify the control is actually absent by searching the codebase first. Framework defaults, upstream middleware, and cross-cutting guards often provide protection that isn't visible in the changed file.

Every such finding must attach:
- What you searched for (query + tool used)
- What you found at trust boundaries (middleware, routers, framework config, file:line)
- Why the finding still stands given the upstream controls

If a protective control IS already in place at an upstream boundary that covers the new code path → do NOT flag as missing. Note it as "confirmed protected by X at Y" if worth recording.

If genuinely missing / bypassable / the upstream control has a gap → flag with search-proof attached. Example:
> searched "auth middleware" via semble; found `src/middleware/requireAuth.ts:12` applied to `/api/*` routes in `src/routes/index.ts:45`; new endpoint `src/routes/public/webhook.ts:8` is registered outside the `/api/*` tree and has no equivalent guard

跳過搜尋的例外：必報清單第二層（`review-standards/must-report.md`）的項目符合該層條件時，不需要上游保護分析，直接報；本檔不列成員。

Rationale: insufficient context produces noisy security reviews that get ignored. Search-before-flag keeps the reviewer credible; the must-report direct tier preserves detection of unambiguous defects. 反向的「撤掉 finding 要舉證」門檻在 `review-standards/security-suppression-evidence.md`。
