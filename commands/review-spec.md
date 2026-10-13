---
description: 對 spec / plan / design doc 做分層 adversarial review（T1 唱反調自審 → T2 單一 Opus architecture-critic → T3 多 lens Opus＋Fable 雙跑 → T4 外部跨模型暗門）。補需求探索階段的自審只掃衛生、抓不到「想得對不對」的洞。另有獨立 yagni 軸審「值不值得」（來源追溯／分母／簡單版舉證），`/review-spec yagni <spec>` 單獨跑、不與 T1–T4 疊加——spec 由模型代寫、範圍源頭是一句模糊憂慮時最該跑。依當下複雜度選 Tier，手動 invoke。
argument-hint: "[tier 1-4 | yagni] [spec 路徑，省略則取最新 local spec]"
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/review-spec-execution-contract.test.sh -->

# /review-spec

對一份 spec / plan / design doc 做**分層對抗式審查**。需求探索階段的自審只抓「寫得乾不乾淨」（placeholder / 矛盾 / scope / 歧義），抓不到「想得對不對」（意圖偏離 / 架構爛 / 假設錯）。這個 command 補後者。

## 解析輸入

`$ARGUMENTS`：

- 第一個 token 是 `1`–`4` → 當 Tier；其餘 token（若有）當 spec 路徑
- 第一個 token 是 `yagni` → 走下方「YAGNI 軸」段；其餘 token 當 spec 路徑
- 第一個 token 不是數字 → 整串當 spec 路徑
- 都沒給 → 目標 spec = cwd 下**最新**的 OpenSpec `openspec/changes/*/design.md`、`openspec/changes/*/proposal.md` 或 local scratch `.scratch/*/spec.md`（依 mtime 取最新；無輸出就問使用者要審哪份）
- 沒給 Tier → 印「Tier 選單」+ 複雜度提示，等使用者選；**不要自己預設高 Tier**。若使用者選 Tier 3，回傳可直接貼上的 `/review-spec 3 <spec 絕對路徑>` 並停止本輪；特權雙跑只接受原 command 同時明列 Tier 3 與 spec 路徑，不把後續裸 `3` 當授權。

command **路徑無關**：任何 spec / plan / PRD 都能審，不綁定特定 workflow。預設 local artifacts 使用 OpenSpec 的 `openspec/changes/<change>/design.md` 或 `openspec/changes/<change>/proposal.md`、無 OpenSpec 時的 `.scratch/<feature>/spec.md`；若目標是 plan / tasks，只接受 OpenSpec 的 `openspec/changes/<change>/design.md` 或 `openspec/changes/<change>/tasks.md`。Tier 1／2／4 先 `Read` 目標 spec 全文再動作；Tier 3 先完成下方可信 permit preflight，才讀取 spec。

## Tier 選單（沒給 Tier 時印這段給使用者選）

| Tier | 機制                                          | 什麼時候選                                    |
| ---- | --------------------------------------------- | --------------------------------------------- |
| 1    | 唱反調自審（in-context，不派 subagent）       | 改 < 2 檔 / 已經很懂這塊                      |
| 2    | 單一 architecture-critic（fresh-context）     | 跨 3+ 檔 / 新模組 / 架構沒把握                |
| 3    | 多 lens Opus／Fable role 雙跑 + synthesize（原生或 distinct vendor mapping） | 動核心架構 / 碰生產資料 / 跨既有 domain model |
| 4    | 外部跨模型暗門（codex-rescue）                | 賭很大的關鍵決策才手動升                      |
| yagni | 需求定價軸（獨立跑，不與 T1–T4 疊加）        | spec 是模型代寫、要審「值不值得」而非「對不對」 |

預設別逼高 Tier — 重 gate 跑久了使用者會懶得等、退回橡皮圖章，gate 本身被蓋章。

## 貫穿守則（標準 Tier 1–4 全部適用；YAGNI 僅沿用守則 0 與 4）

0. **派 critic 只給 artifact + 需求約束，不給自己的結論**（CLAIM 隔離）：dispatch prompt 裡附上 main 自己的評估 / 傾向 /「我認為這段沒問題」會 bias critic 傾向同意——fresh-context 的價值就在它沒被作者結論污染。傳 spec 全文 + 使用者需求約束即可，main 的判斷留在收 findings 之後對照用。
1. **意圖留 in-context、架構/repo 才外派**：「這份 spec 有沒有偏離使用者真正要的」這種**意圖對齊**判斷依賴整段對話脈絡，fresh-context subagent 看不到。意圖對齊留給 main 在 in-context 做，或先蒸餾一份「使用者真正要什麼」brief 餵給 subagent。純架構批判 / 既有 repo 一致性才適合 fresh-context 外派。
2. **Findings 要 sanity-check 使用者 mental model**：subagent 的 finding 是基於「餵給它的 spec」生成的；若 spec 沒反映使用者真正的 mental model，整批 finding 可能自然失效。使用者揭露「這假設不對、實際是 X」時 → reframe 重評、**不要強推原 finding 的解法**。標「dismissed by mental model correction」是 valid outcome，不是 ignore。
3. **每個 Tier 至少一路要交「自洽 + 引證」兩份附錄**（2026-08-01 加，來自 checkout-extension-cart-metafields 實跑）：
   - **自洽表**：把 spec 裡彼此相關的條文兩兩列出，說明它們同時成立。多 lens 平行時各 lens 只讀自己的角度、沒有人拿 A 條去對 B 條——十路 review 漏掉的那條矛盾就是這樣過關的（D2 要求 payload 含寫入時間戳 + D5 要求整包序列化字串當比對基準 + D5 又要求內容沒變不重寫 = 第三條永遠不成立）。
   - **引證表**：spec 裡任何一句「現在的 code / 現在的平台是這樣」，附 `檔案:行號` 或工具查詢結果；附不出來就改寫成「未驗證的假設」。同一輪漏掉的另一條（某 flag 的語義）reviewer 手上有 Read/Grep、翻一下實作就會發現，但沒人翻——critic 預設拿條文對照自己的知識，不會主動去查。

   兩份附錄不另派 agent，寫進既有 lens 的 output schema。Done when：每份 review 產出都帶這兩張表，且引證表裡沒有「聲稱是事實但無出處」的條目。
