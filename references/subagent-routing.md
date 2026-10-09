# Subagent 模型路由 SSOT

派 subagent（Agent tool / workflow agent() / specialized agent）時、按任務性質決定 model。本檔是 single source of truth，散落在多處的規則都引用這裡。

## 派工前核對實際模型

派工前先查當前環境是否透過 vendor、proxy 或別名映射模型，並區分「要求的模型」與「這條路徑實際會呼叫的模型」。可用環境標記的存在性、非敏感映射設定與同路徑近期 runtime 紀錄查證；不讀取或輸出憑證。沒有映射標記也不單獨證明是原生模型。

若要求特定模型或跨模型意見，而目前 subagent 路徑會把它映射成另一個模型，就不要照送後仍按別名標示。已獲准使用 Herdr 時，可依 herdr skill 在原生 TUI 啟動指定模型與 effort；先查新 shell 的映射狀態，未獲准的替代路徑另請使用者決定。不要修改 ccp 或全域認證來湊模型。

派出後仍核對 runtime 的實際模型與 effort；不符就如實標示，保留結果但不冒充原選席，也不重跑其他已成功席位。以上是派工判斷，不新增模型 registry 或檢查程式。完成核對後再依下節選擇任務類型與 agent。

## 三分類定義

按任務性質決定 model：

- **實作任務**（production code / 多檔整合）：`routed-impl` 釘死 sonnet + high（2026-08-12 routed-agent-enforce KEEP 定案時為 opus + medium；2026-09-29 Sonnet 5.5 起改 sonnet，品質靠 main 與 reviewer 驗收把關）；需讀既有 code 找 pattern 的整合要謹慎驗證、別把 plan snippet 直接貼上不比對現況
- **機械任務**（長翻譯 / 摘要 / 格式轉換 / 大量 chunk）：`routed-mech` 釘死 sonnet + medium（description 需 `<mech-ok>`）；要 haiku **一律在 workflow authoring 寫死**
- **判斷類**（架構決策 / synthesis / verify / 主軸抽取）：`routed-judge` 釘死 opus + high、不繼承 main（2026-07-20 拍板，見下方「Fable 配額政策」）

### `<mech-ok>` 嚴格 opt-in

互動式 Agent 只有三項資格全成立才可派 `routed-mech`：

1. 輸入完整。
2. 輸出固定。
3. 不需搜尋、驗證或取捨。

- `<mech-ok>` 只放在 Agent tool 的 `description`；prompt 中單獨出現不算。
- 任一項不確定時，不填 marker，改派 `routed-judge`。
- marker 只證明 main 做過顯式低配決策，不代表 gate 理解或驗證了自然語言意圖。

**安全敏感修飾符**（跨三分類疊加、不是第四分類）：任務涉及防禦性安全工作（authz / crypto / secret 處理 / 漏洞修補 / 安全工具開發）→ 顯式 `model: opus` + `effort: high`、**不繼承 main**。理由：Fable 級模型的安全分類器可能中途拒絕正當防禦性安全工作，pre-route 讓 refusal path 不可達、而不是碰到了再處理（借鑑 pilotfish security-executor 設計、2026-07-13 引入）。token 照原分類標（多為 `<routed:實作>` 或 `<routed:判斷>`）。

### 分類順序：看正確性責任、不看副作用

判類別時，不以「會寫檔、執行 CLI、修改多個檔案」決定；先問任務最不能省略的思考工作是什麼：

1. **先標記安全敏感**：涉及 authz、crypto、secret、漏洞修補或安全工具開發（含控制真實遠端 mutation 的 safety core）→ 套用安全敏感修飾符；接著仍依第 2～4 步判斷底層分類。sentinel 開啟時以 `routed-secure` 作為派工載體；sentinel 關閉時保留底層 `<routed:實作｜機械｜判斷>` token，並顯式使用 opus + high。
2. **需要形成或驗證判斷**：比較來源、解衝突、決定保留內容、綜整論點、驗證真偽、研究重查、抽取主軸 → 判斷類。
3. **改變正式程式行為**：目標已決定，核心工作是實作 production code 或整合跨模組行為與相依關係 → 實作類。「多檔整合」不是單純修改很多檔案。
4. **套用完整規格**：不需實質取捨，只做翻譯、摘要、格式轉換或固定規則批次套用 → 機械類。
5. **混合任務**：可拆時先派判斷類做決策／產規格，再派實作類或機械類執行；不值得拆時，依不可省略的最高認知負擔分類。

邊界案例：

