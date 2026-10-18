# python-typing-and-idioms

型別標註、Pythonic 寫法與 PEP 8 慣例。三個層級保留搬遷前的嚴重度。

## 適用

任何 `.py` 改動。

## 型別標註（HIGH）

- Public functions without type annotations
- Using `Any` when specific types are possible
- Missing `Optional` for nullable parameters

## Pythonic 寫法（HIGH）

- Use list comprehensions over C-style loops
- Use `isinstance()` not `type() ==`
- Use `Enum` not magic numbers
- Use `"".join()` not string concatenation in loops
- **Mutable default arguments**: `def f(x=[])` — use `def f(x=None)`

## 慣例（MEDIUM）

- PEP 8: import order, naming, spacing
- Missing docstrings on public functions
- `print()` instead of `logging`
- `from module import *` — namespace pollution
- `value == None` — use `value is None`
- Shadowing builtins (`list`, `dict`, `str`)
