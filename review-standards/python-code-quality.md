# python-code-quality

函式與檔案的規模、巢狀、重複與魔術數字。嚴重度 HIGH。

## 適用

任何 `.py` 改動，尤其是新增或加長函式。

## 檢查項（HIGH）

- Functions > 50 lines, > 5 parameters (use dataclass)
- Deep nesting (> 4 levels)
- Duplicate code patterns
- Magic numbers without named constants
