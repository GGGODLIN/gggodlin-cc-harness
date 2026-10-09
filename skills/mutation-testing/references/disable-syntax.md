# Stryker Disable Comment Syntax

放錯位置會 **silently 失效**——mutation 照跑、comment 沒用。以下規則必看。

## Table of contents
- [基本語法](#basic)
- [位置限制](#location)
- [常見 mutator 名字](#mutators)
- [Nesting 陷阱](#nesting)

<a id="basic"></a>
## 基本語法

### 單行 disable
```ts
// Stryker disable next-line <MutatorName>
const result = specificValue
```
只 disable **下一行** 的指定 mutator。

### 多行 disable / restore
```ts
// Stryker disable <MutatorName>
const a = 1
const b = 2
const c = 3
// Stryker restore <MutatorName>
```
中間所有行都 disable 該 mutator。

### 全部 disable
```ts
// Stryker disable all
function readConfig(path) {
  return fs.readFileSync(path, 'utf-8')
}
// Stryker restore all
```
用於 I/O wrapper、不做 unit test 的整段。**Use sparingly**——會遮掉真的 bug。

<a id="location"></a>
## 位置限制（放錯的失效模式）

Comment 必須在 **statement level**、對應到完整 statement 前一行。

### ❌ 錯 1：放 object literal 內部（欄位之前）

```ts
const config = {
  // Stryker disable next-line StringLiteral    ← 失效
  name: 'foo',
  value: 42,
}
```

**修法**：放到整個 object 前面 disable 該 mutator 一段：

```ts
// Stryker disable StringLiteral
const config = {
  name: 'foo',
  value: 42,
}
// Stryker restore StringLiteral
```

或直接寫 test kill 那個 mutant（優先——disable 是不得已）。

### ❌ 錯 2：放 method chain 中間

```ts
items
  // Stryker disable next-line ArrayDeclaration    ← 失效
  .filter(x => x > 0)
  .map(f)
```

**修法**：把 chain 前一步或整個 statement 前面加 disable：

```ts
// Stryker disable next-line ArrayDeclaration
const positives = items.filter(x => x > 0).map(f)
```

### ❌ 錯 3：放 expression 中間

```ts
const value = someFunc() +
  // Stryker disable next-line ArithmeticOperator   ← 失效
  otherFunc()
```

**修法**：拆成兩個 statement，disable 放對應 statement 前。

### ✅ 對：放 statement 前

```ts
// Stryker disable next-line ConditionalExpression
if (arr.length === 0) return []
```

<a id="mutators"></a>
## 常見 mutator 名字

寫 disable comment 時要用**精準** mutator 名（case-sensitive）：

| Mutator | 對付什麼 |
|---|---|
| `ArithmeticOperator` | `+` `-` `*` `/` `%` 互換 |
| `ArrayDeclaration` | `[]` 換成 `["Stryker was here"]` |
| `ArrowFunction` | Arrow function body 移除 |
| `BlockStatement` | Block 內容清空 |
| `BooleanLiteral` | `true` ↔ `false` |
| `ConditionalExpression` | `if` 條件強制 `true` / `false` |
| `EqualityOperator` | `==` `===` `!=` `!==` `<` `>` `<=` `>=` 互換 |
| `LogicalOperator` | `&&` ↔ `\|\|` |
| `MethodExpression` | 方法呼叫（`.filter`、`.map` 等）移除或換 |
| `ObjectLiteral` | Object 清空成 `{}` |
| `OptionalChaining` | `?.` 移除 |
| `StringLiteral` | 字串換空字串或 `"Stryker was here"` |
| `UnaryOperator` | `!` `-` 移除 |
| `UpdateOperator` | `++` ↔ `--` |

**取名策略**：先跑 stryker、看 report 裡 survived mutant 的 `mutatorName` 欄位、複製貼上到 comment。不要用記憶——case 錯 comment 失效。

<a id="nesting"></a>
## Nesting 陷阱

Inner `restore` 會 re-enable、即使在 outer `disable all` 內：

```ts
// Stryker disable all
function foo() {
  // Stryker disable ArithmeticOperator
  const a = 1 + 2
  // Stryker restore ArithmeticOperator    ← 這行 re-enable ArithmeticOperator
  const b = 3 * 4                          ← 這行 ArithmeticOperator 會被 mutate（雖然在 disable all 內！）
}
// Stryker restore all
```

**避免 nesting**——一段 code 只用一種 disable/restore 邊界。若需要複雜組合、改用單行 `Stryker disable next-line` 逐行標。

## 寫 disable comment 的紀律

每個 disable comment 旁邊寫 **why**（不是 what）：

```ts
// ❌ 沒資訊
// Stryker disable next-line ConditionalExpression
if (arr.length === 0) return []

// ✅ 記原因
// Stryker disable next-line ConditionalExpression
// early-return optimization; [].map(f) === [] so removing this guard is equivalent
if (arr.length === 0) return []
```

未來 review 才知道為什麼 disable、不是隨手蓋章。

## Verify comment 生效

加了 disable comment 後 rerun stryker、確認：

- 該 mutant 從 survived 清單消失（或標成 Ignored）
- 分數 summary 有變（total mutant 數減少）

若 rerun 分數沒變、mutant 還在 → comment 位置錯了、往 [位置限制](#location) 段找誤放模式。
