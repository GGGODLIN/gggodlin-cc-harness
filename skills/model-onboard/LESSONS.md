# 踩過的坑

## 2026-09-17 建立本 skill 當天

**探針把自己限流，然後誤判成模型壞掉**。第一版 `smoke.py` 沒有節流，對 MiMo flash 連打十幾發後全變 429／502。當時的輸出把它們記成 `FAIL`，讀起來完全像「這顆模型不行」——但停 30 秒後單發一次就回 200。

由此改出兩件事：`client.py` 加 `BENCH_DELAY` 節流（預設 1.5 秒，MiMo 這種本機 engine 還要更大），以及 `smoke.py` 的三態設計——請求層失敗記 `N/A` 而不是 `FAIL`。這是整支腳本最重要的一行區分。

**參數相容性探針把 429 讀成「不支援這個參數」**。原本只判 `ok` 與否，429 就寫成 `rejected`。改成只有 400／422 才算 rejected，429 與 5xx 標 `unknown` 並整項降為 `N/A`。

**接線漏了一層而沒發現**。當天接 MiMo 時，`mimo-x-flash` 進了 adapter 與 litellm 卻沒進 relay，而 litellm 那層測起來全綠。漏層不會報錯，只會讓某個消費端看不到模型——所以 WIRE 的完成條件寫成「三層各自 curl 過」，不是「改完設定檔」。

**移植來的判定太寬鬆**。cline 版 `hard.py` 用 `"6" in content` 判多步 tool 鏈，回覆裡任何位置出現字元 6 都算過。改用同套件 `multirun.py` 的 `\b\d+\b` 抽數字後再比對。

## 建立當天的 RED / GREEN 行為驗證

同一場景（「剛把 mimo-x-flash 串進 litellm，確認能不能用」）給兩個 fresh agent，一個禁止使用本 skill、一個照本 skill 做。

RED（不用 skill）漏掉的：只驗了 litellm 一層就寫「gateway 登記通過」，**完全沒查 relay**；測到 18.8／16.1／18.6 秒的延遲後判定「穩定重現、不是抖動」，據此建議「改掉 `-flash` 後綴」——但 GREEN 同一顆模型測到 0.86–7.94 秒、TTFT 2.04–3.9 秒。RED 把環境造成的延遲當成模型特性，還據此提了改名建議。

GREEN（用 skill）做到的：三層都 probe 並抓出 relay 未登記；T0.3 判 FAIL 後另做一次排除 probe，確認是 `finish_reason: length` 加預算用滿，歸因為「推理佔用預算」而非請求層失敗，並寫明「不是對模型能力的評價」；定位寫成「僅單次來回」並註明 SMOKE 全綠不得讀成能力背書；relay 與 chain 留給使用者拍板沒有代決。

這組對照證實三層檢查與三態歸因是本 skill 的有效成分。

## 裁決表原本缺一欄：額度來源

首次試跑（MiMo pro／flash）時，使用者的否決理由是「flash 跟 pro 吃同一個額度」——而裁決表裡沒有任何一欄放得下這句話。表上有定位、有證據、有未驗證段，全都繞著能力轉，但共用額度的模型**能力再好也不增加容量**。

已補進 `verdict-template.md` 與 SKILL.md 階段一（在 WIRE 就問，不是等測完才問）。

## 第一版整個漏掉 CC 整合層（使用者當天指出）

第一版四階段全部是用 curl 或 python 直接打端點——**而接模型進來多半就是要給 CC 用的**。CC 整合層的問題在 API 面完全是綠燈：context window 被退回 200K 假設、ToolSearch 延遲載入對非 Anthropic 端點停用、stop hook 對 vendor session 發不適用的提示、subagent 派到哪顆模型、CLAUDE.md 風格有沒有被遵守。

更該檢討的是，這一關在 `cc-vendor-bridge/docs/stage-2-playbook.md` 的 Phase 2 與 Phase 3 早就寫好了，連複合測試 prompt、四條 jq 分析指令、五條通過條件都有。盤點時我讀到了那份文件，卻把它整份歸類成「Path 0 專用、與 litellm gateway 路徑不同」就跳過。

**誤判在哪**：Phase 1 的 curl 測試確實綁 Path 0，但 Phase 2／3 測的是 CC 整合層，不分接入路徑——只要最終是給 CC 用就會遇到。而那三個 caveat（context fallback、ToolSearch、stop hook）原文明確標「affects all third-party」。

修法是加階段四 LIVE，見 `references/live-session.md`。

## 待修

**三態不夠用，缺第四格**。T0.3（小 max_tokens 導致 content 空）既不是請求層失敗（HTTP 200、`finish_reason: length`、預算用滿），也不是能力缺陷——但三態只有 `PASS`／`FAIL`／`N/A`，而 `N/A` 的定義綁死在請求層失敗上，於是它沒有合法的格子可放。