- memory→wiki 若需篩選素材、解衝突與綜整主張，即使會寫入多個檔案仍是判斷類；已有完整保留清單與固定模板、只剩搬運時才是機械類。
- 上游研究／重新查證的核心是驗證結論，屬判斷類。
- 控制真實遠端 mutation 的安全 CLI，底層屬實作類並套用安全敏感修飾符；sentinel 開啟時派 `routed-secure`，關閉時使用 `<routed:實作>` + opus + high。

## Fable 配額政策（2026-07-20 拍板、quota-driven 暫時 cap）

當 main session 使用 Fable 時（Fable 限週額 50%），subagent **不默默繼承 Fable**。Fable 的基礎政策入口只有三個；正式窄例外另在本節明列：

1. **Main session 本身**（含對話、routing、最終 synthesis；是否使用 Fable 由使用者當下選擇）
2. **失敗升級終級**（見「失敗後升降級路徑」：sonnet → opus → Fable；派 Fable 時在 Agent description 標 `<fable-ok>` 過 T2-gate，prompt 內同名文字不算授權）
3. **`/advisor` 顧問諮詢**（2026-09-03 拍板）—— 使用者顯式跑 `/advisor` 並選擇 Fable 選項時的單次判斷外包。授權形式同上：`<fable-ok>` 放 Agent description。

第 3 條的成立理由是它結構上燒不動配額：只有人能觸發、一次一問、顧問只回判斷不進實作迴圈，沒有自動或遞迴路徑。與其讓它借用第 2 條的名義（`/advisor` 不是失敗升級，那樣記帳是錯的），不如明列。

**分帳（2026-09-10 起）**：三條入口仍共用同一個 `<fable-ok>` marker，但 `/advisor` 已改派專屬席位 `advisor-seat`（原本直接派 `routed-judge`），而 audit row 的 `subagent_type` 是結構化欄位、每列都有——所以顧問諮詢這條入口用 `jq 'select(.subagent_type=="advisor-seat")'` 就分得出來，不需要新 marker。剩餘限制：入口 1、2 之間仍不可分，且 audit row 不記實際解析出的 model（`audit_row()` 無 model 欄），所以「description 含 `<fable-ok>`」只是 Fable 消耗的代理指標，忘傳 `model:"fable"` 但放了 marker 的呼叫會被誤計。09-10 前的歷史列全掛在 `routed-judge` 底下、無法回溯分離（實查 15 列混了證據審核 5、advisor 3、review-spec yagni 6、其他 1，失敗升級 0 列）。

`fork` 曾被列為第三入口，也曾在 2026-08-14 依 main 是不是 Fable 條件放行（B 案）。**2026-09-05 拍板改為一律要 marker**：fork 的 model 恆 = main（`model` override 被忽略、v2.1.232 起預設開啟、繼承完整對話與 prompt cache），所以每一發 fork 都是「完整脈絡 × main 的 model」，最貴的派工形式。

**fork 每次先問，取得當次同意才派**：平常用一般 subagent；main 認為必要時，先用短句交代要做什麼、一般 subagent 為什麼不夠，再問使用者是否允許這一次 fork。未回答不算同意；同意只限剛說明的當次派工，不沿用到下一次、整個 session 或續叫既有 fork。使用者拒絕就改用一般 subagent 或由 main 自己做，不反覆遊說。已有可讀原文、文件或精確來源指針，不因「需要脈絡」就自動問 fork。

這是對話行為規則；下面既有 T2 gate 仍只檢查 marker／額度，不驗使用者同意，不能把 gate 放行或自己填 marker 當成人類授權。本輪不新增 permit 或逐次 LLM judge。

**現有程式的兩軸檢查**（不代替上方當次同意）：

| 軸 | marker | 適用範圍 |
|---|---|---|
| 脈絡 | `<fork-ok: 一句話理由>`，理由 ≥ 12 bytes | **一律要**，不分 main model |
| 額度 | `<fable-ok>` | 只有 `CC_FABLE_MAIN=1`（原生 `claude-fable-*`）才另外要 |

| description | fork 派工 | audit reason |
|---|---|---|
| 有 `<fork-ok: 理由>`，main 非原生 Fable | ✅ 放行 | `fork_ok` |
| 有 `<fork-ok: 理由>` + `<fable-ok>`，main 是原生 Fable | ✅ 放行 | `fork_ok` |
| 有 `<fork-ok: 理由>` 但 main 是原生 Fable 且無 `<fable-ok>` | ❌ 擋 | `fork_fable_main_no_marker` |
| 無 `<fork-ok:>` | ❌ 擋 | `fork_no_marker` |
| 有 marker 但理由過短或空白 | ❌ 擋 | `fork_reason_too_thin` |
| `fork-gate.off` sentinel 存在 | ✅ 放行（recovery） | `fork_gate_disabled` |