4. **席位驗收先於 surface 或 mutation**：dispatch 前按 Tier 寫下預期輸出 shape；Tier 2 要有 severity-ranked findings，YAGNI 要完整逐條表與反方下限。回傳不符就帶 mismatch 做 focused retry，最多一次；第二次仍不符就標該席 invalid，不把 raw report 上呈或拿來改檔。routed seat 兩次 60 秒仍無 final 時停止該席，保留其他完成席並把結果明標單席，不讓整輪卡住。security finding 觸發 mutation 前先查 known credential exception；目前 Context7 free key 的 feedback 明訂不觸發跨檔止血。Done when：每席都有 valid／invalid／stalled 狀態，invalid 與 stalled 都沒有被當成 finding source。
5. **驗證設計完整性（條件式）**：spec 把 `eval`、`benchmark`、`A/B test`、`judge`、`scorer`、`holdout`、with-skill／without-skill 對照或多 agent 互驗當成成功證據時，標準 Tier 1–4 額外跑本項；一般 API、schema 或純功能 spec 不跑。逐項對帳：① 記答案代替推理；② 錯誤對照組；③ 同源互相認證；④ 評分規則與答案同構；⑤ 設計者兼裁判；⑥ 訓練與驗證共用來源；⑦ 題目框架洩漏；⑧ 受測者知道想要的結果。隱藏輸出答案仍不夠，資料挑選或收集配方洩漏也算 FAIL。
   - 每類固定記 `PASS／FAIL／N-A + spec 引證`。任何 FAIL 都先把乾淨測試要求寫回 spec：凍結題目與成功門檻、隔離 fresh runs、隱藏 arm 標籤、拆開 designer 與 judge、分離訓練與 holdout 來源；寫回後重跑本表，不把「之後會補測試」當通過。
   - `review-spec` 只修 spec 與 review artifact，不直接建立 ticket；後續 `to-tickets` 依既有規則把驗證項分類成 Gate／Confirmation／Contract，Gate 必須成為獨立阻擋 ticket。
   - Done when：八類都有狀態，所有 FAIL 已轉成可執行的乾淨測試契約並寫回 spec，且沒有 designer、資料、context、rubric 或 arm label 的未揭露共享來源。YAGNI 軸不套本項。

## Tier 3 — 推薦矩陣與可配置席位

這是 `/review-spec` 自己擁有的情境規則，不改 `architecture-critic` 的全域預設：

- Tier 1 不派 critic；Tier 2 維持單一 Opus；Tier 4 維持外部跨模型流程。Tier 3 支援單席與配對，但不預設單席或雙跑。
- 使用者選 Tier 3 後，先把本次適用角度與已有執行路徑完整列成矩陣；模型／執行路徑為直列，角度為橫欄。每格明示 `推薦`、`可選`、`需補材料` 或 `不可用：原因`。推薦只是建議，不是授權，也不限制使用者選擇。

  | 模型／執行路徑 | 簡化軸 | 弱點軸 | repo 軸 | 相容軸 |
  | --- | --- | --- | --- | --- |
  | Opus（`<expected_opus_model>`） | 推薦／可選／條件 | 推薦／可選／條件 | 推薦／可選／條件 | 推薦／可選／條件 |
  | Fable（`<expected_fable_model>`） | 可選／條件 | 可選／條件 | 可選／條件 | 可選／條件 |

  角度欄只放本次適用的 slug，不把其他流程的角度塞進矩陣；模型列沿用當前設定與既有派工路徑，不建立 model registry。main 在詢問使用者前，將推薦席位以同一 session 的 top-level assistant envelope `<review-spec-recommendation:v1 permit_id=<id> seats=<lens:model,...>>` 留在 transcript；使用者可以回「照推薦」、指定換模型、同角度加席、減席、取消角度或逐格選擇；自然語言由 main 轉成明示席位配置，未選定不啟動。`--seats` 只能在同一輪推薦 envelope 與 top-level user selection 都存在後 finalize；「照推薦」必須與 envelope 的席位集合完全相同，明示換選可不同。helper 只核對既有 transcript evidence 與明示配置，不從待派 prompt 推斷授權，也不建立自然語意分類器。
- Tier 3 只接受原始 invocation 形狀 `/review-spec 3 <spec 路徑>`；Tier 與路徑缺一就不發 permit。**先不要 Read spec**。先讀 model binding：`CC_VENDOR` 空值走原生 Claude，最終要求 resolved model 依選定角色分別為 `claude-opus-*`／`claude-fable-*`；`CC_VENDOR` 非空時讀 `ANTHROPIC_DEFAULT_OPUS_MODEL` 與 `ANTHROPIC_DEFAULT_FABLE_MODEL`，移除尾端 effort 標記（例如 `(max)`）後兩者必須非空且不同，permit 會綁定這組 vendor mapping，最終 verifier 以 exact model ID 驗收。mapping 缺失、相同或中途變更都停止，不得拿同一 vendor model 冒充不同角色。
- preflight 通過後，在任何 spec 內容進入 context 前執行：`python3 ~/.claude/hooks/review-spec-dual-permit.py issue --session "$CLAUDE_CODE_SESSION_ID" --spec "<目標 spec 絕對路徑>"`。只接受工具回傳的 `permit_id`、`snapshot_path`、`expires_at`、`vendor`、`expected_opus_model`、`expected_fable_model`；issue 失敗就停止，不得手動補 marker。helper 會 full-match 真實 command envelope、核對 command 自帶路徑，建立 owner-only snapshot，並把當前 model mapping 綁進 session-bound permit；任何後續使用者訊息都會撤銷尚未建立的授權。同一 command UUID 只建立一張 permit，程序中斷後重跑只回傳同一張，不會新增 snapshot。
- permit 建立後只 `Read` 回傳的 `snapshot_path`，不要再讀原始 spec。依 snapshot 完成角度裁剪與矩陣選擇；拍板完成後，將同輪 top-level user selection 與 recommendation event 的 UUID 交給 `python3 ~/.claude/hooks/review-spec-dual-permit.py finalize --session "$CLAUDE_CODE_SESSION_ID" --seats <逗號分隔的 lens:model 配置> --recommendation-event <assistant event UUID>`。使用者回覆「照推薦」時再加 `--follow-recommendation`；helper 會要求席位集合與同輪 envelope 完全相同。`model` 只可填 `opus` 或 `fable`；同一 lens 可選一席或兩席，未選 lens 不列入配置。既有 `--lenses <逗號分隔的 slug>` 保留為明示的雙跑快捷方式，但仍須有同一輪 top-level user 的明示配對選擇，不是預設，也不會暗加任何未列席位；新核可的 legacy shortcut 同樣使用 reference＋完整 Read。finalize 成功後告知實際席位數、每席模型與角度，不把推薦寫成已選。
- 每個實際派出的席位先執行 `python3 ~/.claude/hooks/review-spec-dual-permit.py packet --session "$CLAUDE_CODE_SESSION_ID" --lens <slug> --model <opus|fable> --reference`。helper 會建立 owner-only packet file，stdout 是綁定 packet path／permit／到期時間／lens 的短 reference；把 stdout **逐字放在 prompt 最前面**，緊接一句「第一個動作必須用 Read 完整讀取 `REVIEW_SPEC_PACKET_PATH`，不可指定 offset／limit」，再接該 lens 指示與需求約束。gate 比對 Fable reference 與 packet 檔文字是否相等，final verifier 另驗 reviewer 確實完整 Read 該 owner-only file；不再由 main 手動轉貼大型 snapshot：
  - Opus 席：`subagent_type: architecture-critic`、`model: opus`，使用同一份 packet + lens prompt。
  - Fable 席：`subagent_type: architecture-critic`、`model: fable`，description 使用 `<review-spec-dual:v1 permit_id=<issue 回傳值> lens=<slug>>`，prompt 使用與 Opus 席相同的 packet + lens prompt。
  - slug 固定為 `simplify`／`failure`／`repo`／`compat`，分別對應下方四個 architecture lens。
