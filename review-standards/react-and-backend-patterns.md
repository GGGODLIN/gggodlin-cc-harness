# react-and-backend-patterns

React／Next.js 與 Node.js 後端的一般檢查（code-reviewer 版本）。嚴重度照下列標註，與搬遷前 code-reviewer 的判定一致；typescript-reviewer 自己的 React 與 Node 檢查在 typescript 開頭的主題組，嚴重度不同，不混用。

## 適用

角色：code-reviewer。改動是 React 或 Next.js 元件，或是 Node.js 後端的 request 處理、查詢與對外呼叫。路徑只是提示：`.tsx`、`.jsx` 與 server 端 `.ts`／`.js` 先列為候選，語意相關就套用。

## React/Next.js Patterns (HIGH)

When reviewing React/Next.js code, also check:

- **Missing dependency arrays** — `useEffect`/`useMemo`/`useCallback` with incomplete deps
- **State updates in render** — Calling setState during render causes infinite loops
- **Missing keys in lists** — Using array index as key when items can reorder
- **Prop drilling** — Props passed through 3+ levels (use context or composition)
- **Unnecessary re-renders** — Missing memoization for expensive computations
- **Client/server boundary** — Using `useState`/`useEffect` in Server Components
- **Missing loading/error states** — Data fetching without fallback UI
- **Stale closures** — Event handlers capturing stale state values

## Node.js/Backend Patterns (HIGH)

When reviewing backend code:

- **Unvalidated input** — Request body/params used without schema validation
- **Missing rate limiting** — Public endpoints without throttling
- **Unbounded queries** — `SELECT *` or queries without LIMIT on user-facing endpoints
- **N+1 queries** — Fetching related data in a loop instead of a join/batch
- **Missing timeouts** — External HTTP calls without timeout configuration
- **Error message leakage** — Sending internal error details to clients
- **Missing CORS configuration** — APIs accessible from unintended origins