脈絡軸不分 model，因為 fork 的成本來自「帶整個對話」，與 main 是誰無關；這也繞過了「誰是最強模型」的偵測難題（舊設計靠 `CC_FABLE_MAIN`，而它只認名字含 `fable` 的模型，vendor 檔位偵測不到——上線 22 天 fork 的 Fable 分支 **0 次觸發**）。

額度軸維持只認原生 Fable 且**刻意不修** `fable-gate.sh` 的偵測：原生 Fable 是硬牆（週配額 50% cap，燒完就沒），vendor 檔位（`gpt-6-astra` / `gpt-6-sol`）走訂閱制，對 fork 只需要防「當通用工具用」，不需要額度授權。

**明文不保證**：marker 是自我聲明、純字串比對，空洞但夠長的理由照過——它換到的是「決定必須落成文字」，不是「決定必須正確」。Workflow script 內 `agentType:'fork'` 不 fire 本 hook，完全不受管。

fork 分支在 T2-gate 內置於 ENFORCE 兩態共用位置（legacy E1 不得放行 fork），所以 `routed-enforce.on` 改名**救不了它**；誤攔時的唯一出口是 `touch ~/.claude/hooks/fork-gate.off`。回歸測資 `T2-routing-gate.test.sh` case 15a–15i。用法定位：一般 subagent 或 main 自做為預設；只有完整對話確有必要且使用者已同意當次派工才用 fork。不能用未量測的快取或成本優勢替代當次同意。

v2.1.212 當初改的是 `/fork` **slash command**（把對話複製進新的背景 session），並把它原本啟動的 in-session subagent 改名為 `/subtask`；2026-07-30 由此推論「Agent tool 也沒有 fork」在當時為真，v2.1.232 已翻案。Workflow script 內 `agentType:'fork'` 不走 T2-gate，理論上不受影響，但**未實測**。

另有一個正式窄例外：`/review-spec 3 <spec>` 的 `architecture-critic` 選席支線。固定 marker 不構成授權：command 必須在讀取 spec 前，用 `review-spec-dual-permit.py issue` full-match 同 session 的明確 Tier 3＋路徑 command，建立以身分欄位綁定的 owner-only permit：command UUID、session、permit ID、spec 絕對路徑、快照副本路徑、到期時間與可選席位；後續使用者訊息會撤銷尚未建立的授權。同一輪 top-level assistant 先以 `<review-spec-recommendation:v1 permit_id=<id> seats=<lens:model,...>>` 留下推薦來源；使用者選擇後用 `finalize --seats <lens:model,...> --recommendation-event <assistant-event-uuid>` 原子寫入實際席位，`照推薦` 另帶 `--follow-recommendation` 且必須與該 envelope 完全相同，明示換選可不同；既有 `--lenses` 只保留為明示的雙跑快捷方式，但仍須同一輪 user 選擇，且新核可狀態不可跳過 reference／完整 Read；未選席位不可取 packet。每個選定 lens 由 `packet` 產生內嵌完整快照文字、permit_id、到期時間與 lens 的可信 prompt 前綴；Fable description 使用 `<review-spec-dual:v1 permit_id=<id> lens=<slug>>`，gate 逐欄比對身分欄位、並確認 prompt 的 packet 與 permit 記的文字相等後，原子消耗該 `lens:fable` 席；不計算也不比對任何內容 digest，快照不可變靠複製與檔案權限。合成前用 `review-spec-dual-verify.py` 以 `--seat <lens>:<model>:<agent-id>` 驗收單席，或以明示 `--pair` 驗收選定配對；輸入席位集合必須完全等於 finalized 配置，Fable remaining seat 必須清空，再核對 direct subagent JSONL、完整 packet、未過期 permit、resolved model、final attribution、`end_turn` 與非空報告。成功才產生綁定 seat／pair ID 的 owner-only receipt。`close` 會依 receipt 重新執行 verifier 的 check-only 路徑，成功後才消耗 receipt 並清掉 state/snapshot，plain JSON receipt 本身不構成證明。這個窄例外不授權 Tier 2、`/grill-me-one-shot`、裸 `<fable-ok>`、一般 code review 或其他 agent；`CC_VENDOR` 非空時仍要求 distinct vendor mapping，空值也不代表 first-party 證明，仍以 verifier 的 resolved model 為準。