- **dispatch 前先算 permit 剩餘 TTL**：`REVIEW_SPEC_EXPIRES_AT` 減當下 UTC；剩餘不足 45 分鐘就不派任何選定席位、停止本輪並請使用者重新 invoke `/review-spec 3 <spec>` 取得新 permit。permit 預設 2 小時常被 packet／transport 修繕吃掉，「permit 尚未過期」不等於「夠完成整輪選定席位」。
- 選定多席時逐席確認 Agent 已成功啟動；任一席因容量拒絕而未啟動，就停止尚未派出的席位並請使用者重新 invoke `/review-spec 3 <spec>` 取得新授權；已消耗的席位不得沿用或補派。未選席位不派工。
- gate 會在每支選定 Fable 呼叫時原子消耗對應 lens permit；同一 `lens:fable` 只能用一次，未經 finalize 授權或已被裁剪的席位一律拒絕。固定 marker、錯誤 permit ID、別的 session、重複席位、被改動的 packet 檔或過期 permit 均 fail-closed。`architecture-critic` 的裸 `<fable-ok>` 也不授權。
- **runtime 失敗回報**（permit／classifier timeout／容量拒絕／headless 權限檢查卡住）：先講三句「review 有沒有開始／卡在哪一層／現在只決定什麼」，再放技術名、參數與成本證據；不要把內部詞當第一句。
- 單輪最多 4 個 architecture lens、8 個選定席位。finding 多寡不得觸發遞迴派工；補派或重試若會超過上限，先讓使用者決定。同一 command 重跑只取回原 permit，不會補回已消耗席位；使用者決定重試後，重新 invoke `/review-spec 3 <spec>` 建立新授權。
- 每支 Agent 完成時記下回傳的 agent ID。合成前執行 `python3 ~/.claude/hooks/review-spec-dual-verify.py --session "$CLAUDE_CODE_SESSION_ID" --permit-id <permit_id> --expires-at <expires_at> --snapshot <snapshot_path> --seat <slug>:<opus|fable>:<agent-id> ...`。明示配對快捷仍可用 `--pair <slug>:<opus-agent-id>:<fable-agent-id>`。validator 會要求輸入席位集合完全等於 finalized 配置；單席只驗該席，只有選定配對才要求兩席都完成，再核對 direct subagent JSONL、完整 artifact packet、permit 尚未過期、`architecture-critic` final attribution、每席 resolved model 精確符合 permit 綁定的角色 mapping、`end_turn` 與非空報告；同一 agent ID 完成後若又被續跑也會拒絕。只有 `valid:true` 會建立 owner-only 一次性 receipt；接著執行 `python3 ~/.claude/hooks/review-spec-dual-permit.py close --session "$CLAUDE_CODE_SESSION_ID" --permit-id <permit_id> --receipt <receipt_path>`。close 不信任 receipt 自報，會依 receipt 內的 seat／pair ID 再跑一次 verifier `--check-only`，成功才消耗 receipt 並清除 state／snapshot。任一選定席位缺席、模型解析錯誤、mapping 相同或漂移、席位配置／packet 不符或未完成，就標成「選定席位未完成」，呈現已完成部分與每席狀態後讓使用者選擇重新 invoke、接受不完整結果或停止；不得拿舊記錄、單支、偽造 receipt 或未選席位冒充完成。
- 合成採聯集後去重，每項保留角度與模型來源：`兩者皆有`／`僅 Opus`／`僅 Fable`／`互相衝突`。單席報告不得冒稱配對；模型分歧不是 finding 成立證據，仍需照本 command 的證據與呈現紀律核對。

## Tier 1 — 唱反調自審（in-context，預設地板）

不派 subagent。Main 對 spec 直接做對抗式自問，產出：

- 我做了哪 **3 個你可能不同意的決策**？各附「我選它的理由」＋「反方理由」
- 我對 [關鍵變數 / 範圍 / 依賴] **假設了什麼**？哪些沒跟你確認過？
- 這份 spec 哪裡**偷工 / 含糊帶過 / 留未解問題**？
- （本輪有跳過 lens 時加問）我憑什麼跳掉那幾支？**真的 grep 過還是憑印象**？被我判「不算對外契約」的那個 config / schema 變更，消費端真的沒有嗎？

自己能答的先答完、一次列完，只把真要使用者裁的問題留下來問。不要軟化、不要自己先幫忙辯護。完成後接「標準 Tier 1–4 共用收斂」，共用收斂完成才照下方「呈現紀律」surface。

## Tier 2 — 單一 architecture-critic（fresh-context）

`Agent` tool → `subagent_type: architecture-critic`、`model: opus`，prompt 前置 framing（architecture-critic 出身 code-modernization，要關掉它的 migration lens）：

```
這是一份 SPEC / design 文件的 review，不是 code migration。
套用你的 architecture-proposal lens：service/module 邊界是否對應真實 domain seam、
滿足需求的最簡設計、被忽略的 NFR（latency/throughput/consistency）、單點失效 end-to-end trace。
忽略 transformed-code / COBOL / JOBOL 那半段 lens。
Default stance: skeptical。找 over-engineering、漏掉的需求、更簡單的替代。

輸出：findings ranked Blocker / High / Medium / Nit，
每條：what / spec 哪段 / why it matters / 具體建議改法。
結尾一句：If I could only change one thing, it would be ___。

Spec:
[spec 全文]
```

