# python-concurrency-and-frameworks

並行、同步與非同步混用、迴圈內查詢，以及 Django／FastAPI／Flask 的框架檢查。

## 適用

改動匯入或使用 `threading`、`asyncio`、Django、FastAPI、Flask，或在迴圈裡打資料庫與外部服務。檔案路徑常見於 `models.py`、`views.py`、`routers/`、`tasks`，但檔名不符時以 diff 內容為準。

## 並行與資料存取（HIGH）

- Shared state without locks — use `threading.Lock`
- Mixing sync/async incorrectly
- N+1 queries in loops — batch query

## 框架檢查

- **Django**: `select_related`/`prefetch_related` for N+1, `atomic()` for multi-step, migrations
- **FastAPI**: CORS config, Pydantic validation, response models, no blocking in async
- **Flask**: Proper error handlers, CSRF protection