第二個正式窄例外是 `/review-spec yagni <spec>` 的 c 席 Fable batch。`review-spec-yagni-permit.py issue` 只接受同 session 最新的 YAGNI command、帶 packet 絕對路徑的固定模型選單，以及緊接其後的 top-level 人類 `a`／`fable` 選擇；沉默、`照推薦`、後續新 user message 與固定 marker 都不授權。permit 建立 owner-only packet 快照副本，綁定 session、模型選單與人類選擇事件的 uuid、packet 路徑、到期時間、當前 vendor Fable mapping，並只留下 stories／decisions 各一次消耗額度。description 使用 `<review-spec-yagni:v1 permit_id=<id> batch=<stories|decisions>>`，不得同時帶 generic `<fable-ok>`；T2 gate 另驗 prompt 精確引用 snapshot、該 batch sentinel 與 report 路徑，原子消耗後才放行。任一 batch 重放、跨 session、packet／mapping 漂移、helper 失敗或選擇過期都 fail closed；兩個 batch 接受後由 command `close` 清 state。這個例外只授權 `routed-judge model:fable` 的 YAGNI c 席，不授權 Tier 1–4、review-implement、一般 routed-judge 或其他 command。

### `review-implement` 的窄 model-selection authorization

`review-implement` 的 Scope／YAGNI reviewer 沿用既有 `routed-judge`，但每次授權綁定矩陣中的 `<logical model, axis>` seat；目前可選 `opus` 或 `fable`，不新增 `/review-spec` 的 permit、manifest 或 mapping 系統。授權仍需具備下列既有條件：

1. 同一 `session_id` 的 transcript 中，top-level assistant 成功呼叫 `Skill(review-implement)`。
2. 該 `Skill` tool_use 後有唯一 matching、non-error 的 tool_result；runtime result 可用 `success:true` 且 `commandName:"review-implement"` 證明成功。
3. 同一 stage result 後只接受一個 top-level user selection：既有 axis 字、固定字母，或包含明確 model／axis 的自然語言；字母仍須和該 invocation 後唯一的固定選單綁定。`照推薦`／未指定 model 沿用本輪矩陣標出的推薦 seat，`skip`／`d` 不授權 reviewer，多個 user selection 使 invocation stale。
4. Agent description 放單一 `<review-implement-selection:v1 model=opus|fable axis=scope|yagni>`；fable seat 另放 `<fable-ok>`。既有 `<review-implement-fable:v1 axis=scope|yagni>` 只作 fable 相容快捷方式，marker 不構成授權。
5. `tool_input.model` 必須等於 marker 的 logical model、reviewer 必須是 `routed-judge`，且同一 Run 不得重派相同 model／axis seat。

Controller 的 dispatch 形狀如下；每個 selected seat 各派一次，同一 axis 可派兩個不同 model：

```text
Agent(
  subagent_type: "routed-judge",
  model: "opus",
  description: "<review-implement-selection:v1 model=opus axis=scope>",
  prompt: "<scope reviewer prompt>"
)
```

Fable seat 使用 `model: "fable"` 與 `<fable-ok> <review-implement-selection:v1 model=fable axis=scope>`；native／vendor 的 resolved model、缺 mapping deny 與 `unknown` 報告標示沿用 gate 規則。Audit 保留 stage、axis、session、logical／resolved model 與 reason，不記 prompt／description；同一 Run 只允許一次相同 model／axis seat，不同 model 可共享 axis。既有 generic Fable 的 `<fable-ok>` 失敗升級路徑維持不變，但它不能替 review-implement stage 授權。

#### Authorization surface

| 面 | 分類 | 邊界 |
| --- | --- | --- |
| T2 gate、routing policy、固定字母選單、model matrix 與既有 fixtures | Locked | reviewer 不得改寫規則、矩陣或選單後替自己授權 |
| reviewer prompt、finding 與 report | Editable | review stage 唯讀，不得用它們證明授權 |
| T2 audit／trace log | Append-only | 只追加 allow／deny evidence，不回寫歷史列 |
| stage invocation、top-level model／axis selection、sentinel 與 locked-surface permit | Human-controlled | 由使用者或既有 operator recovery path 控制；字母只在 Locked 的固定選單綁定後代表 semantic axis，不由 marker 自證 |

Locked surface 的生命週期沿用既有 agent-contract gate：bootstrap 走既有 locked-file bootstrap exemption；update 由使用者以既有 staged-tree permit 變更並重跑 T2 fixtures；recovery 把 `routed-enforce.on` 改名只回退 allowlist，完整回退則還原既有 gate 版本或沿既有 locked-surface 路徑撤回，不新增 review-implement sentinel。每條路徑都應留下既有 audit／commit trace。

