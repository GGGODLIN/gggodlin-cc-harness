# 能力題組

腳本在 `~/Desktop/projects/local-llm-gateway/bench/`，移植自 2026-09-15 的 帳號池轉接服務 評估。原版硬編了 cline 的 endpoint、key 與 `x-api-key` 認證樣式，移植後改由 `client.py` 讀 env，任何 OpenAI 相容端點都能跑。

## 環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `BENCH_BASE_URL` | `http://127.0.0.1:8000/v1` | 端點 |
| `BENCH_API_KEY` | `sk-1234` | 金鑰 |
| `BENCH_AUTH_STYLE` | `bearer` | 或 `x-api-key` |
| `BENCH_DELAY` | `1.5` | 每次請求間隔秒數，撞 429 就調大 |
| `BENCH_TIMEOUT` | `300` | 單次請求逾時 |

## 各支腳本

| 腳本 | 測什麼 | 跑法 |
|---|---|---|
| `smoke.py` | 接線十二道探針（階段二用） | `python3 smoke.py <model> 3` |
| `suite.py` | codeA 滑動視窗、codeB 拓樸排序、單輪 tool loop | `python3 suite.py <model>` |
| `hard.py` | codeC semver range（20 筆測資）、codeD 除錯加不可變性、三步 tool 鏈 | `python3 hard.py <model>` |
| `multirun.py` | 把三步 tool 鏈重複 n 次做穩定度統計 | `python3 multirun.py <model> 5` |
| `argdump.py` | 參數保真度：模型轉手檔案內容時有沒有改動空白與換行 | `python3 argdump.py <model> 5` |
| `descfix.py` | A/B：工具描述寫明「原樣傳遞」能不能提升保真度 | `python3 descfix.py <model>` |
| `edittest.py` | agentic edit 的 old_string 精確匹配，fixture 埋了行尾空白 | `python3 edittest.py <model> 5` |

## 判分都是機械的

code 題是 hidden test 實跑後比對常數，tool 題是 ground truth 數字比對，保真度是與原文做 byte 級 `==`。沒有人工評分也沒有 LLM 判官，所以同一顆模型重跑結果可比。

## 這組題的重點在哪

`argdump` / `descfix` / `edittest` 三支是獨到價值所在：它們測「模型當 coding agent 時會不會把檔案內容偷偷改形狀」。一般 benchmark 不測這個軸，但它直接決定模型能不能託付會改檔的工作。

2026-09-15 的實測結論：muse 16/16 原樣傳遞、V4.1 與 GLM 各 3/8 會掉尾端換行。但同日另一輪也發現，**觸發條件很窄**——只有「工具描述沒明示精確性」加上「要求把整份內容複述成參數」兩條件同時成立才顯現；真實 CC 的 Edit 那種「選取片段加描述明寫 byte-for-byte」完全不受影響（三個模型 15/15 全中）。引用這個軸時要連同這個邊界一起講。

## 沒涵蓋的軸

長 context、平行 tool call、錯誤恢復成功率、JSON mode、拒答與安全、成本換算。要這些就得另外設計，不要假裝這組題測過了。

繁體中文與 system prompt 遵從不在這組題裡，它們在 `smoke.py`（原版題目全是英文，且從不送 system message）。

## 安全注意

`suite.py` 與 `hard.py` 會用 `subprocess` 直接執行模型產出的程式碼，沒有沙箱。跑的是自己接入的模型時風險可控，但別拿它去測不信任的來源。
