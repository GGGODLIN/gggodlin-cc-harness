---
name: model-onboard
description: 把新的第三方模型接進本機模型池，並判定它值不值得用。觸發語包括「我串了一個 X」「接入 X」「幫我確認一下這個模型」「這顆模型行不行」「簡單驗一下」「要不要排進 free chain」「新加了一個 provider」，以及接入後想比較兩顆模型優劣的場合。涵蓋 adapter、litellm gateway 與 CLIProxyAPI relay 三層接線、能力探針、CC session 內的整合驗證、裁決與登記。不要用在：模型定價或規格的純事實查詢（走 research-before-answer）、已接入模型的行為除錯（走 debugging）、harbor testbench 的實驗設計與判讀（那是使用者自己拍板的重型實驗，本 skill 只負責提名候選）。
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# 接入並評估一顆第三方模型

一次接入分五階段：**WIRE → SMOKE → BENCH → LIVE → VERDICT**。WIRE 與 SMOKE 預設一定跑，BENCH 與 LIVE 看這顆模型的用途，VERDICT 永遠要做。要排進 `free`／`free-smart` chain 的腿，LIVE 之後、VERDICT 之前多一道「入鏈關卡」。

五階段之所以要拆開，是因為它們的失敗長得不一樣：接線失敗會沉默（某一層沒登記，但別層測起來都正常）、能力不足會被限流偽裝成失敗、CC 整合層的問題在 API 面完全看不出來、而「這顆該放哪」是價值判斷不是測量結果。混在一起做，最常見的後果是把上游故障寫成「這個模型不行」。

## 階段一：WIRE — 三層都要登記

本機模型池是三層串接，任何一層漏登記，別層都測得出綠燈，於是漏層不會被發現。層次地圖、各層設定檔位置與 probe 指令見 [references/wiring-layers.md](references/wiring-layers.md)，接入新模型時先讀它再動手。

同時問清楚**額度來源與共用對象**：這顆的額度是訂閱、PAYG、免費層還是本機 engine？跟既有哪幾顆共用？共用額度的新模型不增加容量，能力再好也沒有存在意義——這件事在 WIRE 就要問，不要等能力都測完才發現。

完成條件：**三層的 `/v1/models` 都列得出這個 model id**，而且是逐層實際 curl 過的輸出，不是「我改了設定檔所以應該有」；**額度來源與共用對象已寫下來**。

登記完把改動 commit（個人 repo 照自動 commit 慣例），設定檔若不在版控則先備份再改。接著完成下方「輸出預算」，才進 SMOKE。

### 輸出預算

1. 如果引入免費模型，就先用當前 provider 的模型目錄、官方契約或端點驗證核實最大輸出量，並查 adapter／gateway／relay 有沒有降低或覆寫它。記錄 model、來源、支援上限及實際請求參數；查不到就標未驗證，不猜 2048／4096／8000。
2. 將能力測試與正式消費端的輸出預算設為這條來源已核實的可用上限，送出後對回 request、finish_reason、usage 與正式答案。若契約要求輸入加輸出共用 context，按該契約核算可用上限；不要拿 context window 當最大輸出量。上限不要求模型寫滿，短答案要求也不能代替推理加正文所需的預算。
3. 只有刻意測小預算相容性的探針可保留低值，結果與能力測試分開。遇到 length／MAX_TOKENS 或空正文而仍有 reasoning，先核輸出預算和轉送路徑，再判模型能力；不靠逐次小幅加量、縮短來源或改答案抽取掩蓋截斷。

完成條件：每個新免費模型都有上限來源、測試與消費端實際預算、轉送核對及足額回件，或逐項標明未驗證／阻塞。完成後接 SMOKE；如果現有腳本仍硬編小值，就先修能力探針的接線，保留刻意小預算診斷。

## 階段二：SMOKE — 接線驗證，預設一定跑

跑 `bench/smoke.py`，它把過去踩過的坑做成自動探針：

```bash
cd ~/Desktop/projects/local-llm-gateway/bench
BENCH_BASE_URL=http://127.0.0.1:8000/v1 BENCH_API_KEY=sk-1234 python3 smoke.py <model-id> 3
```

十二道探針涵蓋可達性、content 通道、小 max_tokens、streaming、tool_call 格式、tool loop 收尾、system prompt 遵從、繁中單輪、參數相容性、繁中×tool 情境、證據忠實度、該不該呼叫工具。每道預設跑 3 次，因為單次樣本分不出「這顆不會」和「這次剛好沒中」。

