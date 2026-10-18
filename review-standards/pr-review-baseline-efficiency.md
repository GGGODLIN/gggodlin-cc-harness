# pr-review-baseline-efficiency

`/pr-review` 的跨面向基準清單之一（Efficiency）。共通說明見 `pr-review-baseline-reuse`。

## 適用

由 `/pr-review` 派出時必套：派工 prompt 寫「由 /pr-review 派出」就套用，不論語言與改動內容。其他入口派工沒有這行，不套。

## 檢查項（Efficiency）

1. **Unnecessary work** — redundant computations, repeated file reads, duplicate network/API calls, N+1 patterns.
2. **Missed concurrency** — independent operations run sequentially when they could run in parallel.
3. **Hot-path bloat** — new blocking work added to startup or per-request/per-render hot paths.
4. **Recurring no-op updates** — state/store updates inside polling loops, intervals, or event handlers that fire unconditionally → add a change-detection guard. If a wrapper function takes an updater/reducer callback, verify it honors same-reference returns (otherwise callers' early-return no-ops are silently defeated).
5. **TOCTOU pre-check anti-pattern** — pre-checking file/resource existence before operating → operate directly and handle the error.
6. **Memory** — unbounded data structures, missing cleanup, event listener leaks.
7. **Overly broad operations** — reading entire files when only a portion is needed, loading all items when filtering for one.