收到 raw report 後先過守則 4 的席位驗收。valid report 完成後接「標準 Tier 1–4 共用收斂」，共用收斂完成才照下面「呈現紀律」surface。等效於對 spec 做單 critic 一發 adversarial review，這裡自己控派工以便接 Tier 3。

## Tier 3 — 多 lens 平行 + synthesize

### 前置：lens 派/跳裁剪

派工前先對下方每一支 lens 標「派／跳 + 一句理由」，不要無差別全派也不要憑印象砍：

- **跳過須附機械證據**，憑印象不准跳。例：跳相容 lens 的唯一合法理由 = `grep` spec 全文對對外介面／schema／config 變更字樣零命中 **且** spec 明文自述純內部重構；兩個條件都要，缺一就派
- **跳單非空 → 在 response 亮單**（lens + 理由 + 那條 grep 證據原樣輸出），**結束回合等使用者拍板才派**；**跳單為空（全派）→ 不問直接跑**
- 裁剪只砍 lens、不砍 severity 門檻，也不拿「這份 spec 很小」當跳過理由——spec 小就整體選低 Tier，不是留在 T3 砍 lens

裁剪拍板完成後，先依推薦矩陣與使用者明示配置告知實際席位，再把每個選定的 architecture lens／model 組合各自派出。架構批判與弱點批判可形成 polarity pair，但只有使用者選定兩席時才要求配對完成：

- **lens 架構批判（簡化軸）**：同 Tier 2 framing — default skeptical、找 over-engineering / 漏掉的需求 / 更簡單的替代。**偏 YAGNI / Torvalds 視角、抓「該砍什麼」。**
- **lens 弱點批判（強度軸）**：architecture-critic fresh-context、prompt 切對立 stance（**與架構批判形成 polarity pair**，借鑑 council-of-high-intelligence 的 Socrates/Feynman 對立 + Kahneman 自審 + Taleb tail risk 視角）：

  ```
  你是「找漏掉什麼」的 critic、不是找簡化機會的。

  Default stance: 假設這份 spec 在某些情境會裂。找：
  - 沒考慮的 edge case / failure mode / tail risk
  - 隱含假設（spec 沒明寫但默認成立的）— 列出來 + 各標「假設成立的前提」
  - 操作面盲點：rollback / 並發 / 競態 / 部分失敗 / 資料半路掛
  - 誤用面：使用者錯用 / 惡意輸入會怎樣
  - 能力放大時這設計會在哪先崩

  不要找 over-engineering / 簡化機會（那是「架構批判 lens」的活）。

  紀律：findings 要可操作 / 可驗證；不接受「理論上可能」級別的 paranoia。
  ```
- **lens 既有 repo 一致性**：architecture-critic，prompt 要它用 `Read`/`Grep` 讀 `CONTEXT.md` / `docs/adr/` / 既有 glossary，檢查 spec 有沒有跟既有 domain model、已決策、術語衝突
- **lens 相容／演進（契約軸）**：architecture-critic，prompt 要它用 `Read`/`Grep` 對照既有 code 與 spec，回答三問：(a) 這份 spec 動到哪些**已上線**的介面契約（API shape / DB schema / 事件格式 / config 格式），逐項列出改前改後 (b) 每個消費端的遷移路徑是什麼——誰在用、舊格式何時停止支援、沒跟上的消費端會怎麼壞 (c) 哪些變更需要 expand/contract 分段（先加新、雙寫過渡、再砍舊）而非一次切換。**不找 over-engineering、不找 edge case**（那是另兩支的活），只盯「上線後會不會把既有消費端弄壞」
- **lens 意圖對齊**：**不純 fresh-context**（守則 1）。Main 在 in-context 做，或蒸餾「使用者真正要什麼」brief 連同 spec 餵給一個 critic

所有選定席位完成且 resolved model 驗收通過後 synthesize：先按模型與 lens 做聯集去重，再按 severity 排；每條保留 `兩者皆有`／`僅 Opus`／`僅 Fable`／`互相衝突` 與 lens 來源，並做 **polarity contested 標註**（只有兩個對立席位都被選定時才適用；main 在 in-context 做、不另派 subagent）：

- 「架構批判」說 X 可以刪 → 「弱點批判」有沒有把 X 列為防禦？→ 有則 finding 標 `[contested by 弱點 lens]`
- 反向同理（弱點派要加 Y 防禦 → 架構派視 Y 為 over-engineering → 標 `[contested by 架構 lens]`）
- contested findings 在 surface 階段**單獨一段**呈現、由 user 決策、main 不替它判（這是 polarity pair 的核心產出 — 兩 lens 真實對撞處、最值得人工決策）

合成完成後接「標準 Tier 1–4 共用收斂」，共用收斂完成才照呈現紀律 surface。**報告開頭第一段固定列「本輪跳過的 lens + 理由」**，無跳過就寫「無」——跳單沉默等於宣稱全派，no silent caps。

想要**互動式**拷問而非自動 panel → 改去 `grill-me`（一句一句問）或 `grill-with-docs`（對既有 doc 互動壓測）；那是另一條路，不在這 command 內自動跑。

## Tier 4 — 外部跨模型暗門（手動，高風險 spec 才用）

> **當下路徑狀態**：`gemini -p` 個人 AI Pro 路 6/18 已退役（401 `IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals`，本機 v0.47.0 驗證、不可恢復）；`agy -p` Antigravity CLI 1.1.0（2026-07-10 實測）正常可用——**現役可選路徑 = codex、agy Gemini Flash 與 opt-in 的 agy Gemini Pro**；只派使用者選定的席位，不自動雙路。此結論沿用 trial `agy-review-flash-vs-pro` 結案 verdict（2026-07-10，全文見 ~/Desktop/projects/.claude/trials/archived.md）：Flash 在 5 個 PR 抓到全場唯一 CONFIRMED finding → 升 pr-review 永久軸；Pro unique 命中僅 2 PR 且帶結構性幻覺（高信心假警報）→ 降 opt-in 預設關。

外部模型給**不相關架構盲點**的第二意見。T4 先列出當次可用外部席位與推薦；只有使用者明示選定的席位才派工，不預設雙路，也不因未回覆而自動啟動任何外部席位。

🔌 接線點：ChatGPT 網頁版席位 — 見 WIRING.md