後果不只是標籤不準：GREEN runner 的自我檢查**連三輪 FAIL**，兩種修法都過不了，最後依「修正額度用盡就換路」停手。rubric 第 5 條要求「請求層失敗不得寫成能力結論」，auditor 看到 FAIL 就判違規，但 skill 又不准標 `N/A`——是我自己寫的兩處互相打架，不是 agent 做錯。它沒有竄改腳本原判來硬過，這個處理是對的。

修法是加一格「組態相關」給這類情況。**尚未修**，因為要連 rubric 與 Self-Verify 一起重驗。

## 尚未解決

MiMo flash 對「要求輸出含大括號的 JSON」穩定回 502，追到上游是小米桌面 app 的 engine 自己回的，不是 adapter 也不是 litellm。觸發條件還沒完全縮小。

2026-09-24 trial review 稽核六次接入後留下三項，當輪使用者拍板不修：
- **BENCH 停點被跳過 2/6**：24f2a26c 引用 assistant 自提、未核准的「池 bar」直接跑 BENCH；c7f4e002 寫「SMOKE 如果乾淨就直接跑 BENCH，你不用回覆」。harbor 也有一次先跑後問（e8c655af）。
- **報告難讀 4/6**：使用者在 4 個 session 說「看不懂」或要求白話，集中在 harbor／BENCH 階段分不清、結論不在開頭。
- **裁決 memory 缺寫**：dbda4fdf 使用者說結案後 assistant 明說「這次不另存 memory」；cb993ca7 只用 python 附記 project 檔，沒有 reference 條目。

## 2026-09-24 trial review（六次接入稽核）

**單樣本丟失被讀成 PASS**。舊版 `smoke.py` 的判定只看剩下的樣本，丟掉的請求層失敗不報數，3 發丟 1–2 發後剩 1/1、2/2 仍印 `PASS`。09-17～09-24 六次接入有四次踩到（e8c655af T0.12、24f2a26c T0.6、50646353 T0.12、cb993ca7 四道工具探針），其中兩次 auditor 仍判合規，cb993ca7 據此寫出「工具相關的探針都有過」。

由此改出：`smoke.py` 的 `sample_verdict` 每道都印 `有效 v/n` 與丟失狀態碼、有效不到半數判 `N/A`（local-llm-gateway `tests/test_smoke_sampling.py`）；SKILL.md 三態段補「PASS 也要看有效樣本數」、rubric 補第 6 條、verdict-template SMOKE 表數字欄改名。rubric 第 6 條第一版把「參數相容性」也要求成 `有效 v/n`，回歸情境誤判，改成排除這道逐參數單發的探針。

## 2026-09-29 Antseed 接入

**入鏈關卡只在 memory、skill 沒寫**。使用者 09-25 定「新腿引入要跑回歸題組 v1」，但只寫進 memory；Antseed 接入時是翻 memory 才接上，RED runner 照舊版 skill 讀成「WIRE 之後就能入鏈」（SKILL.md 舊版 chain priority 停點寫「WIRE 完成後」）。

由此改出：SKILL.md 加「入鏈關卡」段與 `references/regress-gate.md`，chain priority 停點改到關卡之後，verdict-template 加關卡表。

## 2026-10-16 接 Gemini 4 Argon

**照過時的接線圖改了已停用的 CPA**。10-15 遷到 Magpie 後 wiring-layers.md 沒更新，我先往 `~/.cli-proxy-api/config.yaml` 加 provider，才發現 8317 已轉給 Magpie、CPA 與一般 LiteLLM 都沒在跑。改成 Magpie CLI `provider add` 後當下生效，不用重啟。

**Gemini 經 litellm 進 CC 會壞在第二輪**。litellm 1.89.3 的 `/v1/messages` 轉換丟掉 Gemini 的 thought_signature，CC 第二輪帶 tool 結果時 Google 回 400「Function call is missing a thought_signature」；`openai/` provider 還會把 `/v1/messages` 轉去打不存在的 `/responses`。原生 `gemini/` provider 一樣丟簽章，且把 `reasoning_effort: high` 換成 `thinkingBudget: 4096`。Magpie 的 google preset 把簽章編進 tool_use id 帶回去，usage.jsonl 記 `effort: high`。RED 沒能重現這條（當時 litellm 沒在跑，runner 直接選 Magpie），所以只記在這裡、沒寫成 traps 規則。

**入鏈關卡把 mimo26 現場重跑當成必要步驟**。現場對照的規則出處是外部審查建議，不是原需求；原需求一直是「跟 mimo26 的凍結基準比」。改成 v1 只跑受測腿、對凍結基準比，比較器的追加確認也改成只看受測腿（local-llm-gateway ce8a0d5）。
