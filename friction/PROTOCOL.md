<!-- 本檔在契約測試底下：bash ~/Desktop/projects/.claude/hooks/trial-review-friction-consumption.test.sh && bash ~/Desktop/projects/.claude/hooks/friction-review-state.test.sh -->

# 通用摩擦協議

CC 執行過程的摩擦（卡住、繞路、重複踩坑、規則沒被遵守）統一按本協議紀錄與消費。捕捉觸發長在錨點上（authoring/review 類 skill 收案步驟、save-session），不依賴使用者想起來；消費由事件制 sweep 提醒、折入一律過使用者拍板。

## 紀錄格式（一行一條）

新寫入固定帶最小 provenance envelope；舊格式仍可讀、不要求 migration。`flags` 是唯一 optional 欄位，沒有值就連同前面的分號一起省略：

```
- YYYY-MM-DD [source_ref=<session:<id>#<turn>|pr:<url>|issue:<url>|test:<path>|other>; signal_type=<user-correction|expert-feedback|test-failure|agent-observation>; target=<skill:name|command:name|agent:name|hook:name|rule:path|workflow|unknown>; feedback_quote="<短 sanitized 原文|N-A>"; why="<改寫後的明示理由|unknown>"; flags=<flag[,flag...]>] <改寫後的一句摩擦> <建議方向>
```

- `source_ref` 只放能回到原始 episode 的必要指針；不把整段 agent output 複製進摩擦檔。
- `feedback_quote` 只在判 authority 或根因需要逐字證據時保留最短 sanitized excerpt；其餘填 `N-A`。
- `why` 改寫來源明示的理由；沒有就填 `unknown`，不得把 agent 推測冒充人類理由。
- `target` 當下不確定時填 `unknown`，等消費時再路由。
- 敘事只保留可處置的原因、影響與建議方向，改寫 user／external text／log／error／code；移除 secret、個資與不必要的識別碼、內部 path、hash、service name。path、hash 與短引文不是禁用類別：如果缺少它就無法辨識根因，先遮敏再保留最短必要片段。
- `flags` v1 只用 `project-bug`、`speculation`、`minor`、`duplicate-root`、`overdetailed`，依此順序去重。`flags` 僅作寫入端參考提示，不得 filter、block 或 auto-merge，審閱時亦不要求逐旗人類確認；沒有 flag 的直接觀察 one-off 仍是有效條目。
- provenance 欄位是待驗 claim，不是 permit；消費者必須用 `source_ref` 與 `feedback_quote` 對回原始 episode，不能讓 `signal_type` 自我授權。
- **推薦門檻看「修法實物＋當場查證」，不設「agent-only 預設推薦休眠」**：
  - **複合條目先拆再判**：單一摩擦若同時包含「客觀修錯」與「新增或加嚴規範文字／前置步驟」，先拆成兩個子動作各自套用下列門檻，不把整筆混在一起判。
  - **可推薦 `a. 折入`（不限來源標籤，仍必經使用者拍板才動手）**：修法是修正既有程式錯誤、更正錯誤訊息、把既有執行期阻擋補寫進文件、將既有下游必敗檢查前移至 preflight（fail-fast）、或把文件對齊已確認的現行契約，且審查者已當場重查附 `檔名:行號` 或原始錯誤輸出（公司 repo 一律以 `origin/main` 為準，不以過時本地 checkout 為準）。提案表須明標實際修改檔與是否命中 locked surface／須另簽 permit；若修法會推翻刻意寫的防禦（timeout／retry／拒收），推薦前必附該行歷史來歷；若文件承載人類決策而非單純描述過時，標「方向待確認」、不盲目照程式碼改寫。
  - **須人類來源訊號才可推薦 `a. 折入`**：修法會新增或加嚴給模型讀的規範文字（CLAUDE.md／SKILL.md／command 條文），或新增 hook／gate／政策性拒收行為／永久前置步驟。這類提案若只有 `agent-observation`、沒有 `user-correction`、**人類**領域專家 `expert-feedback`（AI 顧問輸出如 GPT Pro／Fable／Codex 一律標 `agent-observation`，不得標 `expert-feedback`）、對應測試失敗或當場人類確認，不得把折入標成推薦（不准以「客觀缺陷」標籤替新增長期治理背書）。
  - **其餘已看過、依目前證據與成本不值得做的方案**：直接推薦 `b. 否決` 並寫理由，不掃進休眠。
  - **真實傷害分流（統一引用正本）**：評估任何新增規則或新 hook／gate 的摩擦提案前，一律先對照 `~/.claude/references/mechanism-iteration-materiality.md`（H1–H4 紅線與 N1–N4 放行條件）；僅命中 N1–N4 且未命中 H1–H4 者**不得標為推薦折入新規則或 hook**，但須於既有拍板批次中照列並附條目編號與理由（不新增額外停點）。
