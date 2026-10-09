# Survived Mutant Patterns

Table of contents:
- [Pattern 1: ObjectLiteral 沒 assert 內容](#p1)
- [Pattern 2: StringLiteral 沒 assert 值](#p2)
- [Pattern 3: ArrayDeclaration 沒探邊界](#p3)
- [Pattern 4: `.join(sep)` separator](#p4)
- [Pattern 5: Early-return optimization](#p5)
- [Pattern 6: I/O method call](#p6)

前 3 個是 CC 產 test 的三大盲點（proj 2026-07-09 首跑實測），後 3 個是通用 mutation testing pattern。

---

<a id="p1"></a>
## Pattern 1: ObjectLiteral 沒 assert 內容

### 判準
Source code 產出 object literal、test 只驗 flow 走到那個分支 / 只驗 return 存在，沒 assert object 具體欄位值。

### Mutation 例
```ts
// Source
function getSections() {
  return {
    cvsWidget: 'appEmbed',
    cvsCheckout: 'appBlock',
    invoiceAtThankYou: 'appBlock',
  }
}
```

Stryker 產的 mutant：
- `return {}`（清空 object）
- `cvsWidget: ''`（單 field 換空字串）
- `cvsCheckout: ''`

若 test 都過 → 這 test 沒 assert object 內容。

### Test theater 版
```ts
test('getSections returns something', () => {
  const s = getSections()
  expect(s).toBeDefined()  // 只驗存在
})
```

### 修法（A：補 value assertion）
```ts
test('getSections returns correct mapping', () => {
  expect(getSections()).toEqual({
    cvsWidget: 'appEmbed',
    cvsCheckout: 'appBlock',
    invoiceAtThankYou: 'appBlock',
  })
})
```

用 `.toEqual` 或針對關鍵欄位 `.toBe`——不要用 `.toMatchObject`（partial match、mutation 清空還會過）。

---

<a id="p2"></a>
## Pattern 2: StringLiteral 沒 assert 值

### 判準
Source 用了特定 string 值（狀態碼、type discriminator、i18n key），test 只驗回傳 truthy 或型別。

### Mutation 例
```ts
// Source
function classify(user) {
  if (user.plus) return 'plus'
  return 'basic'
}
```

Mutant：
- `return 'plus'` → `return ''`
- `return 'basic'` → `return ''`

### Test theater 版
```ts
test('classify handles plus', () => {
  expect(typeof classify({plus: true})).toBe('string')  // 只驗型別
})
```

### 修法（A）
```ts
test('classify returns plus tier for plus user', () => {
  expect(classify({plus: true})).toBe('plus')
  expect(classify({plus: false})).toBe('basic')
})
```

`.toBe(exactString)` 直接對 string literal。

---

<a id="p3"></a>
## Pattern 3: ArrayDeclaration 沒探邊界

### 判準
Source 有 `value ?? []` / `value ?? [defaultItem]` 這種 fallback，test 沒測 nullish input。

### Mutation 例
```ts
// Source
function hasFeature(features, target) {
  return (features ?? []).includes(target)
}
```

Mutant：
- `features ?? []` → `features ?? ["Stryker was here"]`
- `features ?? []` → `features ?? [target]`

若 test 都過 → nullish 分支根本沒觸發。

### Test theater 版
```ts
test('hasFeature works', () => {
  expect(hasFeature(['a', 'b'], 'a')).toBe(true)  // 只測 features 非 null 的 case
})
```

### 修法（A：補 null case）
```ts
test('hasFeature returns false when features is nullish', () => {
  expect(hasFeature(null, 'a')).toBe(false)
  expect(hasFeature(undefined, 'a')).toBe(false)
})
```

**若無法從 caller 觸發 nullish（type 保證非 null）** → 判定為 **C（合法 NoCoverage）**、不要硬造 test。此時 Stryker 也會標成 `# no cov`。

---

<a id="p4"></a>
## Pattern 4: `.join(sep)` separator

### 判準
Source 用 `.join(', ')` 或類似，test 用單元素 array（separator 不出現）。

### Mutation 例
```ts
items.join(', ')  // mutant: items.join('')
```

單元素 array `['x'].join(', ')` = `'x'`、`['x'].join('')` = `'x'`——**兩者結果一樣、mutant 存活**。

### 修法
Test 至少 2 個元素：
```ts
expect(format(['a', 'b'])).toBe('a, b')  // separator 出現
```

---

<a id="p5"></a>
## Pattern 5: Early-return optimization

### 判準
Guard clause 是 optimization 而非邏輯必需——移除後行為相同。

### Mutation 例
```ts
// Source
function process(arr) {
  if (arr.length === 0) return []  // optimization
  return arr.map(transform)
}
```

Mutant：移除整個 if——但 `[].map(transform)` = `[]`、結果一樣、**mutant 存活但這是合法等價**。

### 修法（B：加 disable comment）
```ts
// Stryker disable next-line ConditionalExpression
if (arr.length === 0) return []
return arr.map(transform)
```

Comment 位置注意：**必須在 statement 前一行**、不能放 object literal 內、不能放 method chain 中間——見 `disable-syntax.md`。

---

<a id="p6"></a>
## Pattern 6: I/O method call

### 判準
Function 呼叫 `fs.*` / `fetch` / `child_process.*` / DB client——mutation 產出的變體實務上無 unit test 可觸發。

### Mutation 例
```ts
function readConfig(path) {
  return fs.readFileSync(path, 'utf-8')  // mutant: 換 encoding、換 method
}
```

### 修法（C：block disable）
```ts
// Stryker disable all
function readConfig(path) {
  return fs.readFileSync(path, 'utf-8')
}
// Stryker restore all
```

或 refactor 把 pure logic 拉出來單獨測——I/O wrapper 用 integration test 驗（不同層級）。

---

## Meta pattern：AI 產 test 的 tell

以下 assertion 型態 = 高機率 test theater（碰到請當紅旗）：

- `.toBeDefined()` — 只驗存在
- `.toBeTruthy()` / `.toBeFalsy()` — 只驗 boolean coercion
- `.not.toThrow()` — 只驗沒炸
- `typeof x === 'string'` — 只驗型別
- `.toBeInstanceOf(Object)` — 幾乎驗不到東西
- Snapshot test（`.toMatchSnapshot()` 沒對照關鍵欄位）

看到這些 → 讀對應 source function → 大概率 mutation testing 會抓到一堆 survived。