- **codex-rescue**：單 job（一次只跑一個）、**prompt 內硬性禁止開放式外查**（不准 WebSearch / WebFetch / 開 URL / 查 GitHub 星數）。T4 的 xhigh＋長 spec 一律視為可能超過 8–10 分鐘，照 `~/.claude/commands/pr-review.md` 的 canonical Run 段走 `subshell + nohup detach + rollout jsonl poll`；不要用 companion 自帶 background、Agent subagent 或 Bash `run_in_background` 直包。把 spec 當 prompt 要它讀一次就 adversarial 評，同 severity scale。（你的 codex 已配 `model = gpt-6-astra` + `model_reasoning_effort = ultra` = 旗艦，不用另指定 model；effort 比 model 更決定聰明度。）
- **agy Gemini Flash**——預設外部第二路；model id 只從 `~/.claude/model-routing.env` 的 `GEMINI_FLASH_MODEL` 讀取（trial 用 3.5 Flash 結案收編，後續升版不再分散寫進 command）：
  ```bash
  GEMINI_FLASH_MODEL=$(bash "$HOME/.claude/scripts/model-routing.sh" GEMINI_FLASH_MODEL)
  : "${GEMINI_FLASH_MODEL:?missing or invalid GEMINI_FLASH_MODEL in ~/.claude/model-routing.env}"
  agy --model "$GEMINI_FLASH_MODEL" --print-timeout 10m \
    -p "<禁外查 adversarial 評審 prompt + spec 全文>" 2>&1
  ```
- **agy Gemini 3.1 Pro (High)**——**opt-in、預設不跑**；僅使用者點名才加跑（trial 結案：unique 命中低 + `attributes-undefined` 類結構性幻覺、高信心假警報比漏抓更傷）：
  ```bash
  agy --model "Gemini 3.1 Pro (High)" --print-timeout 10m \
    -p "<禁外查 adversarial 評審 prompt + spec 全文>" 2>&1
  ```
- **agy 共通**：⚠️ **參數順序 hard rule（2026-07-05 實測）**：`-p` 取「下一個參數」為 prompt 值——`agy -p --model X "prompt"` 會把字面 `--model` 當 prompt 送出、回無關廢話（本日 T4 前兩發空轉主因）；`--model` / `--print-timeout` 一律放 `-p` 之前。`--print-timeout` 預設 5 分鐘，長 spec 拉到 10 分鐘比較穩；prompt 硬禁外查（同 codex）；OAuth 已登入（2026-06-24 本機驗證 `agy -p "ping"` 正常回應）；**不走 free REST API**（要吃訂閱、且 free 層會拿 spec 訓練）；findings 標 `[agy-Flash]`，使用者點名加跑 Pro 時另標 `[agy-Pro]`、不合併。

全路徑回齊後把各份批判 diff，標出**只有一方提的點**（這是 T4 的核心產出——交集是信心加成，差集才是跨模型盲點）；與 T2/T3 已有 findings 合成時同樣標注來源模型。完成後接「標準 Tier 1–4 共用收斂」。

## 標準 Tier 1–4 共用收斂：root / first_nail

這不是第五個 lens。各 Tier 先保留完整 findings，main 完成證據核對、聯集去重與 sanity-check 後，才在最終呈現前壓成兩個共同欄位：

- `root`：唯一承重問題；它若不成立，其餘 findings 會失去理由或降成次要。若多個問題彼此獨立，誠實寫「無單一承重問題」，不要硬湊假 root。
- `first_nail`：針對 root 的最便宜可證偽檢查。必須寫出輸入或樣本、動作、PASS／FAIL 訊號，以及時間或成本上限；規模要小於完整實作。
- root 為「無單一承重問題」時，每個獨立 root 各配一個 first_nail，並明寫哪些工作可平行；不要拿共同排程或同一份 spec 當成假根因。

單一 root 時，主報告先用兩行交付：

```text
承重問題：<root>
第一個驗證：<first_nail>
```

root 為「無單一承重問題」時，`第一個驗證` 按每個獨立 root 逐行展開，格式為 `- <root>：<first_nail>`，再標哪些可平行。

這個收斂區塊不取代 severity findings、自洽表、引證表或 contested findings。Done when：完整 findings 仍可追溯，root（或「無單一承重問題」時的每個獨立 root）能解釋為何它承重，每個 first_nail 都可直接執行並讓人決定停止、改路或繼續。YAGNI 軸已有分母檢查與最簡版舉證，暫不套本段。

## YAGNI 軸 — 需求定價（獨立呼叫）

觸發：`/review-spec yagni <spec 路徑>`；或 to-spec 落檔後的審查選單（最後一行有 `<review-spec-entry-menu:v1>`，由 `review-spec-tier1-nudge.sh` 要求）緊接著回 `f`——Fable 許可把這則 `f` 當成親手輸入的指令，不必再請使用者重打。與 T1–T4 正交：它們審「想得對不對」，本軸審「值不值得」。找洞型 review 對過度設計的 spec 是火上加油（每個洞的修補＝更多行），本軸方向相反——reviewer 的預設答案是「不做」。誕生脈絡：2026-08 closeout hook 案，模型代寫 spec 把一句「怎麼知道真的有東西散落在外」翻譯成證明級機械＋防篡改治理，7,200 行上線後複雜層被用 0 次。

1. **席位（預設單席 c；b 席每輪呈現給使用者拍板）**：**沒明示時不得逕自只派 c**——packet 組好後、派工前呈現一次**席位＋模型合併成一題**的選單，使用者只回一個字母。逐字照下方範本，`<…>` 換成當場解出的值，packet 路徑填步驟 2 實際寫入的絕對路徑、不要手打縮寫；同一則附當次 packet 字元數當成本依據（空問一句會退化成橡皮圖章）：
   ```
   派工擇一（席位＋模型，回一個字母）：
   - a. c 席・fable 級 → <Fable 實際值>
   - b. c 席・opus 級 → <Opus 實際值>
   - c. c 席＋web GPT Pro 席（多約 17 分鐘、燒 Pro 額度）・fable 級 → <Fable 實際值>
   - d. c 席＋web GPT Pro 席（多約 17 分鐘、燒 Pro 額度）・opus 級 → <Opus 實際值>
   <review-spec-yagni-model-menu:v1 packet=<packet 絕對路徑>>
   ```
   不要拆成席位、模型兩題，也不要請使用者分兩則回：Fable 許可只看最新一則選單後的第一則回覆，拆題會讓第二個答案永遠不算（2026-09-30 實例：使用者回「a,a」與隨後的「fable」都被拒）。指令已明示席位（如 `yagni b+c <spec>`）時不再問席位，但仍用同一個範本、只留該席位的兩個選項。AFK 或無回應走 b（單席 c＋opus 級）、不阻塞。b 席從 agy Gemini Flash 換成 web GPT Pro 的依據（2026-09-08 全量對帳 20 份雙席報告、813 對 verdict）：agy 席 unique 貢獻 22 條但 unique 誤報 29 條（誤報多於獨佔貢獻），砍除的 99 條裡 48 條與 c 席重複，漏抓 40 條是 c 席的兩倍；另有兩場全表只交出 0 砍與 2 砍，一場因把 rubric 明文保護的量測證據條目判成該砍而整席作廢。席位定義：
   - a. headless 原生 Claude：`bash ~/.claude/scripts/review-spec-yagni-native.sh <packet檔>`——清空 vendor env 後以 `opus` alias 的原生解析值一次性執行（腳本不寫死版號）；席位開始的證據是真正 request，不是 `claude auth status`；c 席被判同族自審且使用者不接受時的替補