| 繞行嘗試 | 攔截點 |
| --- | --- |
| 只有固定 `<fable-ok>` 或 structured marker，沒有成功 stage transcript | `review_implement_stage_missing` 或 `review_implement_marker_missing` |
| marker 只放在 prompt、放多個 marker，或 model／axis 不在矩陣 | `review_implement_marker_invalid` |
| payload／transcript 不一致、stage result 無效、選擇過期或同一 model／axis 已派過 | 對應 `review_implement_*` fail-closed reason |
| 字母選擇前沒有唯一逐字固定選單、選單被改字／調序、重複，或選單只出現在 sidechain／tool result | `review_implement_axis_alias_unbound` |

這是防漂移 gate，不承諾抵抗同 UID 主動竄改 transcript、環境變數或本機檔案；判不出授權一律 deny。

**預設從「不指定 = 繼承」改為「必須顯式指定」**：main 為 Fable 時，T2-routing-gate 會攔下未指定 model 的 general-purpose 派工。這條 override 舊規則「絕不為強任務顯式指定模型、避免凍結成意外降級」——它綁定 Fable 50% 配額政策，**政策撤了本段整段刪、回復繼承預設**，不是永久凍結。

判斷類預設維持 opus+high。`fable-routing-downgrade` trial 證明架構審查兩個模型各有獨有採納 finding，因此只在 `/review-spec` Tier 3 保留正式雙跑，兩份報告共同進 synthesis。`typescript-reviewer`、`python-reviewer` 與 generic `code-reviewer` 維持 Opus；Python／generic 的 Fable 影子觀察沒有取得有效 pair，依「雙跑就正式合流，否則單跑」原則退役，不把零樣本解讀為 Opus 勝出。

安全敏感修飾符不受本段影響（原本就顯式 opus）。

## routed-* enforce（常態；2026-08-12 routed-agent-enforce trial KEEP 結案）

**`general-purpose` 與所有無定義檔的 agent 已停用**（含內建 `claude`；CC 層 `permissions.deny` 已加 `Agent(general-purpose)` / `Agent(claude)` 先攔，hook 白名單 fail-closed 後備）。即興派工改用四個 model + effort 已釘死的 agent，**不需 `<routed:>` token**——agent 選擇本身就是分類宣告；`routed-mech` 另須在 description 放 `<mech-ok>`：

| agent | 分類 | model | effort |
|---|---|---|---|
| `routed-impl` | 實作 | sonnet | high |
| `routed-mech` | 機械（description 需 `<mech-ok>`） | sonnet | medium |
| `routed-judge` | 判斷 | opus | high |
| `routed-secure` | 安全敏感修飾符 | opus | high |

- 有定義檔的 specialized agent（deep-explore / code-reviewer 等）、plugin agent（含冒號）不受影響
- Workflow `agent()` 不經過本白名單（E2 例外照舊）；workflow 端改由 `workflow-routing-gate.py` 檢查，規則見「B. Workflow author 寫 script」
- 互動式 `routed-mech` 在 sentinel 開啟或關閉時都檢查 description 的 `<mech-ok>`；Fable N1 仍優先於 mech marker
- 升級階梯改用 per-call `model` override 打在同一個 routed-* 上（frontmatter model 會被 per-call 參數覆蓋）；Fable 終級仍需 description 的 `<fable-ok>`。`architecture-critic` 不接受裸 `<fable-ok>`，其 Fable 窄例外只認 `/review-spec 3 <spec>` 建立的可信 permit、完整 artifact packet，以及含 permit ID／lens 的 description marker；固定 marker或沒有 permit 的 `model:fable` 仍會被擋
- `routed-impl` 的 effort 是 routed-agent-enforce trial 首次定義（三分類原本只定 model、實作類 effort 空白；當時 medium，2026-09-29 改 sonnet + high）
- EXTRA_ALLOW 的 `claude-code-guide` 是 CC 內建（磁碟無定義檔、預設跑 haiku——2026-07-30 transcript 實錄）；查證結果要寫進規則檔的任務帶 per-call `model: sonnet|opus` 蓋掉（同日 probe 實測 override 生效、transcript 實錄 `claude-sonnet-5`）。effort 無 per-call 參數、內建 agent 不可調

**啟用開關**：`~/.claude/hooks/routed-enforce.on` 存在時啟用白名單強制。改名不需重啟，但只會回退白名單；`routed-mech` 的 `<mech-ok>` opt-in 仍保留。完整回退需同時還原 mech gate、agent 契約與 routing 文件。

⚠️ **開啟前必須確認 routed-* 已載入**（agent 檔需重啟 session 才生效，2026-07-26 實測）。在未載入的 session 開啟 sentinel → 該 session 失去所有即興派工能力（general-purpose 被擋、routed-* 不存在）。檢查方式：派工錯誤訊息附的可用 agent 清單裡有沒有 `routed-impl`。

