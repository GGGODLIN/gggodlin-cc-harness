# pr-review-baseline-quality

`/pr-review` 的跨面向基準清單之一（Quality）。共通說明見 `pr-review-baseline-reuse`。

## 適用

由 `/pr-review` 派出時必套：派工 prompt 寫「由 /pr-review 派出」就套用，不論語言與改動內容。其他入口派工沒有這行，不套。

## 檢查項（Quality）

1. **Redundant state** — state duplicating existing state, cached values that could be derived, observers/effects that could be direct calls.
2. **Parameter sprawl** — adding new params instead of generalizing or restructuring existing ones.
3. **Copy-paste with slight variation** — near-duplicate code blocks that should be unified with a shared abstraction.
4. **Leaky abstractions** — exposing internal details that should be encapsulated, or breaking existing abstraction boundaries.
5. **Stringly-typed code** — raw strings where constants, enums (string unions), or branded types already exist in the codebase.
6. **Unnecessary JSX nesting** — wrapper Boxes/elements that add no layout value; check whether inner-component props (flexShrink, alignItems, etc.) already provide the needed behavior.
7. **Nested conditionals** — ternary chains, nested if/else, or nested switch 3+ levels deep → flatten with early returns, guard clauses, a lookup table, or an if/else-if cascade.
8. **Unnecessary comments** — comments explaining WHAT the code does (well-named identifiers already do that), narrating the change, or referencing the task/caller. Keep only non-obvious WHY (hidden constraints, subtle invariants, workarounds for specific bugs).