- 舊格式 `- YYYY-MM-DD <一句摩擦> <建議方向>` 保持合法；消費時標為 legacy，只在影響判斷時回查 session／git，不反向批量改舊資料。既有待折項不因本版補欄或重寫。

新條目完成判準：單行同時交代原因、影響、建議方向；敘事與 `why` 已改寫並通過上述最小化；`feedback_quote` 若存在已縮成必要的 sanitized excerpt；既有防線已正常運作、當下無任何擬議改動的「零提案觀察」不寫入摩擦檔；不因 flag、one-off 或 metadata 缺漏捨棄有效條目。

拍板後搬入「已折／已否決」時，在同一行補歸因紀錄：

```
- YYYY-MM-DD [proposal_source=<anchor:duplicate-2|trial-review:file-3|dormant-retriage|user>@<session-id>; user_decision=<approved|rejected|superseded>@<timestamp-or-message-id>; implementation=<commit|path:line|already-fixed:<ref>|retired:<ref>|duplicate-of:<ref>|N-A>] <原摩擦>
```

前導日期固定保留原摩擦的捕捉日，不得改寫成拍板日；拍板時間只記在 `user_decision`。90 天退場同樣以這個捕捉日計算。

`proposal_source` 記「哪個入口把項目送進具體提案」，不把單純提醒送達冒充因果；個人側 `approved` 在搬入已折段前必須有真實 implementation，`rejected` 固定為 `N-A`；條目在審閱前已由既有 commit／上游修好、目標機制已退役或與另一筆完全重複時，記 `user_decision=superseded@<ts>` 並在 `implementation` 註明 `already-fixed:<ref>`／`retired:<ref>`／`duplicate-of:<ref>`，避免誤記成 `rejected` 扭曲否決率或誤記成 `approved` 虛增折入數。結案動作不另寫句尾尾綴——落地位置由 implementation 欄承載（2026-08-17 拍板：舊格式的 `→ <結案動作>` 尾綴與 implementation 欄重複，改為對齊實務）。公司側 approved 先使用下一段的「已拍板待落地」格式。

## 落點（分散式）

- **有主摩擦**（屬於某個 skill / command / agent / hook）→ 該機制目錄下的 `friction-log.md`（固定檔名）。command / agent / hook 在 `~/.claude/` 下是平檔、沒有自己的目錄，一律用 `~/.claude/skills/<name>/friction-log.md`，該目錄不需要 `SKILL.md`。有主摩擦不得落在 `~/.claude/friction/`
- **無主摩擦**（工作流級、跨機制）→ `~/.claude/friction/workflow-general.md`
- **文件與程式碼不一致**（agent 回報某個 repo 的文件跟現有程式碼對不上）→ `~/.claude/friction/doc-drift.md`，由 `/self-closeout` 第 0b 步寫入；無進行中上游 PR 計畫的第三方上游作者文件落差與已結案未追蹤 `.scratch/` 歷史票免記，fork 條目先跑 `git blame` 確認作者歸屬。折入優先把文件改對，實查錯在測試／帳本／常數時可在個人 repo 直接修復或轉路由，詳見該檔開頭
- 新建或首次接入本協議的檔案固定使用 `## 待折`、`## 休眠` 與 `## 已折／已否決` 三段；既有檔案若仍用 `## 已折 / 已否決` 或缺標準標題，先執行 `friction-review-state.py bootstrap --file <path>` 正規化，不另開第三個已折段。`## 休眠` 缺席時視為空，執行 dormant 搬遷時由 helper 自動補上標題
- 寫入新摩擦一律用 `Edit` 插入目標檔的 `## 待折` 段內；禁止用 `>>`、`cat >>` 或 `tee -a` 直接往檔尾追加（檔尾位於 `## 已折／已否決` 底下，追加到檔尾會讓新摩擦脫離 `## 待折` 掃描區而隱形）；結構異常由 `friction-review-state.py lint` 偵測並在 `TRIAL_REVIEW_QUERY_ONLY=1` 預檢中浮現
- 沒有 `## 待折` 的舊摩擦檔不計入待折門檻，但若含條目會由 `lint` 報出，應執行 `bootstrap` 補齊標準三段
- 折入後不刪原紀錄，逐筆完整搬到已折段並附日期、歸因紀錄與落點；分群只用於提案，不用短標識取代原文