最後三道是 2026-09-17 從 `nvidia-build-bench` 的實測觀察補進來的，補的是**有鑑別力**的軸：繁中要在 tool 情境下才測得出退化（有模型單輪乾淨、進 tool context 掉簡體）；證據忠實度測模型肯不肯採信與訓練記憶衝突的 tool 回傳（有模型會幻覺「現在是 2023」並罵證據虛構）；該不該呼叫工具測的是給了工具卻憑記憶硬答。

輸出有三態：`PASS` / `FAIL` / `N/A`。**`N/A` 表示請求層失敗，能力無從判定**——這個區分是整支腳本最重要的部分，沒有它就會把 429、502、503 寫成模型能力差。哪些狀態碼該歸到哪一層、以及各種已知陷阱，見 [references/traps.md](references/traps.md)。

完成條件：**每道探針都有 PASS / FAIL / N/A 三者之一的明確落點**，而且所有 `N/A` 都追出了成因（限流？上游沒開？adapter 沒起？），不是留著不管。

`N/A` 佔多數時不要往下走，先解決請求層問題再重跑——帶著一半 `N/A` 去做裁決，等於拿不存在的證據下結論。

`PASS` 也要看有效樣本數。腳本每道探針都印 `有效 v/n`，並列出丟掉幾發與狀態碼；有效不到半數時直接判 `N/A`。有效 2/3 的 `PASS` 只證明那 2 發，裁決表照實寫 `有效 2/3；丟 1 發（429）`，定位也不能把它寫成「穩定可用」。

## 階段三：BENCH — 能力評估，看情況跑

SMOKE 全綠之後才有意義。跑 `bench/` 底下移植自 cline 系的題組，測程式正確性、多步 tool 鏈、工具結果忠實度、參數保真度、agentic edit。題目與判分方式見 [references/bench-suite.md](references/bench-suite.md)。

這組題的獨到價值在 `argdump` / `descfix` / `edittest` 三支——它們測「模型轉手檔案內容時會不會偷偷改動空白與換行」，一般 benchmark 不測這個軸，而它直接決定模型能不能當 coding agent 用。

完成條件：**每一題都有 n 次的 tally（不是單發），且分數與延遲、token 一起記錄**。

跳過這階段是合理的——例如這顆模型只打算當單次來回用（翻譯、摘要、判官），不進 agentic 派工。跳過時在裁決裡寫明「未測能力，定位僅限單次來回」，不要讓 SMOKE 的綠燈被讀成能力背書。

## 階段四：LIVE — 在真的 CC session 裡跑

**接進來多半是要給 CC 用的，而前三階段全部是用 curl 或 python 直接打端點，測不到 CC 整合層。** 有一整類問題只有真的開一個 session 才看得見：context window 被退回 200K 假設、ToolSearch 的延遲載入對非 Anthropic 端點預設停用、stop hook 對 vendor session 發出不適用的提示、subagent 實際派到哪顆模型、CLAUDE.md 的風格規則有沒有被遵守。這些在 API 面全是綠燈。

做法、環境變數、複合測試 prompt 與 jsonl 分析指令見 [references/live-session.md](references/live-session.md)。

這階段用 `claude -p` headless 自己跑，不必交給使用者——headless 會起完整 session 並留下 jsonl，hook、MCP、subagent、CLAUDE.md 都照常生效。只有「模型會不會問問題後等待」這類互動行為需要人親自跑。

順帶測 context 上限：直接對端點送遞增長度的 prompt，看回報的 `prompt_tokens` 與何時失敗。第三方端點的實際上限常與宣稱不符，而這個數字決定 `CLAUDE_CODE_MAX_CONTEXT_TOKENS` 該釘多少——沒實測就別亂釘，亂設比不設更危險。

完成條件：**拿到該 session 的 jsonl，四條分析指令都跑過，五條通過條件逐條有結論；context 上限有實測數字**。

這顆模型若不打算給 CC 或其他 agent harness 用（例如只給腳本做單次翻譯），這階段可以跳過，但要在裁決裡寫明「未在 CC 內驗證」。

完成後：要進 `free`／`free-smart` chain 的腿接下方「入鏈關卡」；不進 chain 的直接接階段五。

## 入鏈關卡：free 池回歸題組

chain 的主要消費者是 CC 主 session 底下的子 agent，做的是規則稽核、小段 review、分類這類日常短任務。前面幾階段都沒有「跟現役腿比」的對照組，所以 SMOKE、BENCH 全綠也看不出這顆會不會把現役腿做得到的事做壞。這道關卡用同期交錯跑的對照組補這一塊（使用者 2026-09-25 定 v1；2026-10-03 改用分析類 v3 取代原本的 D3/D4）。

做法、指令與判讀見 [references/regress-gate.md](references/regress-gate.md)。兩部分都要跑：