🔌 接線點：ChatGPT 網頁版席位 — 見 WIRING.md
   - c. 本 session fresh subagent（`routed-judge`），**派工前先問模型級別、不代選**：模型級別併在步驟 1 的合併選單裡問、不另開一題，選項寫成 `fable 級 → <實際值>` 與 `opus 級 → <實際值>`，並在選單同一則說明「選定級別套用到 stories 與 decisions 兩批；這是範圍拆分，不代表增加不同模型視角」，兩個實際值當場解出——vendor session 取 `ANTHROPIC_DEFAULT_FABLE_MODEL` 與 `ANTHROPIC_DEFAULT_OPUS_MODEL`（各去掉尾端 effort 標記如 `(max)`），原生 session 為當前 Claude Fable 與 `opus` alias 的當下解析值（取 `~/.claude/logs/model-drift-watch.jsonl` 最新一筆 `claude-opus-*` 的 `model`；查不到就寫 `opus（解析值未確認）`，不寫舊版號）。**opus 級解出的值落在 free 池就在該行標 `⚠️ free 池`**：`routed-judge` 定義自帶的 opus 在 vendor wrapper 下被映射到 free 池，2026-09-08 全量實測 28 批 0 批跑到 Opus，8 批落 `z-ai/glm-5.3-flash`、1 批落 `deepseek-v4-flash`，那批砍除率 4.9%（對照 luna 17.4%／sol 15.8%）且 5 次 sentinel 無交件全出在它。使用者回答後才派，並把選定級別寫進 Run；AFK 或無回應走 opus 級——Fable 的可信 permit 必須綁定本輪真實人類選擇，沉默不能代替授權。`CC_VENDOR` 非空時先警告「同族自審、盲點可能同源」，使用者可換 a。**c 席走 deterministic 分批契約**：packet 條目拆成 stories／decisions 兩批各派一席，每席開工第一步先 Write sentinel 檔 `~/.claude/.scratch/yagni-c-<batch>-<session-id>.started`，逐條表寫進同目錄 `.report.md`，該檔**首行固定寫 `resolved_model: <值>`**（值取自該 subagent 回報的實際模型；拿不到就寫 `unknown`，不留空、不猜）；main 起跑後 60 秒查不到 sentinel 即標該批 invalid、不用同一契約 focused retry，只保留另一批與其他席（2026-08-27 兩次 60 秒、08-29 三次 600 秒無 final 的同型卡死）；**report 檔是交付物本身**——2026-09-09／09-10 四次派工都帶了 report 指示，c 席四次都只回 final、自稱「本席輸出限制不允許寫 report 檔」，其中一批的完整逐條表因此從未落磁碟。那個限制不存在：`routed-judge` 工具集全開，同一席剛寫成功的 sentinel 就是反證。派工 prompt 要寫進「你有 Write 權限、sentinel 已證明；final 只回計數與路徑」，但不能只靠這句——真正的落檔保證在下方步驟 3 的 main backstop
     **Fable permit 接線（只在模型選單明確選 Fable 時走）**：
     1. 步驟 1 合併選單的最後一行固定放 `<review-spec-yagni-model-menu:v1 packet=<packet 絕對路徑>>`；路徑就是步驟 2 的 canonical path（`~/.claude/.scratch/review-spec-yagni-packet-<session-id>.md` 展開成絕對路徑），也是下一步 `issue --packet` 要傳的同一個值，兩者不相等 helper 就拒發。選單先於 permit 存在、帶不了 permit_id，所以改帶 packet 路徑。使用者回代表 fable 的字母（範本裡是 `a` 或 `c`）或 `fable` 才算選 Fable——helper 從選單文字讀出哪些字母是 Fable；`照推薦`、沉默或其他文字不授權，改走 Opus，或重新列一次完整選單再問（helper 只看最新一則選單後的第一則回覆）。
     2. 選 Fable 後、任何新使用者訊息出現前，執行 `python3 ~/.claude/hooks/review-spec-yagni-permit.py issue --session "$CLAUDE_CODE_SESSION_ID" --packet "<packet 絕對路徑>"`。helper 會從 top-level transcript 重驗同 session `/review-spec yagni`、模型選單與最新人類選擇，建立 owner-only 的 packet 快照副本（不可變靠複製與檔案權限）；非 0、`allowed != true` 或缺欄即停止，不手補 state／marker。
     3. stories／decisions 各自在 dispatch 前執行 `python3 ~/.claude/hooks/review-spec-yagni-permit.py marker --session "$CLAUDE_CODE_SESSION_ID" --permit-id "<issue 回傳 permit_id>" --batch <stories|decisions>`。Agent 使用 `subagent_type: routed-judge`、`model: fable`；description **只放**回傳的 `<review-spec-yagni:v1 ...>` marker，不加 generic `<fable-ok>`。prompt 必須各自只出現一次 helper 回傳的 `snapshot_path`、該 batch 的 `.started` 與 `.report.md` 絕對路徑；第一個動作 Write sentinel、第二個動作 Read 完整 snapshot。
     4. 兩個 Agent call 都被 gate 接受後保留 snapshot；close 會刪除它，派工接受不代表 reviewer 已讀完。完成後接步驟 3 的交件核對與 3.1「Fable permit 收尾」。任一 batch 被拒或未派就不 close；permit 固定到期且 batch 單次消耗，重試需重新 invoke `/review-spec yagni` 取得新的人類選擇。
     Done when：Fable 路徑有 issue 收據、stories／decisions 各一筆 permit consume audit、close 成功（在 3.1 收尾核對）；Opus 路徑沒有建立 YAGNI permit。
   - d. 這次不跑
   Done when: 席位組合確定（預設或使用者指定）。