## 三種狀態的排程語意

`## 待折` 同時容納「人類還沒看過」與「人類看過但決定現在不改」是本協議 2026-09-12 前的設計缺陷：後者已經完成審閱，卻因為計數不變而每天重新成為待決事項。三段各自的提醒資格固定為：

| 段 | 意義 | 計入提醒 |
|---|---|---|
| `## 待折` | 尚未提給人類看過，或已符合重開條件 | 計入（同一批內容不重複通知，見「通知水位」） |
| `## 休眠` | 人類看過並決定現在不改；沒有折入也沒有否決 | 不計入 |
| `## 已折／已否決` | 已完成處置，保存歸因紀錄 | 不計入 |

休眠沒有期限。一條線索永遠沒有再被處理，不等於必須永遠提醒它；要限制的是反覆消耗注意力，不是要求歷史清空。**休眠不是否決的委婉說法**——搬進休眠的項目不寫 `user_decision`，也不得在任何統計裡計為已處理或已折入。

搬入休眠時在原文同一行後面補一句重開條件，格式：

```
[dormant since=<YYYY-MM-DD>; wake-when=<一句話，什麼改變後值得再看>]
```

`wake-when` 只寫一句、不填表、不要求量化門檻。重開邊界固定為三條：新資訊必須對應原本保留的原因（等重現的項目要等到重現結果，光是過了一週不算）；同一件事換句話說、重排文字、更新時間戳不算新資訊；真實復發可以是新資訊，但不自動提升授權——多幾條 `agent-observation` 仍然只是 agent 提案。

寫不出 `wake-when` 的項目仍可休眠，填 `wake-when=需使用者主動重提`；不得只寫「值得重新看看」就當條件。純屬「等下次順手改某檔」且無觀測入口的低價值小修，直接推薦 `b. 否決` 不進休眠；綁定既有 trial 的休眠項應在該 trial 到期 review 時順帶檢視。**人類明確約定的延後是另一回事**：說「下週五再決定」就在那天提醒一次，不得把所有休眠自動解釋成「N 天後再問」並無限續約。若「保留」其實只是今天沒空讀，不得記成休眠，該留在待折。

**休眠不得掩蓋人類已明確要求完成的工作。** `signal_type=user-correction` 只是來源類型，不能單憑它判斷有沒有尚未履行的明確指令，要看原文——保存一個改善提案，和延後一個已承諾執行的要求，不是同一件事。

## 通知水位

已通知不等於已審閱，但已通知的同一批內容不需要每天再通知。白天提醒行的計數分母固定為「待折段中尚未通知過的個人側項目」，不是待折段的全部行數，也不是休眠庫存。晨間工廠與 `/trial-review` 的唯讀預檢、候選盤點和拍板批次則數待折段全部個人側項目（不含 `[pending_implementation ` 行，也不含 `target` 指向 `/Desktop/work/` 的公司側條目）：水位只負責提醒行不重複，不決定有沒有工作、也不決定哪些項目進批次，否則白天顯示過提醒的項目會永遠進不了拍板。

水位標記跟著項目走、不跟著檔案走——用整份檔案的修改時間或全文 hash 會讓「整理格式、搬動歷史段落」也觸發重複提醒。已通知但未處理的項目仍留在待折段，人類進批次流程時照樣看得到，不因通知送過就當成已完成。

## 消費門檻

兩個條件都只把項目送進提案，不等於已消費或已折入：

- **單檔待折 ≥3 項**（機械條件）→ 摩擦待折掃描在 projects 根目錄 session 的第一個合格 prompt 彙總過門檻檔案，導向 `/trial-review` 逐檔處理
- **同類摩擦第 2 次出現**（語意條件、掃描不實作）→ 錨點 append 當下自行判斷；同類就當場提出，不等 `/trial-review`

具體提案後仍須使用者拍板；approved 完成來源修改與驗證後才算折入，rejected 算已處理但不算折入。

公司側 approved 但尚未落地時，原項目留在待折段並直接補狀態尾碼：

