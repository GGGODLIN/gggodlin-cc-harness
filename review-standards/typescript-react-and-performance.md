# typescript-react-and-performance

React／Next.js、效能與一般慣例檢查。嚴重度照下列標註，與搬遷前 typescript-reviewer 的判定一致。

## 適用

角色：typescript-reviewer。改動碰到 React 或 Next.js 元件、hooks、render 內的物件與陣列、迴圈內的查詢、套件匯入，或 `console.log`、魔術數字、命名。路徑只是提示：`.tsx`、`.jsx` 先列為候選，語意相關就套用。

## MEDIUM -- React / Next.js (when applicable)
- **Missing dependency arrays**: `useEffect`/`useCallback`/`useMemo` with incomplete deps — use exhaustive-deps lint rule
- **State mutation**: Mutating state directly instead of returning new objects
- **Key prop using index**: `key={index}` in dynamic lists — use stable unique IDs
- **`useEffect` for derived state**: Compute derived values during render, not in effects
- **Server/client boundary leaks**: Importing server-only modules into client components in Next.js
- **Component defined inside another component**: Declaring a new component within a component's body recreates it on every render — remounting the subtree and discarding its state. Hoist it to module scope, or use a `renderX` helper method for inline markup.

## MEDIUM -- Performance
- **Object/array creation in render**: Inline objects as props cause unnecessary re-renders — hoist or memoize
- **N+1 queries**: Database or API calls inside loops — batch or use `Promise.all`
- **Missing `React.memo` / `useMemo`**: Expensive computations or components re-running on every render
- **Large bundle imports**: lodash 的匯入寫法照該 repo 的明文規範：專案 `CLAUDE.md`、project rules，或全域 `rules/typescript/react.md` 的 `no-full-lodash-import`（要求 `import debounce from "lodash/debounce"` 這種子模組匯入）。有明文規範就以它為準，不另憑記憶指定寫法；原本的「改用 named import」與該規範互相衝突，所以不再獨立成條。沒有明文規範時，先看 bundler 設定與套件形式（`lodash` 是 CommonJS，`lodash-es` 是 ES module），只在舉得出實際會多打進 bundle 的證據時才報，舉不出來就記為證據不足，不宣稱所有專案的 lodash 匯入都無法 tree-shake。其他套件的整包匯入同樣處理：有可 tree-shake 的替代品且證據站得住才報。

## MEDIUM -- Best Practices
- **`console.log` left in production code**: Use a structured logger
- **Magic numbers/strings**: Use named constants or enums
- **Deep optional chaining without fallback**: `a?.b?.c?.d` with no default — add `?? fallback`
- **Inconsistent naming**: camelCase for variables/functions, PascalCase for types/classes/components