2. **組 packet**：packet 用 Write tool 寫到 neutral canonical path `~/.claude/.scratch/review-spec-yagni-packet-<session-id>.md`，不得沿用 spec／工具名稱進 packet 路徑，也不得用 shell redirect 寫 packet。內容＝spec 全文＋使用者原話引文附錄（彙整 spec 內 `[user: …]` 標註；spec 沒標時回對話撈原話補上）。**引文是指涉型短答時必須連前一則一起收**——`a`／`b`／`照這個`／`可以`／`當然要驗證可用性` 這類回答的語意住在它所指的那則選項或提案裡，只收短答會讓 reviewer 把已拍板的邊界誤判成模型推導（2026-08-23 實例：只抽 `[user: "a，當然要驗證可用性"]`、漏掉選項 a 原文「讀現有 NIM key 並複製進隔離 config」，routed-judge 因此要求 demote 一條使用者已拍板的 credential 邊界）。收法：短答與被指涉的選項／提案文字成對放進附錄，標明哪句是問、哪句是答＋步驟 3 的 rubric 全文。照貫穿守則 0（CLAIM 隔離）：不放 spec 作者或 main 的評估與辯護理由。**研究數字與 wayfinder resolution 要附**：spec 引用的研究檔關鍵數字表（大小／次數／頻率）與 wayfinder 逐題拍板紀錄一併進附錄——2026-08-21／08-23 三場翻案共同根因是 reviewer 把「spec 沒寫」判成「沒發生」。Done when: packet 檔存在且 grep 不到作者結論字樣。
3. **派席執行三檢查**，輸出逐條表 `# | 條目 | 來源類 | verdict | 一句理由`：
   - **來源追溯**：逐條 requirement／user story 分類——(a) 使用者原話（核對引文真偽）／(b) 量測證據（附數據出處）／(c) 模型推導。(a)(b) 受保護不砍；(c) 逐條要求「砍掉會發生什麼具體損失」，答不出 → verdict 為 `demote-v2` 或 `kill`。
   - **分母檢查**：spec 是否回答「這問題過去實際發生幾次、每次損失多少」。沒有 → 標「未定價」，未定價問題的解法以最簡版為上限。
   - **簡單版舉證**：reviewer 先寫出一頁最簡版方案，逐條列 spec 超出最簡版的部分——舉證責任在 spec 方，不在砍方。
   - **反方下限**：一席若輸出 0 個 `demote-v2`／`kill`，必須對每一條模型推導逐條證明砍掉的具體損失；缺任一條就視為 output shape 不合，回守則 4 focused retry。
   Done when: spec 每條 requirement 都出現在表中（枚舉核對條數，不抽樣），且每席通過守則 4 的席位驗收；c 席落檔的 `resolved_model` **只作紀錄、不作驗收條件**——唯一會標該批不可信的情況是選了 fable 級卻跑出別的級別（靜默降級）。選單解出 `free` 時池內任何一顆都算相符，選 free 就是接受不指定具體模型；`unknown` 照記，不因此作廢。主報告寫出實際落在哪個模型與當初選的級別。**main backstop（每席都做）**：c 席 final 回來後先確認該批 `.report.md` 存在；不存在就當場用 Write 把 final 全文落檔（首行照樣 `resolved_model:`，值取 final 自報、拿不到寫 `unknown`），確認兩批都有檔才進步驟 4——逐條表只留在 transcript 等於下一輪讀不到，2026-09-10 已因此遺失一批完整表。
3.1 **Fable permit 收尾**：步驟 3 核對交件後接本步。兩批都已完成、失敗或取消，且 main 已核對交件結果後，才執行 `python3 ~/.claude/hooks/review-spec-yagni-permit.py close --session "$CLAUDE_CODE_SESSION_ID" --permit-id "<permit_id>"`；只要任一批仍在執行，就保留 snapshot 等完成通知。失敗／取消先記錄結果，缺表不算審查通過；清理不重跑舊審查。任一批未被接受或未派出時不 close；helper 拒絕時保留原回件，不重建 permit。Done when：兩批已停止、交件結果已記錄，且 close 成功或拒絕原因已記錄；有效交件才接步驟 4，無效交件維持未完成。
4. **主報告三句再 dispute 上呈**：surface 前固定先講三句「這輪在審值不值得做／兩席（或 reviewer）一致認為哪裡太早／你現在只決定要不要縮 scope」，逐條表、內部 ID 與來源分類統計下沉到 yagni-review 檔、聊天不重播。接著表交回 spec 作者（或 main session），作者對每條只能填 `accept`／`dispute`。accept → 改 spec；**dispute → 條目與 reviewer 理由原文上呈使用者拍板，作者不得自行關閉、不得以完備性為由保留 (c) 類條目**。Done when: 每條 verdict 都有 accept 或使用者裁決，零懸置。
5. 落檔照下方「落檔」段，檔名 `<YYYY-MM-DD>-<topic>-yagni-review.md`，接摩擦盤點。

## 呈現紀律

收到 subagent raw report 後 **DON'T**：

- verbatim 整份倒給使用者（TUI 吃力 + 沒做 main 該做的篩選）
- 軟化結論——critic 的 severity 與措辭原樣傳達，見下方 DO 的「結論強度不變」
- 在 finding 旁加自己判對錯
- 主動提「我來幫你改 code」（spec 內 actionable 修正照下方 DO 直接落；code 改動是使用者另一個 explicit request）

**DO**：