1. v1（`regress.run`，對照 mimo26）；報告有退步候選就跑 `--attempts 3,4` 追加確認
2. 分析類 v3（`regress.v3_run formal`，只跑這條腿 4 場，再用 `regress.v3_run report` 產報告）

完成條件：**v1 報告結論與 v3 報告摘要列都有；每個退步候選都跑過追加確認**。v1 不是「未發現明確退步」，或 v3 不是「有效評分 4/4、按時完整交件 4/4、捏造 0、越界 0」，就預設不進 chain；v3 內容分數只記錄、不當門檻。仍想進是使用者的決定，帶著報告問，不要自己放行。

完成後接階段五；chain priority 停點在這裡才問，不是 WIRE 之後。

## 階段五：VERDICT — 裁決與登記

三件事，缺一不可：

1. **填裁決表**，格式見 [references/verdict-template.md](references/verdict-template.md)
2. **給出定位**：主用 / 備援 / 僅單次來回 / 不適合 agentic / 淘汰。定位要對得上實際測到的證據，測不到的軸就寫「未驗證」
3. **寫一條 memory 條目**，標明日期、實測數字、以及翻案條件

裁決表寫完後接下方「自我檢查」，通過才進回報。

## 自我檢查

裁決表是本 skill 的主要產出，而它最容易出的錯是「證據比宣稱窄」——測不到的軸被寫成結論、上游故障被寫成模型缺陷。派一個 subagent 對表：

- `subagent_type`: `skill-verify-auditor`
- description 固定含 marker 字串 `skill-verify:model-onboard`（採用率統計 grep 用，不要改字）。marker 放 description、不是只放 prompt——額度 gate 從 description 取 skill 名，prompt-only 是舊寫法，不再是正式接線
- prompt 把**裁決表全文**與下列 rubric 逐字嵌入
- 指示它偏置找違規，無法確認就判 FAIL，最後輸出固定的 `VERDICT:` 行

rubric：

1. WIRE 表的每一層都對應一次實際 probe 輸出，而不是「已修改設定檔」這類推論
2. SMOKE 表裡每個 `N/A` 都寫出了成因（限流／上游故障／服務沒起），沒有留白
3. 「未驗證」段非空，且跳過 BENCH 時明確涵蓋 agentic 能力
4. 定位（主用／備援／僅單次來回／不適合 agentic／淘汰）指得到表中具體哪一列證據
5. 請求層失敗沒有被寫成模型能力結論
6. SMOKE 表中跑 n 次的探針（參數相容性是每個參數各打一發，不在此列），數字都寫成 `有效 v/n`，n 等於表頭的 n；有丟樣本的列寫出丟了幾發與狀態碼或成因；有效不到半數的列不是 `PASS`

**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。裁決表末尾固定一行，狀態只能是下列四個之一：

- 全 PASS → 「🔎 self-verify: COMPLIANT」
- 任一 FAIL 且已修正 → 先修再交，標「🔎 self-verify: FIXED_AFTER_AUDIT — R#（抓到什麼、怎麼修的）」，同句明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 標「🔎 self-verify: FAILED — R#（缺口）」，並把證據撐不住的那一列裁決改回「未驗證」或整列刪除，不得保留原定位
- subagent 出錯 / timeout / 空輸出 / 格式錯誤 → 標「🔎 self-verify: SKIPPED (agent error)」，不要靜默略過

## 三個要使用者拍板的停點

這三處不要自己決定——它們改變的是對外行為或資源分配，不是內部實作細節：

| 停點 | 什麼時候出現 | 要問什麼 |
|---|---|---|
| **chain priority** | 入鏈關卡跑完後 | 這顆要不要排進 `free` chain？排第幾腿？附回歸題組兩份結論（新模型預設不進 chain，只給獨立 alias；關卡沒過時明講退步清單） |
| **BENCH 要不要跑** | SMOKE 全綠後 | 這顆的定位需不需要 agentic 能力證據？不需要就跳過 |
| **送不送 harbor** | BENCH 出結果後 | harbor testbench 成本高（一輪百餘 trial 加 LLM 判官審軌跡），題庫子集、臂數、attempts 全由使用者選。本 skill 只負責提名候選並說明理由，不代為設計實驗 |

## 回報格式

給使用者的回報分兩段，不要混在一起：

- **第一段**：這顆模型的能力與定位（BENCH 與 SMOKE 的結果）
- **第二段**：接線過程本身撞到的問題（漏層、限流、上游故障、設定沒生效）

混在一起寫，讀的人會把上游故障當成模型缺陷。今天的 MiMo flash 就是這樣——502 是小米桌面 app 的 engine 回的，跟模型聰不聰明無關。
