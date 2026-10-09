# 入鏈關卡：free 池回歸題組

新腿要排進 `free`／`free-smart` 之前跑。題組在 `~/Desktop/projects/local-llm-gateway/regress/`，兩部分都要跑：v1 考日常短任務有沒有退步，分析類 v3（A1 本機盤點、A2 紀錄稽核）考給起點路徑與分母後逐項查證、引用原文佐證。只跑 v1 抓不到「讀一批紀錄、逐項下結論」這一型；只跑 v3 抓不到日常稽核、review、分類的退步。

v3 在 2026-10-03 取代 D3/D4（使用者判定 D3/D4 太簡單、擋不住任何腿）。D3/D4 的 case 與歷史結果留在 repo，但不再是入鏈條件。

## 前置

1. relay 已有這條腿的專用 alias（WIRE 階段加的，priority 10、disable-cooling，不掛 `free`）
2. 在 `regress/run.py` 的 `LEGS` 登記：`"<腿>": {"alias": "<relay alias>", "expect_model": ("<上游自報的 model 前綴>",)}`。`expect_model` 用 `startswith` 比對，上游自報字串有多種時全列
3. key：`source ~/.cli-proxy-api/keys.env`，用 `REGRESS_API_KEY=$CLIPROXY_KEY_ADMIN`

## v1（T1/T2/T5/T7，每例 2 次）

```bash
cd ~/Desktop/projects/local-llm-gateway
REGRESS_API_KEY=$CLIPROXY_KEY_ADMIN python3 -m regress.run --legs mimo26,<腿> \
  --out .scratch/free-pool-regress/runs/<腿>-<YYYYMMDD>.jsonl
python3 -m regress.report .scratch/free-pool-regress/runs/<腿>-<YYYYMMDD>.jsonl \
  --candidate <腿> --short-only-note --frozen regress/baselines/mimo26-20260925.jsonl \
  > .scratch/free-pool-regress/reports/<腿>-vs-mimo26-<YYYYMMDD>.md
```

- mimo26 同期交錯跑當對照；報告第一段「基準漂移」判「未發現」才代表對照可信
- 報告列出「退步候選（待追加確認）」時，對那幾題跑追加一對：`--cases <id,...> --attempts 3,4`，mimo26 一起跑；`regress.report` 接受多個 jsonl，把原檔與追加檔一起傳進去重產報告
- 一輪 150 題約 70 分鐘（2026-09-29 實測），用背景執行

## 分析類 v3（每條腿 4 場）

```bash
REGRESS_API_KEY=$CLIPROXY_KEY_ADMIN python3 -m regress.v3_run formal --legs <腿> \
  --out .scratch/free-pool-analysis-regress-v3/onboard/<腿>-<YYYYMMDD>.jsonl
python3 -m regress.v3_run report --rows .scratch/free-pool-analysis-regress-v3/onboard/<腿>-<YYYYMMDD>.jsonl \
  > .scratch/free-pool-analysis-regress-v3/onboard/<腿>-<YYYYMMDD>-report.md
```

- 新腿只跑 `formal`（A1、A2 各兩情境，每題 1 次）。`pilot` 是改過題目或判分器後驗題目本身用的，題目已在 2026-10-03 用 V4.1 驗過，新腿不必再跑
- `--out` 每次用新路徑：檔案已存在時會接在後面寫，混進舊列
- 每場上限 20 分鐘，同題型串行、A1 與 A2 並行；實測每場 49 秒～9 分鐘，用背景執行
- 請求層 N/A 會自動補跑一次；同一格不要手動重考
- 對照用 2026-10-03 正式考試（`.scratch/free-pool-analysis-regress-v3/formal/formal-20261003-report.md`）：7 條現役腿內容分數 89.9%～100%，全部有效 4/4、按時 4/4、捏造 0、越界 0

## 怎麼判

v3 只看報告摘要表的交件與紅旗欄，內容分數記進裁決表、不設門檻：題目鑑別度低（現役腿 89.9%～100%），而且分數高低本來就不是 v3 的放行條件。

| 結果 | 意思 |
|---|---|
| v1「未發現明確退步」，且 v3 有效評分 4/4、按時完整交件 4/4、捏造 0、越界 0 | 過關，可以問使用者 chain priority |
| v1「暫緩」「資料不足」，或 v3 有捏造、有越界、有未按時交件 | 預設不進 chain；接線保留供重測 |
| v3 有效評分不到 4/4（補跑後仍 N/A，或有 invalid 列） | 資料不足，不是能力結論。invalid 代表上游模型對不上 `expect_model`，先修接線；N/A 先追請求層成因。修好後用新 `--out` 整份重跑 formal，因為上一輪被請求層作廢，所以不算重考 |

「暫緩」裡要分清是模型行為（捏造、越界、答錯）還是請求層（逾時、429、上游故障）。逾時歸因不清時不要寫成能力結論。

未過關仍想進 chain 是使用者的決定（前例：bunny 在回歸題組建立前入鏈）。帶著報告的退步清單問，不要自己放行。

## 收尾

- 兩份結果（v1 的 jsonl 與報告、v3 的 jsonl 與報告）照 repo 慣例 commit 進 local-llm-gateway
- T7 過去曾把檔案寫到工作目錄外；跑前 `ls -A ~ > before.txt`、跑後比對，有多出的檔案就清掉並寫進裁決表
