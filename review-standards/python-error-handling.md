# python-error-handling

Python 的錯誤處理與資源管理。嚴重度 CRITICAL。

## 適用

改動含 `try`／`except`、檔案或連線等需要釋放的資源，或會吞掉失敗的流程。

## 檢查項（CRITICAL）

- **Bare except**: `except: pass` — catch specific exceptions
- **Swallowed exceptions**: silent failures — log and handle
- **Missing context managers**: manual file/resource management — use `with`