- 呈現前先把每條 finding 分類、first-match 優先序：**題目誤讀**（critic 誤解 spec 某段 → 先補 spec 該段說明、該條重審，不直接丟棄也不照單全收）→ **actionable** → **trade-off**（兩個合理標準對撞、留使用者裁）→ **noise**。判 noise 時反問一句「在餵給 critic 的材料裡補什麼 context 能防這個 false flag？」——答得出來就補，下輪不再誤報
- **橡皮圖章訊號（靠紀錄算出來，不靠記得）**：**派 critic 前**就先讀回同目錄既有 review 檔的 disposition 行——`grep -h '^- disposition:' <spec 同目錄>/*-review.md`——當場數出「前 N 輪各有幾條 substantive finding、其中幾條判 actionable」並印給使用者。**連續 2+ 輪有 substantive findings 而 0 條 actionable** = 這是 validating 不是 doubting，停下，把分類理由攤給使用者檢查或升 Tier，不要繼續蓋章。每次 `/review-spec` 都是新 session、記不得上一輪，所以這個訊號只能從落檔算；沒有 disposition 行就等於這個訊號結構性抓不到。**查無前輪** review 檔或前輪沒有 disposition 行時明寫「查無前輪紀錄」，不要當成乾淨
- 按 severity 排（Blocker → High → Medium → Nit）
- 每條給 spec 原文核心句 + 1–2 句濃縮抓重點，**結論強度不變**
- **跨元件／多分支 trade-off 先畫目前流程**：最後一輪拍板若涉及跨 component／service／module／package／process 的呼叫順序，或含 branch／fallback，先在拍板表前用 call tree／pseudocode 畫「目前怎麼走」。本輪推翻舊結論時，緊接 `之前／現在` diff，只標唯一翻案；不改核心決策的 findings 另列「旁支發現」，每條附預設建議。
- **先 triage 完才開口、只把真衝突留到最後一輪拍板**：題目誤讀→補 spec 該段並重審；actionable 且不動 scope／行為／風險承擔→直接改 spec、在 review 檔逐條記「改了什麼、依據哪條既有決策」；事實更正與既有決策可推導項同樣直接落；noise→記理由。剩下的 trade-off（scope、行為、風險承擔、reviewer polarity 真衝突）彙總成**最後一輪拍板表**：一列一題、每列 a／b／c、推薦放第一、選後效果先講。不逐條停下問 act／ignore——使用者 2026-08-21 原話「能自決盡量自決，只有真正需要我決策的最後再討論」
- **架構意圖圖 decision nudge（trial）**：Tier 3／重大架構 spec 若改變 domain／deployment／trust／data-ownership boundary，或 component／service／module／package／process 間的 cross-boundary edge，就在最後一輪拍板表追加「此 spec 適合先看架構意圖圖：a. 生成  b. 跳過」。API／schema／config／retry／lifecycle 只有造成上述 boundary／edge 變化才觸發。
🔌 接線點：架構圖產生與審批 — 見 WIRING.md
  - 只有 Archify wrapper 成功且 intent artifact 與 wrapper receipt validation 通過，才啟動唯一一支共用 adapter background task：`Bash(run_in_background=true): node ~/.claude/scripts/plannotator-review.mjs intent <wrapper-receipt>`；記錄 `adapterTaskId` 與 wrapper receipt identity，同一 identity 同時只能有一支 live task。
  - Bash 回報 `running in background` 或 `moved to background` 代表 adapter task 仍在執行，不是 adapter timeout。adapter task 還是 live 時不得啟動第二支、不得讀未完成 receipt，也不得要求 top-level human 用 user shell 重跑；若收到重跑要求，回覆現有瀏覽器審閱仍在等待，繼續等同一支 task。
  - 等 harness `task-notification` 明確回報 `completed` 或 `failed`，不主動輪詢。通知後只用 Read 讀 output file 一次，接受唯一 final JSON 的 `receipt` path；task failed、final JSON 缺失／重複或 receipt path 不唯一都維持 `BLOCKED`。
  - 只有 adapter exit0 且唯一 receipt `decision=approved`、`transition=intent-accepted` 才放行 review-spec completion／to-tickets／implement；`intent-accepted` 只放行這三個下游階段。
  - `approved with notes` 仍回傳 `decision=approved`、`transition=intent-accepted` 並視為接受；持久化 notes／feedback 與 adapter receipt path 到 review artifact／handoff，列為 downstream implementation inputs。
  - adapter exit1 且 receipt `decision=annotated`、`transition=classification-required` 時，持久化 feedback 並維持 `BLOCKED`；只向 top-level human 要求分類 `artifact-inaccurate` 或 `architecture-rejected`，agent 不得自行猜測。
  - `artifact-inaccurate` 只能針對同一份已接受的 spec 與同一個 intent source 重生圖並重跑 adapter；`architecture-rejected` 回到 spec revision，並使舊 artifact／adapter decision 同時失效。
  - `dismissed`、timeout、gate-error、invalid result、receipt/artifact drift 全部維持 `BLOCKED`，不得轉成 waiver 或放行；classification no answer 也維持 `BLOCKED`。
  - 選 b 或不回答為 0 次 Archify、0 次 Plannotator，不阻塞 to-tickets／implement，也不得取代 post-implement actual delta。
  - `/wait-what` 互動圖接線已在 trial review 退役；Figma、native PlanMode 行為與觸發條件保持不變。
- 使用者隨時可要 `show all`（完整 triage 表）或 `反駁` 任一條；改 spec 以外的 code 仍是另一個 explicit request，不主動提
- **拍板表收齊回覆（或使用者說夠了）→ 必進下方「落檔」段寫 review.md，這是 review 的收尾動作不是可選項**

## 落檔

審完把 findings 寫到 spec 旁：`<spec 同目錄>/<YYYY-MM-DD>-<topic>-review.md`（date 用 `date +%F`）。它是 persistent source of truth — 之後實作出 bug 可指回這份自我修正。**不要** git commit（交給使用者）。

落檔時每條 finding 給穩定 ID（`F1`、`F2`…，同一份檔內不重號），並在檔末 `## Dispositions` 段逐條寫一行固定形狀，讓下一輪能用一個 grep 統計：

```text
- disposition: <ID> | <class> | main=<verdict> | user=<verdict> | <一行理由>
```

- `<class>`：`misread`／`actionable`／`tradeoff`／`noise`，取上方 triage 分類的原詞
- `main=`：Main 這輪的判定，用同一組分類詞（`main=actionable`、`main=noise`…）
- `user=`：`accepted`／`dismissed`／`deferred`／`n/a`。上呈拍板表的條目照使用者實際回答填；`n/a` 代表 Main 自決、沒上呈
- 這一行的形狀與 `review-implement` 的 `### Dispositions` 段共用，所以跨兩支機制可以一起 grep

沒有拍板表的輪次也要寫這段——全部 `user=n/a` 是有資訊的紀錄（代表這輪沒有任何條目上呈）。

落檔後做摩擦盤點再收工：本次 review 過程有無預見或撞到的摩擦（含 critic 派工不順、材料準備缺口）→ append 所屬機制的 `friction-log.md`，無主的落 `~/.claude/friction/workflow-general.md`（規則見 `~/.claude/friction/PROTOCOL.md`）；無摩擦不留紀錄。