Trial 全程紀錄見 `~/Desktop/projects/.claude/trials/archived.md` `routed-agent-enforce` 段（2026-08-12 KEEP 結案）。

## 三場景的執行紀律

### A. Main session 即興派 Agent tool

sentinel 開啟時直接選 `routed-{impl,mech,judge,secure}`；只有 `routed-mech` 另須在 description 加 `<mech-ok>`。三項資格任一不確定就改派 `routed-judge`，不要猜填 marker。

sentinel 關閉時，general-purpose 沿用 prompt 或 description 的分類 token：

```
<routed:實作>  / <routed:機械>  / <routed:判斷>
```

T2-routing-gate hook 強制 enforce；互動式 `routed-mech` 即使 sentinel 關閉，仍只接受 description 的 `<mech-ok>`。

- `subagent_type` 為 specialized agent（deep-explore / code-reviewer / docs-lookup / chrome-fetcher / parallel-search / url-fetcher / claude-code-guide 等）→ E1 自動 pass、不需 token；`routed-mech` 是唯一例外，仍需 description 的 `<mech-ok>`
- Workflow 內 `agent()` call → 完全不 fire hook、不需 token（2026-06-21 B probe 實證 workflow agent escape PreToolUse:Agent hook）

實際 routing 仍由 main 自決：token 只強制過 gate、不指定具體 model。但 main 為 Fable 時多一道檢查（fable-gate 注入 `CC_FABLE_MAIN=1`）：general-purpose 派工**未指定 model → deny**，需顯式指定（判斷 → opus、機械/實作 → sonnet）或在 description 標 `<fable-ok>`（僅限失敗升級終級；prompt 內同名文字不算授權）。effort 無 tool 參數、在 prompt 內寫「以 xhigh 深度推理」等指示。

實作 / 重構型派工 prompt 先套模板（目標 / 不變量 / 範圍 / spec / 驗收 / 回報合約六件套）→ 見 memory `reference_dispatch_prompt_templates`。

#### Read-only worktree preflight

read-only Agent 只讀既有 detached worktree 時，不要為了隔離再傳 `isolation=worktree`。派工前先驗 Agent launch cwd 是否位於可建立 worktree 的 Git repo，或環境是否提供 WorktreeCreate hook；target path 本身是 worktree 不代表 launch cwd 通過前提。前提不成立就用 no-isolation，並在 prompt 給 absolute target path、明文禁止寫入。需要寫入但 isolation 不可得時，不套這個 fallback，改回 shared-tree 序列化或停止。

### B. Workflow author 寫 script

寫 `agent(prompt, opts)` 時，每個呼叫都用 `agentType` 指定上表的 routed-*，不在 script 裡手寫 model／effort 數值。為什麼：model 與 effort 只存在 agent 定義檔的 frontmatter，改一處全體跟著變；手抄數值會跟定義檔漂移（2026-09-29 RED：3 個 fresh runner 全部手抄、2 個漏寫 effort 而吃到 session 當下的 effort）。

```js
// 判斷（scope / verify / synthesize）
await agent('合論 + 寫信心區間', { schema: SYNTH_SCHEMA, agentType: 'routed-judge' })
// 實作
await agent('寫純新檔 + 完整 spec', { agentType: 'routed-impl' })
// 機械（fetch + 結構化抽取、大量 chunk）
await agent('fetch + extract claims', { agentType: 'routed-mech' })
// haiku-OK 機械（純翻譯 / 格式轉換）→ 同一個 routed-mech 再加 per-call model
await agent('翻譯這段', { agentType: 'routed-mech', model: 'haiku' })
```

- 2026-09-29 probe 實證（workflow `wf_1d4eecfa-e86`，transcript 的 `message.model` 與 `effort` 欄）：`agentType` 會套用定義檔的 model＋effort（mech → sonnet/medium、judge → opus/high、impl → sonnet/high，session effort 為 medium 時照樣），per-call `model` 會覆蓋 model、effort 仍取定義檔。
- workflow 裡的 `routed-mech` 不需要 `<mech-ok>`：那道檢查掛在 Agent tool 的 PreToolUse，workflow 不會觸發。
- 例外：specialized agent（`url-fetcher`、`chrome-fetcher` 等）照用自己的 `agentType`。只在非 Anthropic vendor session 跑、刻意繼承 main 的 workflow（目前只有 `deep-research-paced-zai.js`，GLM 已退役）會被下方 gate 擋；真要跑就暫時用停用開關，不另設放行標記。
- 機械 gate：`~/.claude/hooks/workflow-routing-gate.py`（PreToolUse:Workflow）會擋「opts 物件字面值裡沒有 model／agentType／spread」與「單參數 `agent(x)`」，deny 訊息指回本段。**明文不保證**：opts 用變數或 helper 傳入的呼叫看不透、照放；寫了 agentType 但分類選錯照放。