```
[pending_implementation proposal_source=<...>; user_decision=approved@<...>; implementation=N-A（等待公司側落地）]
```

摩擦待折掃描與全域 `/trial-review` 在「過門檻」計數與待審批次中，一併排除含 `[pending_implementation ` 的行、公司側摩擦檔（如 `acme/docs/owner/harness-friction.md`）與 `target` 指向 `/Desktop/work/` 的未審公司側條目（白天一般提醒不再逐日顯示；`TRIAL_REVIEW_QUERY_ONLY=1` 唯讀預檢保留「已拍板待落地」清單供盤點，並於 `/trial-review` 全場收尾由 `friction-review-state.py company-summary` 彙整公司側待開 PR 與未審待決整體分布、上次處理時間與 `acme/` 啟動指令）。所有公司側未審條目、`[pending_implementation ` 項目與休眠項，統一由 `~/Desktop/work/acme/` 的專案 skill `acme-friction`（「來處理摩擦」）完整重審、按 repo 建 worktree 開 PR 並以 `friction-review-state.py` 結清帳本；拿到真實 commit／PR 後，移除 pending 標記、補 implementation，再搬到已折段。

## 多 session 摩擦時間鎖

真正處理一份摩擦檔前，在第一個 `## 待折` 標題下一行寫固定 24 小時 marker：

```markdown
<!-- friction-review-lock:v1 session=<CLAUDE_CODE_SESSION_ID> claimed_at=<UTC ISO-8601> expires_at=<UTC ISO-8601> -->
```

鎖的 owner 是整份檔案的待折與休眠批次。未到期由其他 session 跳過；已到期可精確替換接手；格式損壞或同段多 marker 時停止處理。實際解析與狀態轉換固定使用 `~/Desktop/projects/.claude/hooks/friction-review-state.py`，command 與測試不得各自重寫 parser。認領前先驗第一個精確 `## 待折` 與第一個已折段都存在（缺段時先用 `bootstrap` 正規化），避免結構錯誤後殘留鎖；取得鎖時以 `inspect --file <path> --snapshot <snapshot-path>` 寫出排除 marker 行後之第一個 `## 待折` 與 `## 休眠` 段落的 owner-only 原文快照（依 `harness-trust-binding/spec.md` 以原文相等性取代內容雜湊）。來源修改前與結案寫入前，各由 helper `validate --snapshot <snapshot-path>` 重驗完整 marker 格式、owner、期限與原文快照。結案寫入把同檔全部拍板項目（含待折段的 `approved`／`rejected`／`superseded`／`landed`／`company-pending`／`dormant`，與休眠段的 `close-dormant`／`wake-dormant`／`update-dormant`／`dormant-to-company-pending`）組成一個 operations JSON 陣列，由 helper 用同一次檔案寫入批次完成搬遷／狀態更新，最後才移除自己的 marker；不得逐筆呼叫 transform 或先改待折／休眠段再拿舊快照驗自己的改動。既有 pending implementation 取得落地證據後也要重新認領並通過相同 gate。任一外部變動就停止後續寫入；取消或保留待折時也在驗證後精確移除自己的 marker，marker 不得移入已折段。**全部保留待折、沒有任何搬遷操作時，仍走同一個 helper**：`transform --operations '[]' --release-lock` 只釋放鎖、不動待折內容（釋放後原文快照與認領時相同），owner、期限與快照驗證一律照跑；空 operations 若未帶 `--release-lock` 仍會被拒。不得手動編輯 marker 行繞過 helper。待折段累積多餘空行時，`tidy --release-lock` 走同一組 owner、期限與快照驗證，只把第一個待折段內的連續空行壓成一行，不動已折段、條目本身與段外內容；它必須帶 `--release-lock`、沒有保留鎖的變體——它改寫的正是快照涵蓋的那一段，留著鎖會讓 owner 手上的快照與檔案不符。搬遷本身已會帶走「刪除條目所產生的」那一個空行，所以 `tidy` 只用於清理既有累積，不是每次結案的例行步驟。

## 已折條目退場

`workflow-general.md` 與 `doc-drift.md` 的第一個 `## 已折／已否決`（或舊式 `## 已折 / 已否決`）段中，日期早於保留線的已折條目可以退場。以執行日 `D` 往前推 90 個日曆日得到保留線；條目日期必須嚴格早於 `D - 90 days` 才搬，剛好落在第 90 天的條目保留在主檔。條目日期取條目首行的完整 ISO 日期 `- YYYY-MM-DD`，不是用檔案修改時間或 epoch。

