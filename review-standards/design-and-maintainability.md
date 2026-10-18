# design-and-maintainability

跨檔案、整個功能或 PR 範圍的設計衰退檢查，與語言無關。嚴重度照下列標註，與搬遷前 code-reviewer 的判定一致。

## 適用

角色：code-reviewer。改動橫跨多個模組、新增抽象、碰到事件或 webhook 或佇列處理、或碰到金額與時間單位。任何語言都先列為候選，語意相關就套用。

## Design & Maintainability (HIGH)

Cross-cutting design decay — language-agnostic. These complement the size/syntax checks in `review-standards/code-review-quality.md`; flag at whole-feature / PR scope, not line-by-line. Apply the search-before-flag rule in `review-standards/finding-discipline.md` before claiming "scattered" / "duplicated" / "circular" — these need cross-file evidence.

- **Change propagation** — one class/module changing for multiple unrelated business reasons (e.g. `UserService` edited for billing AND notification AND profile logic); one logical change forcing edits across >3 unrelated files; a method using another object's data more than its own (Feature Envy); two classes reaching into each other's internals (Inappropriate Intimacy).
- **Dependency disorder** — circular dependencies between modules; high-level/domain code importing low-level infrastructure directly (DB driver, HTTP client) instead of depending on an abstraction; Law of Demeter chains `a.getB().getC().doD()`; a module importing from >5 others; an implementer using only a subset of a fat interface (ISP).
- **Domain model distortion** — business logic scattered across service layers while domain objects are getter/setter-only (anemic model); code/variable/method names diverging from what the business calls the concept; a subclass overriding or throwing on most of its parent's contract (LSP / Refused Bequest); value concepts (Money, Email) given mutable identity instead of being replaced when changed.
- **Knowledge duplication** — the same *decision* (not just code lines) expressed in multiple places; one domain concept named 3+ ways (`user` / `account` / `member` / `customer`); parallel class hierarchies that must change in lockstep.
- **Accidental complexity** — abstractions built "for future use" with a single current consumer (Speculative Generality / YAGNI); classes that only delegate without adding behavior (Middle Man); a rewrite materially more elaborate than the problem it solves (Second-System Effect).
- **Cognitive overload (beyond size/nesting in code-review-quality)** — parameter lists >4; a boolean flag parameter that switches the function between two behaviors (= two responsibilities); domain concepts passed as bare primitives (`String email`, `int orderId`) instead of purpose-built value types.
- **Event state ordering (conditional)** — when the diff touches an event, webhook, queue/job handler, async callback, or state transition, identify every state/entity it reads but does not create itself. Trace where that state is created and require a code-level ordering guarantee such as an existence check, idempotent upsert, queue dependency, transaction, or lock. Handler registration order and timing assumptions are not guarantees; flag only when a reachable execution can observe missing or stale state.
- **Unit and representation drift (conditional)** — when the diff touches money, quantity, duration, percentage, date/time, or timezone values, trace each value from creation through conversions, storage, API boundaries, and downstream reads. Verify that its meaning stays explicit and consistent: cents vs dollars, per-item vs per-pack, seconds vs milliseconds, 0–1 fraction vs 0–100 percent, and UTC vs local time. Flag only a concrete mismatch or an ambiguous boundary that can change behavior.

**What NOT to flag here** (false-positive guards): a composition root wiring concrete dependencies is not a DIP violation; DTOs / persistence records / API payload models are allowed to be data-only (not anemic); coordinated edits inside one bounded context are not shotgun surgery; a switch over a closed external enum or wire format is not missing polymorphism; repetition across separate bounded contexts is not automatically duplicate knowledge.