Workflow specific 細節（哪些 phase 算機械 / Search vs Fetch downgrade target）見 `~/.claude/skills/workflow-hardening/SKILL.md` §8。

### C. Specialized agent（main 派非 general-purpose）

`subagent_type` 為 specialized agent → agent description 已寫用途、有自己預設 routing。Main 派時：

- 不需加 `<routed:>` token（E1 pass）；`routed-mech` 例外，description 必須有 `<mech-ok>`
- 不需在 opts 指定 model（agent 預設處理）
- 視情況可加 model override（如 `parallel-search` 預設 haiku、main 想用 sonnet）

## 回報合約：輸出長度上限

subagent 回傳的內容整包進 main context；長回覆同時撐爆 main 的 context 與 CC 的 32000 output token 上限（2026-09-20 枚舉：`~/.claude/projects` 全庫 17 個 jsonl 命中 `output token maximum`，其中 11 個落在 `subagents/` 或 `workflows/` 底下）。三場景都適用：

- 每個派工 prompt 明寫回傳上限。預設 ≤300 字；判斷 / 合論類放寬到 ≤600 字，仍要在 prompt 內寫出數字
- 長產物（報告 / 逐條清單 / 抽取結果 / diff）一律寫檔，回傳只給絕對路徑 + 摘要 + 需要 main 拍板的項目
- 逐條枚舉型任務給筆數上限，超過就分批派；不要讓單一 agent 回完整清單
- 不靠調高 `CLAUDE_CODE_MAX_OUTPUT_TOKENS` 解決——上限調高只是讓更大的回覆進 main context，主 session 死得更快

## 失敗後升降級路徑

### 計數口徑（唯一定義；dispatch-and-verify.md 的訊號與 CLAUDE.md 摘要都引用這裡、不另立）

- **計數 key = 子任務 × root cause**。子任務 = 同一個目標 + 同一組輸入（重新拆解後是新子任務、歸零）；root cause 變了也歸零（第一輪 timeout、第二輪查出真因是缺環境變數 → 新 key 重數）。
- **計數單位 = 修正嘗試**。首次執行不算；之後每次「為同一 key 再試」都算一次——重派 subagent、main 自己重修、換一種修法、升級重派，全都算。
- **上限 = 同一 key 修正嘗試 2 次**。第 2 次仍失敗 → 禁止第三次、走「額度用盡四選一」。與 `~/.claude/commands/goal-gen.md` Retry / unblock policy「同 root cause 最多 retry 2 次」同一口徑（那邊管 /goal 無人值守、這邊管 main session 派工）。
- **邊界**：subagent 產出的瑕疵若 main 以 < 3 行 surgical edit 能修好 → 照 dispatch-and-verify.md「失敗 case 處理」直接修、不消耗修正嘗試額度。

- 正例：sonnet 派工失敗（首次執行、不計）→ 修正嘗試 1（升 main 重派）失敗 → 修正嘗試 2 失敗 → 四選一。
- 反例：三次都是同一個 assertion fail、每次換一種修法就當新的一輪（root cause 沒變、修法不同不歸零、額度第 2 次就用盡了）。

### 升級：sonnet → opus → Fable 三級階梯（2026-07-20 起）

機械 / 實作類子任務指定 sonnet 跑、失敗 → 修正嘗試 1 重派升 `model: opus`（prompt 註明 high 深度）；修正嘗試 2 仍失敗且判斷值得最後一搏 → 升 Fable 終級（Agent description 標 `<fable-ok>` 並簡述失敗軌跡；main 為 Fable 時可不指定 model 讓它繼承，否則顯式 `model: fable`）。每次升級 prompt 必帶三件事：原任務全文、上一輪失敗輸出（原樣貼、不摘要）、已排除的方向（「試過 X 不行、因為 Y」）。Fable 終級也失敗 = 額度用盡、走四選一。

- 正例：派 sonnet 改 5 個檔的 import 路徑，grep 驗證發現 2 檔漏改 → 重派寫 `model: opus`、prompt 貼「漏改的 2 個檔路徑 + 上輪回報原文」。
- 反例：sonnet 失敗後換個措辭再派一次 sonnet（同級重試燒掉一次修正嘗試、卻沒升級）；或升級重派但只寫「上次沒做好、再做一次」（沒帶失敗軌跡、強模型會重犯同一個錯）；或第一次修正就直接跳 Fable（跳過 opus 級、燒配額）。

