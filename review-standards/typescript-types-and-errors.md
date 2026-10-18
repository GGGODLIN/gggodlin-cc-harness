# typescript-types-and-errors

TypeScript／JavaScript 的型別安全、非同步正確性、錯誤處理與慣用寫法。嚴重度照下列標註，與搬遷前 typescript-reviewer 的判定一致；HIGH 項會擋合併。

## 適用

角色：typescript-reviewer。改動碰到 `any`、型別斷言、`tsconfig.json`、`async`／`await`、Promise、`try`／`catch`、`JSON.parse`、`throw`、模組層狀態或回呼風格程式碼。路徑只是提示：副檔名 `.ts`、`.tsx`、`.js`、`.jsx` 先列為候選，語意相關就套用。

## HIGH -- Type Safety
- **`any` without justification**: Disables type checking — use `unknown` and narrow, or a precise type
- **Non-null assertion abuse**: `value!` without a preceding guard — add a runtime check
- **`as` casts that bypass checks**: Casting to unrelated types to silence errors — fix the type instead
- **Relaxed compiler settings**: If `tsconfig.json` is touched and weakens strictness, call it out explicitly

## HIGH -- Async Correctness
- **Unhandled promise rejections**: `async` functions called without `await` or `.catch()`
- **Sequential awaits for independent work**: `await` inside loops when operations could safely run in parallel — consider `Promise.all`
- **Floating promises**: Fire-and-forget without error handling in event handlers or constructors
- **`async` with `forEach`**: `array.forEach(async fn)` does not await — use `for...of` or `Promise.all`

## HIGH -- Error Handling
- **Swallowed errors**: Empty `catch` blocks or `catch (e) {}` with no action
- **`JSON.parse` without try/catch**: Throws on invalid input — always wrap
- **Throwing non-Error objects**: `throw "message"` — always `throw new Error("message")`
- **Missing error boundaries**: React trees without `<ErrorBoundary>` around async/data-fetching subtrees

## HIGH -- Idiomatic Patterns
- **Mutable shared state**: Module-level mutable variables — prefer immutable data and pure functions
- **`var` usage**: Use `const` by default, `let` when reassignment is needed
- **Implicit `any` from missing return types**: Public functions should have explicit return types
- **Callback-style async**: Mixing callbacks with `async/await` — standardise on promises
- **`==` instead of `===`**: Use strict equality throughout
