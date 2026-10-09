# 已知陷阱

每條都來自實際踩過的接入。共通形狀是：**某個非能力因素長得像能力問題**。

## 歸因：狀態碼屬於哪一層

判定「這是模型不行」之前，先把狀態碼歸層：

| 狀態 | 多半的成因 | 不該推論成 |
|---|---|---|
| 401 | 沒帶 key 或 key 錯 | 任何能力結論 |
| 400 / 422 | 參數不被接受（`reasoning_effort`、超出 output 上限） | 模型不支援該功能——可能只是這層 proxy 擋掉 |
| 402 | 帳號額度用盡 | 模型弱 |
| 403 | entitlement 不足（沒訂閱、沒權限） | 模型弱 |
| 413 | 單發請求超過 TPM 上限，**不排隊、重試無用** | 一般限流 |
| 429 | 限流。可能是上游配額，也可能是**探針自己打太快** | 模型弱、參數不支援 |
| 5xx | 上游故障 | 模型弱 |

`smoke.py` 的三態設計就是為了這件事：請求層失敗一律記 `N/A`，不記 `FAIL`。

判 429 來源的方法：停 30 秒後單發一次。回 200 就是自己打太快，調大 `BENCH_DELAY`；仍 429 才是上游配額。

relay 層另有一個坑：它的本地冷卻會在 selector 層短路，毫秒級回 `All credentials ... are cooling down`，請求根本沒出這台機器。**網頁端手動重置額度不會解除它**，要 `launchctl kickstart` 重啟（冷卻預設只存記憶體）。看最新 `logs/error-*.log` 尾巴是本地字串還是上游原生格式，一行分辨。

## 探針自傷

連續打探針很容易把自己限流，然後整批結果變成 `N/A`，看起來像模型掛了。`client.py` 預設 `BENCH_DELAY=1.5` 秒，MiMo Desktop 這種本機 engine 需要更大（實測 1.5 秒仍會 429）。

症狀：前幾道 PASS、後面全 `N/A`。

## content 欄可能是空的

有些模型的答案只在 `reasoning_content`，`content` 恆空（NVIDIA 的 `qwen3.5-122b` 實例）。標準 SDK 直接讀 `content` 會拿到空字串，看起來像模型不回話。

`client.py` 的回傳同時取 `content` 與 `reasoning`，`smoke.py` 的 T0.2 專門驗這件事。

## reasoning 模型需要大 max_tokens

推理型模型把 token 燒在思考上，`max_tokens` 給小了正文會是空的。給 ≥8000 才公平。T0.3 用 64 故意觸發這個現象，好知道這顆是不是推理型。

## 會 tool call ≠ 能收掉 loop

`gpt-oss-120b` 發得出合法 `tool_calls`，但拿到 tool result 之後不綜合，反而想再呼叫工具卡死。**只測「有沒有發出 tool_call」會高估 agentic 能力**，要測完整一輪：發 call → 餵回結果 → 看最終回覆有沒有採用那個結果（T0.5 與 T0.6 的分工就是這個）。

## 單次樣本不可當基準

2026-09-15 曾用單次樣本得出「GLM 最快最省」，隔幾天同題重測整個反過來。延遲與 token 受池負載影響大，n=1 的數字不能寫進裁決當比較依據。

所有探針預設 n≥3；要拿數字比較兩顆模型，n 還要更大。

## harness 底價 vs context 上限

免費層常見的死法不是能力不足，是 **harness 的裸底價就超過上限**。Groq free tier 8K TPM，而 CC headless 一個 turn 光 system prompt 加工具定義就 79,836 tokens，pi 這種精簡 harness 也要 29,018——繞完所有參數問題仍然死在 413。

要判「這顆能不能跑 agent」，先算 harness 底價，不是先測模型聰不聰明。

## model id 含斜線

`provider/model` 形式的 ref 用 `/` 切，model id 本身含斜線（`xiaomi/mimo-x-pro-preview`、`deepseek-ai/deepseek-v4-flash`）就會切錯。litellm 寫成 `openai/xiaomi/mimo-x-pro-preview` 這種雙 prefix 是可行的，但別的消費端不一定，必要時設無斜線 alias。

## 只測單輪繁中會漏掉退化

有模型單輪生成繁中乾淨，一進 tool／agentic 情境就掉簡體（`minimax-m2.7` 實例）。**軸交叉才抓得到**，所以 T0.8（單輪）與 T0.10（tool 情境）要分開看：兩道都 PASS 才算繁中沒問題，只有 T0.8 PASS 代表還沒測到退化面。

## 模型可能不信自己拿到的證據

餵進 tool result 的事實若與模型訓練記憶衝突，有模型會拒信甚至反過來罵證據虛構——`qwen3-next-80b-a3b-thinking` 實測會幻覺「現在是 2023」、指控證據捏造，整段轉簡體。這類模型在 RAG 與 agentic 用途上不可用，但 code 題可能滿分。

T0.11 用一份含時序更新的證據（先說六個、後更新為七個）測這件事：答 7 表示採信了最新值，答 6 表示取了被更新掉的舊值。

## 給了工具也可能不用

`tool_choice: auto` 下，有模型面對時效性問題會憑訓練記憶硬答，不呼叫工具。這跟「不會發 tool_call」是兩回事——它發得出來，只是判斷失誤。T0.12 專測這個決策。

## 模型自述不可信

問模型自己「你是什麼模型、context 多大、支不支援 X」，答案經常是編的。規格要從 provider 文件或實測來，不從模型口中來。