### 額度用盡 → 四選一、不再嘗試

同一 key 修正嘗試 2 次用盡仍不過 → 四選一、選哪個明寫在回覆裡：

1. **換路**：回到問題定義重新拆解（子任務切法錯了、不是執行錯了；拆解後是新 key、額度重來）
2. **升 effort**：main 自己做、prompt 加 ultrathink 或 `/effort` 升檔（見 performance.md）
3. **外部第二意見**：codex-rescue（可靠配方見 codex-rescue.md：單 job、禁開放式外查、前景跑）
4. **停下問使用者**：判準見 dispatch-and-verify.md「停下問使用者 vs 自己決定」節

- 正例：兩次修正嘗試都卡同一個測試 → 明寫「選 1 換路：原拆法把 A、B 耦合的邏輯拆進兩個子任務、改成單一子任務處理」。
- 反例：額度用盡後「再試最後一次」（prompt 改多少都是第三次嘗試）；或默默改成自己做、不說明前兩次為什麼失敗（自己重做也是修正嘗試、同樣受額度管）。

### 降級：強模型解出的重複模式 → 蒸餾回 sonnet 批次套用

main 級解出會重複出現的模式（同型修改套用到 N 個檔 / N 個 case）→ 蒸餾成含完整 spec 的 prompt（輸入格式、輸出格式、邊界 case 處理全部寫死、不留「參考前面的做法」這種要 context 的指涉），降回 sonnet 批次套用。對齊三分類的機械類：spec 完整後它就是機械任務。

- 正例：main 解出第一個 API migration 正確改法後、把 before/after 對照 + 3 個邊界 case 寫進 prompt，剩下 12 個檔派 sonnet 各自套用。
- 反例：spec 只寫「照第一個檔的改法改其他檔」就派 sonnet（sonnet 看不到 main 的 context、會自由發揮）；或每個檔情況都不同（不是重複模式）也硬蒸餾。

## 驗證 / 退役 trigger

T2-routing-gate hook trial 期累積 audit log 看：

- **deny rate 高** → main 真常忘規則、gate 有用
- **deny rate 低** → main 當前 model 自律已夠；gate 轉入保險絲模式（低頻 review），退役判準改看「vendor / model 切換事件期間的攔截數」——連續 2 次切換事件、各自首兩週皆 0 攔截才考慮退役（單次安靜不足以退役、否則保險絲定位自毀；deny rate 低≠educated、見 [[feedback_hook_not_llm_trainer_attribution_2026_06_29]]）
- **token 偷懶率**（標 `<routed:判斷>` 但實際是機械）→ 高 = gate 流於形式、需加更嚴 enforce

2026-07-03 audit snapshot：真實 deny rate 3/64 = 4.7%（12 天、扣 smoke 13 筆）、偷懶率抽查 ≈ 0% → 已依上行轉入保險絲模式。

Audit log: `~/.claude/logs/T2-routing-gate-audit.jsonl`
Trace log: `~/.claude/hooks/T2-routing-gate.trace.log`

## 例外 / 邊界

- **Workflow author 寫 model 選擇時 confusion** → 看 [`~/.claude/skills/workflow-hardening/SKILL.md`](~/.claude/skills/workflow-hardening/SKILL.md) §8 workflow-specific guide
- **Specialized agent 預設 model 不確定** → 看該 agent 的 description（`~/.claude/agents/<name>.md` 或 plugin 自帶）
- **T2-gate 撞到不適合的 case** → 加進 E1（specialized agent 例外）或 E2（workflow context 例外）的 hook script 內

## 引用本檔的位置

- `~/.claude/CLAUDE.md`「Subagent 模型選擇」段 → 1 行 pointer 指此
- `~/.claude/skills/workflow-hardening/SKILL.md` §8 → 三分類定義 pointer、保留 workflow-specific Search/Fetch detail
- T2-routing-gate hook permissionDecisionReason → 1 行 pointer

修改三分類定義或 token 機制 → **改本檔、不改各 echo 處**。

## Cross-link

- `~/.claude/skills/workflow-hardening/SKILL.md` — workflow 寫作期間 always-on skill、§8 為本檔 workflow specific 延伸
- `~/.claude/hooks/T2-routing-gate.sh`（已全域 deploy 2026-06-21、經 fable-gate.sh 註冊於 settings.json）— main session 強制 enforce 機制
- memory `reference_cc_pretooluse_agent_mutate_probe_2026_06_21` — workflow agent 不 fire hook 的 B probe 實證
- memory `feedback_always_on_rule_adherence_empirical_low` — always-on rule 採用率低、不是集中能解的問題
