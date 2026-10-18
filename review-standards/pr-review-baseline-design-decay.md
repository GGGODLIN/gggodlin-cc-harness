# pr-review-baseline-design-decay

`/pr-review` 的跨面向基準清單之一（Design Decay）。共通說明見 `pr-review-baseline-reuse`。文中的 Step 2.7、Step 2.9 指 `/pr-review` 的步驟。

## 適用

由 `/pr-review` 派出時必套：派工 prompt 寫「由 /pr-review 派出」就套用，不論語言與改動內容。其他入口派工沒有這行，不套。

## 檢查項（Design Decay）

Language-agnostic maintainability decay **visible in the diff**. The full architectural sweep belongs to `code-reviewer` (whole-feature scope) and Step 2.9 blast radius — here, flag only what the diff itself reveals. Apply Step 2.7 search-proof before claiming "scattered" / "circular".

1. **Divergent Change** — the PR edits one class/module for multiple unrelated business reasons (billing + notification + profile in one change) → suggest splitting responsibilities.
2. **Shotgun Surgery** — one logical change forced across >3 unrelated files/modules → the decision is leaked across the codebase.
3. **Feature Envy / Inappropriate Intimacy** — a new method uses another object's data more than its own; or two classes reach into each other's internal state.
4. **Wrong-direction dependency** — a new import making high-level/domain code depend directly on low-level infrastructure (DB driver, HTTP client) instead of an abstraction; or a new circular import.
5. **Law of Demeter chains** — newly added `a.getB().getC().doD()` train-wrecks.
6. **Anemic drift** — new business logic added to a service layer while the domain object it concerns stays a getter/setter data bag; or new code/names diverging from the term the business uses for the concept.
7. **Speculative Generality** — abstraction, parameters, hooks, defensive checks, or fallbacks added for needs the spec doesn't have. → 預設給 Nice / 參考用，不給 Must Fix（delete it, inline back until a real need shows）。例外：spec 明確要求 extensibility、或 strict-liability（安全 / 隱私）情境。
8. **Pass-through abstraction（deletion test）** — 新加的 wrapper class / helper / adapter / service，想像刪掉它：complexity 消失 = pass-through 無存在價值；complexity 轉移到 N 個 caller 端 = 有 leverage。→ pass-through 建議刪、直接 inline。例外：encapsulate 了 3+ 種 edge case（i18n / 空值 / 特殊字元），caller 端邊界情況集中處理 = 保留。跟 7 差異：7 是**沒 caller 的假抽象**（寫了應付未來但沒用），8 是**有 caller 但 wrapper 只做轉發**（用了但只是搬位置）。
9. **One-instance seam** — 新加的 interface / adapter / plugin point、目前只有一個實作、且沒明確跡象要加第二個。「未來會多幾家」的預測沒具體 caller 支持 = 假設性 seam。→ 預設給 Nice / 參考用；除非 spec 明確要求 multi-vendor / extension point。判準：**兩個獨立實作**才算真 seam。跟 7/8 差異：7 是**沒 caller**、8 是**只做轉發**、9 是**有 encapsulate 但只一個實作**——三姊妹涵蓋「過早抽象」smell family 三種形態。
10. **Concept-count test（假 refactor）** — PR 自稱 refactor / simplification 時：數 reader 要同時 hold 的概念數（分支 / mode / layer / 中介物）改前 vs 改後。概念數沒降、只是搬位置 = relocate not reduce → Nice / 參考用，並指出真正能讓整條 branch / mode / layer 消失的重構方向。與 7-9 三姊妹互補：三姊妹抓過早「加」抽象，這條抓無效「改」抽象。
11. **File-size vs diff-size** — diff 小不代表結構健康：判 resulting file，一個 +40 行的 diff 也可能把檔案推過健康邊界（~1000 行 total 是警訊線）。改後檔案明顯過大 → 建議 decompose-then-add，不是先塞再說。（absorbed from addyosmani/agent-skills code-review-and-quality, 2026-07-11; item 10 同源）

(Parameter sprawl, copy-paste, stringly-typed, and leaky abstractions are already covered by the `pr-review-baseline-quality` group — don't double-report.)
