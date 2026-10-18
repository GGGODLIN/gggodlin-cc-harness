# code-review-quality

跨語言的程式碼品質、效能與一般慣例檢查，含降級模式的有界檢查。嚴重度照下列標註，與搬遷前 code-reviewer 的判定一致。

## 適用

角色：code-reviewer。任何語言的程式碼改動都先列為候選。降級模式一項只在 diff 新增 catch、fallback、retry 或 skip-and-continue 路徑時才適用。

## Code Quality (HIGH)

- **Large functions** (>50 lines) — Split into smaller, focused functions
- **Large files** (>800 lines) — Extract modules by responsibility
- **Deep nesting** (>4 levels) — Use early returns, extract helpers
- **Missing error handling** — Unhandled promise rejections, empty catch blocks
- **Bounded degraded modes** — When a diff adds a catch, fallback, retry, or skip-and-continue path, verify the degraded state is observable and has an explicit threshold that escalates or aborts. Do not require every layer to log; require the failure to surface once at the boundary that owns the operational context.
- **Mutation patterns** — Prefer immutable operations (spread, map, filter)
- **console.log statements** — Remove debug logging before merge
- **Missing tests** — New code paths without test coverage
- **Dead code** — Commented-out code, unused imports, unreachable branches

## Performance (MEDIUM)

- **Inefficient algorithms** — O(n^2) when O(n log n) or O(n) is possible
- **Unnecessary re-renders** — Missing React.memo, useMemo, useCallback
- **Large bundle sizes** — Importing entire libraries when tree-shakeable alternatives exist
- **Missing caching** — Repeated expensive computations without memoization
- **Unoptimized images** — Large images without compression or lazy loading
- **Synchronous I/O** — Blocking operations in async contexts

## Best Practices (LOW)

- **TODO/FIXME without tickets** — TODOs should reference issue numbers
- **Missing JSDoc for public APIs** — Exported functions without documentation
- **Poor naming** — Single-letter variables (x, tmp, data) in non-trivial contexts
- **Magic numbers** — Unexplained numeric constants
- **Inconsistent formatting** — Mixed semicolons, quote styles, indentation