符合條件的條目按條目日期的季度分組追加至歸檔檔：`workflow-general.md` 寫入 `friction/archive/<YYYY-Qn>.md`，`doc-drift.md` 寫入 `friction/archive/doc-drift-<YYYY-Qn>.md`（避免與 `workflow-general.md` 混檔破壞統計分離）；既有季度檔只能追加，不得覆蓋原內容。主檔保留 `## 待折`、第 90 天與近 90 天的已折條目，以及該檔後面的其他內容。搬遷是保留資料，不刪 archive 檔、主檔或其他同層段。

段界只認下一個同層的 `## `；條目內的 `###`／`####` 與其內容要跟著條目一起搬，後面的同層 `## ` 不得被誤搬。

退場固定使用 `~/Desktop/projects/.claude/hooks/friction-review-state.py retire --older-than 90d`，重用既有 `inspect`／原文快照驗證、24 小時時間鎖與同檔批次寫入路徑；不得另寫 parser。其他 session 的未到期鎖直接跳過，不建立 archive，也不改來源。v1 只提醒並等待使用者拍板，不新增排程或 hook；首次真實存量整理另由一次性整理票處理。

## 折入規矩

- 提案會刪除或弱化既有規則時，先用「有害（照做會出錯）／未遵守（規則對但沒照做）／不適用（範圍過寬）」三個診斷角度核對並說明收益、成本與替代方案；三類只作診斷參考，不硬性禁止推薦刪除重複、過時或無可見增益的規則，也不強制將未遵守條目升成 hook／gate。最終增刪弱化均由使用者拍板。
- skill / command / agent 類改動 → invoke skill-creator，並走其內建 RED → GREEN → REFACTOR 行為驗證
- hook / gate 類改動 → invoke gate-authoring（命中 locked surface 時提案先明標須使用者另簽 permit）
- 單一產品 repo 寫碼習慣／重複踩坑 → 個人 repo 切進該 repo invoke `repo-guard`（優先架構／型別／指路型 lint，不預設塞進全域 hook 或文字規則）；公司 repo 仍照下方公司側條不代改，於待落地清單註明進該 repo 跑 `Skill(repo-guard)`
- rule 類 → 落 memory 或 CLAUDE.md（照 memory cluster 規則）
- 公司側 → 重查先核對 `origin/main`，只整理已拍板修改清單與驗收條件，不代改；approved 先留在待折段（休眠項核准時以 `dormant-to-company-pending` 搬至待折段），寫完整 `[pending_implementation ...]` 狀態，拿到真實 commit／path 證據後才搬段並計折入
- approved（個人側）：來源改動與驗證完成後，原項目連同歸因紀錄搬到第一個「已折／已否決」段
- rejected：不改來源，implementation=N-A，原項目連同歸因紀錄搬到第一個「已折／已否決」段
- superseded（已由既有 commit／上游修好、目標機制已退役或重複項）：不改來源，`user_decision=superseded@<ts>`，`implementation=already-fixed:<ref>|retired:<ref>|duplicate-of:<ref>`，原項目搬到第一個「已折／已否決」段
- 休眠：只用於真的在等具體條件（重現、上游 PR 時點）的項目；不改來源、不寫 `user_decision`，原項目全文搬到 `## 休眠` 段並補 `[dormant since=…; wake-when=…]`（沒有系統觀測入口時照實寫 `wake-when=需使用者主動重提`）
- 保留待折（僅限「今天沒空讀」）：原項目不搬，只釋放時間鎖

## 歷史比對

新項目進批次審閱時，在提出處置推薦**之前**按需查找相關歷史（主張復發、重開、已修、已批准待落地或先前否決時必查）；不新增常駐觀察者，也不要求寫入端在記錄前做全庫比對。

**檢索**：需要查歷史時，結構化線索（`target`、機制名、檔名）與原文線索（動作、失敗現象、錯誤字串）並用，避免漏掉早期無 metadata 的舊紀錄。`source_ref` 用來核對來源與辨識重複記錄，不當成新舊事件必須相同的搜尋條件。

