# typescript-node-and-dependencies

Node.js 邊界檢查與 `package.json` 依賴衛生。嚴重度照下列標註，與搬遷前 typescript-reviewer 的判定一致。

## 適用

角色：typescript-reviewer。改動碰到 request handler、檔案 I/O、外部資料輸入、`process.env`、模組系統（ESM／CommonJS），或 diff 含 `package.json`。路徑只是提示：`package.json` 與 server 端 `.ts`／`.js` 先列為候選，語意相關就套用。

## HIGH -- Node.js Specifics
- **Synchronous fs in request handlers**: `fs.readFileSync` blocks the event loop — use async variants
- **Missing input validation at boundaries**: No schema validation (zod, joi, yup) on external data
- **Unvalidated `process.env` access**: Access without fallback or startup validation
- **`require()` in ESM context**: Mixing module systems without clear intent

## MEDIUM -- package.json / Dependency Hygiene (when package.json is in the diff)
- **Unpinned versions**: A dependency added as `latest` or `*` — pin a specific version or a constrained range so installs stay reproducible.
- **Duplicate dependency declaration**: The same package listed in both `dependencies` and `devDependencies` — keep it in exactly one place.
- **Undeclared script tooling**: A tool invoked in `scripts` (`eslint`, `jest`, `prettier`, `tsc`, etc.) that is absent from `devDependencies` — declare it so the script survives a clean install.