**成本邊界**：本機文字搜尋可跨全部檔案的他檔待折段、休眠段與已折段（紀錄落在哪個檔是儲存位置，不是問題身分），只展開少量最相關候選的原文（第一輪最多 3 筆作起點）。候選受限或查不明時只寫「本次未找到」或「比對尚不完整」，**不得寫成「以前沒有發生過」**。

**命中後先排除同一事件被記兩次**：相同 `source_ref` 可能含同一段對話的不同事件，不同 `source_ref` 也可能是同一事件的轉述。要看來源與事件內容，不得靠欄位異同直接算復發次數。

確認是獨立事件後，依歷史處置分四種：

| 命中的歷史 | 先確認 | 對新項目的影響 |
|---|---|---|
| 休眠 | 是否對應原本的 `wake-when` | 條件成立才合併成同一議題的一列重開提案；只增加背景就不重開 |
| 確實折入過 | 新事件是否發生在修改生效之後、是否在原修改的適用範圍內 | 提高「查核原處置是否有效」的優先序——**不是提高「再加一道治理」的優先序** |
| 確實否決過 | 當年否決的是問題、某個方案，還是特定證據與成本條件下不做 | 只有否決理由被新資訊動搖才形成重考提案；同方案同條件不因再被記錄一次就重新請人否決 |
| 處置或理由不明 | 原文能支持到哪裡 | 只當相關背景。位於已折段本身不足以證明它真的折入過 |

**比對不產生授權**：命中一筆曾 approved 的歷史不會自動授權新增規範類條目。要引用舊的人類要求、專家意見或測試當本次佐證，必須指出它確實涵蓋本次問題與範圍。

**呈現**：只在有會影響本次判斷的歷史命中時，於拍板表「歷史對照」欄交代「對照哪一筆、當時怎麼處理、這次新增什麼、為何重開／提高查核／維持原決定」；不強制每群輸出固定長串查詢欄位。休眠項被重新帶入時與新項目合併成同一議題的一列，不讓人拍兩次。**比對命中本身不得寫成新的摩擦紀錄**。

### 歷史比對的四種失敗（每次比對前讀一次）

1. **用自己的歷史紀錄替自己的新提案背書。** 每個會影響處置的命中，都要說清楚獨立事件、相同適用範圍、時間先後、原決策理由與本次差異；證據只到哪裡，結論就停在哪裡。
2. **舊資料找不到，卻被說成沒有歷史。** 早期措辭、機制改名、候選限制都會漏檢，「未命中」不證明是首次發生。
3. **找到一個舊決定，就忽略後來的處置。** 命中互相衝突時要看處置範圍與後續關聯，查不明就標不確定。
4. **把重播成本換成無止境的歷史調查。** 歷史比對負責找出足以影響這次決策的已存證據，不是每筆的固定深挖程序。

**覆蓋邊界**：本機制只保證「新事件或新證據被記錄並進入批次審閱時，相關歷史會受檢查」。對沒有任何可觀測入口的 `wake-when`，照實寫 `wake-when=需使用者主動重提`，不得聲稱系統正在等它。

## Sweep 掃描範圍口徑

- 個人側 glob：`~/.claude/skills/*/friction-log.md`、`~/.claude/friction/*.md`
- 個人側具名檔：落在上述 glob 之外、但仍走本協議的檔案，維護於 `trial-review.sh` 的 `PRIVATE_FRICTION_FILES`。目前只有 `~/.claude/pr-review/friction.md`——它被 `.gitignore` 單獨排除（條目含公司 repo 名與 PR 編號），**不得搬進 `skills/` 樹**，否則那些內容會進個人 config repo
- 公司側：不納入全域 `trial-review.sh` 待折門檻；統一由 `friction-review-state.py company-summary` 彙整（涵蓋 `doc-drift.md` 中 `[pending_implementation ` 與 `target` 指向 `/Desktop/work/` 的條目、公司休眠項，以及 `acme/docs/owner/harness-friction.md`），並由 `~/Desktop/work/acme/.claude/skills/acme-friction/` 負責重審與結清

## 治理現況

`/trial-review` 是過門檻摩擦的統一批次消費入口；同類第 2 次仍可在錨點當場提案。本協議原 trial 已於 2026-09-06 結案畢業為常設機制（KEEP），entry 見 trials/archived.md `friction-loop-protocol`，不在 active.md。（原「一個月單一入口折入為零即刪整套協議」條款已於 2026-11-19 移除：單一入口零折入不代表擋下無效提案沒有價值。）
