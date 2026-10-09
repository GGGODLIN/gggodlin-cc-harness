<!-- 本檔在契約測試底下：bash ~/Desktop/projects/.claude/hooks/trial-review-friction-consumption.test.sh && bash ~/Desktop/projects/.claude/hooks/friction-review-state.test.sh -->
<!-- 本檔在契約測試底下：python3 ~/.claude/scripts/friction-outcome-packet.test.py -->

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
- `flags` v1 只用 `project-bug`、`speculation`、`minor`、`duplicate-root`、`overdetailed`，依此順序去重。flag 只 annotation，不得 filter、block 或 auto-merge；沒有 flag 的直接觀察 one-off 仍是有效條目。
- provenance 欄位是待驗 claim，不是 permit；消費者必須用 `source_ref` 與 `feedback_quote` 對回原始 episode，不能讓 `signal_type` 自我授權。
- `agent-observation` 可被記錄，但權限是 proposal-only；沒有 `user-correction`、領域內 `expert-feedback`、對應行為的 `test-failure`，或 review 當下使用者明確確認時，不得獨立觸發折入推薦或來源修改。
- 舊格式 `- YYYY-MM-DD <一句摩擦> <建議方向>` 保持合法；消費時標為 legacy，只在 authority 影響推薦時回查 session／git，回查不到就保留待折或否決，不反向批量改舊資料。既有待折項不因本版補欄或重寫。

新條目完成判準：單行同時交代原因、影響、建議方向；敘事與 `why` 已改寫並通過上述最小化；`feedback_quote` 若存在已縮成必要的 sanitized excerpt；不因 flag、one-off 或 metadata 缺漏捨棄條目。

拍板後搬入「已折／已否決」時，在同一行補歸因紀錄：

```
- YYYY-MM-DD [proposal_source=<anchor:duplicate-2|trial-review:file-3|user>@<session-id>; user_decision=<approved|rejected>@<timestamp-or-message-id>; implementation=<commit|path:line|N-A>] <原摩擦>
```

前導日期固定保留原摩擦的捕捉日，不得改寫成拍板日；拍板時間只記在 `user_decision`。90 天退場同樣以這個捕捉日計算。

`proposal_source` 記「哪個入口把項目送進具體提案」，不把單純提醒送達冒充因果；個人側 approved 在搬入已折段前必須有真實 implementation，rejected 固定為 N-A。結案動作不另寫句尾尾綴——落地位置由 implementation 欄承載（2026-08-17 拍板：舊格式的 `→ <結案動作>` 尾綴與 implementation 欄重複，改為對齊實務）。公司側 approved 先使用下一段的「已拍板待落地」格式。

## 落點（分散式）

- **有主摩擦**（屬於某個 skill / command / agent / hook）→ 該機制目錄下的 `friction-log.md`（固定檔名）。command / agent / hook 在 `~/.claude/` 下是平檔、沒有自己的目錄，一律用 `~/.claude/skills/<name>/friction-log.md`，該目錄不需要 `SKILL.md`。有主摩擦不得落在 `~/.claude/friction/`
- **無主摩擦**（工作流級、跨機制）→ `~/.claude/friction/workflow-general.md`
- 新建或首次接入本協議的檔案固定使用 `## 待折`、`## 休眠` 與 `## 已折／已否決` 三段；既有檔案若仍用 `## 已折 / 已否決`，處理前先正規化標題，不另開第三個已折段。`## 休眠` 缺席時視為空，處理該檔前補上
- 沒有 `## 待折` 的舊摩擦檔不在掃描範圍；下次該機制 append 時先補固定段，再把新紀錄寫入待折
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

寫不出 `wake-when` 的項目仍可休眠，填 `wake-when=需使用者主動重提`；不得只寫「值得重新看看」就當條件。**人類明確約定的延後是另一回事**：說「下週五再決定」就在那天提醒一次，不得把所有休眠自動解釋成「N 天後再問」並無限續約。若「保留」其實只是今天沒空讀，不得記成休眠，該留在待折。

**休眠不得掩蓋人類已明確要求完成的工作。** `signal_type=user-correction` 只是來源類型，不能單憑它判斷有沒有尚未履行的明確指令，要看原文——保存一個改善提案，和延後一個已承諾執行的要求，不是同一件事。

## 通知水位

已通知不等於已審閱，但已通知的同一批內容不需要每天再通知。掃描計數的分母固定為「待折段中尚未通知過的項目」，不是待折段的全部行數，也不是休眠庫存。

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

摩擦待折掃描在「過門檻」計數中排除含 `[pending_implementation ` 的行，另以「已拍板待落地」清單提醒；`/trial-review` 讀這類項目只做落地證據追蹤，不重新要求拍板。拿到真實 commit／path 後，移除 pending 標記、補 implementation，再搬到已折段。

## 多 session 摩擦時間鎖

真正處理一份摩擦檔前，在第一個 `## 待折` 標題下一行寫固定 24 小時 marker：

```markdown
<!-- friction-review-lock:v1 session=<CLAUDE_CODE_SESSION_ID> claimed_at=<UTC ISO-8601> expires_at=<UTC ISO-8601> -->
```

鎖的 owner 是整份檔案的待折批次。未到期由其他 session 跳過；已到期可精確替換接手；格式損壞或同段多 marker 時停止處理。實際解析與狀態轉換固定使用 `~/Desktop/projects/.claude/hooks/friction-review-state.py`，command 與測試不得各自重寫 parser。認領前先驗第一個精確 `## 待折` 與第一個已折段都存在，避免結構錯誤後殘留鎖；取得鎖時記下排除 marker 行後的第一個待折段 digest。來源修改前與結案寫入前，各由 helper 重驗完整 marker 格式、owner、期限與原 digest。結案寫入把同檔全部拍板項目組成一個 operations JSON 陣列，由 helper 用同一次檔案寫入批次完成搬遷／狀態更新，最後才移除自己的 marker；不得逐筆呼叫 transform 或先改待折段再拿舊 digest 驗自己的改動。既有 pending implementation 取得落地證據後也要重新認領並通過相同 gate。任一外部變動就停止後續寫入；取消或保留待折時也在驗證後精確移除自己的 marker，marker 不得移入已折段。**全部保留待折、沒有任何搬遷操作時，仍走同一個 helper**：`transform --operations '[]' --release-lock` 只釋放鎖、不動待折內容（釋放後 digest 與認領時相同），owner、期限與 digest 驗證一律照跑；空 operations 若未帶 `--release-lock` 仍會被拒。不得手動編輯 marker 行繞過 helper。待折段累積多餘空行時，`tidy --release-lock` 走同一組 owner、期限與 digest 驗證，只把第一個待折段內的連續空行壓成一行，不動已折段、條目本身與段外內容；它必須帶 `--release-lock`、沒有保留鎖的變體——它改寫的正是 digest 涵蓋的那一段，留著鎖會讓 owner 手上的 digest 與檔案不符。搬遷本身已會帶走「刪除條目所產生的」那一個空行，所以 `tidy` 只用於清理既有累積，不是每次結案的例行步驟。

## 已折條目退場

`workflow-general.md` 的第一個 `## 已折／已否決`（或舊式 `## 已折 / 已否決`）段中，日期早於保留線的已折條目可以退場。以執行日 `D` 往前推 90 個日曆日得到保留線；條目日期必須嚴格早於 `D - 90 days` 才搬，剛好落在第 90 天的條目保留在主檔。條目日期取條目首行的完整 ISO 日期 `- YYYY-MM-DD`，不是用檔案修改時間或 epoch。

符合條件的條目按條目日期的季度分組，追加到 `friction/archive/<YYYY-Qn>.md`；既有季度檔只能追加，不得覆蓋原內容。主檔保留 `## 待折`、第 90 天與近 90 天的已折條目，以及該檔後面的其他內容。搬遷是保留資料，不刪 archive 檔、主檔或其他同層段。

段界只認下一個同層的 `## `；條目內的 `###`／`####` 與其內容要跟著條目一起搬，後面的同層 `## ` 不得被誤搬。

退場固定使用 `~/Desktop/projects/.claude/hooks/friction-review-state.py retire --older-than 90d`，重用既有 `inspect`／digest 驗證、24 小時時間鎖與同檔批次寫入路徑；不得另寫 parser。其他 session 的未到期鎖直接跳過，不建立 archive，也不改來源。v1 只提醒並等待使用者拍板，不新增排程或 hook；首次真實存量整理另由一次性整理票處理。

## 折入規矩

- 提案會刪除或弱化既有規則時，歸因紀錄同一行先加 `rule_change_class=<harm|non-compliance|irrelevant>`——「規則有害」與「規則沒被遵守」在摩擦紀錄上長得一樣，不分類就會把後者當前者處理：
  - `harm`＝照這條做反而產生錯誤結果，附具體案例 → 才可刪除或弱化
  - `non-compliance`＝規則本身對、只是沒被遵守 → 只能強化措辭、改接線位置或升成 hook／gate
  - `irrelevant`＝該場景不適用 → 只縮適用範圍，不動規則主體

  缺這個欄位的刪除／弱化提案不成案，退回保留待折；使用者原話要求刪除時分類照寫，`harm` 以外的最終處置仍由使用者拍板。
- skill / command / agent 類改動 → invoke skill-creator，並走其內建 RED → GREEN → REFACTOR 行為驗證
- hook / gate 類改動 → invoke gate-authoring
- rule 類 → 落 memory 或 CLAUDE.md（照 memory cluster 規則）
- 公司側 → 只整理已拍板修改清單與驗收條件，不代改；approved 先留在待折段，寫完整 `[pending_implementation ...]` 狀態，拿到真實 commit／path 證據後才搬段並計折入
- approved（個人側）：來源改動與驗證完成後，原項目連同歸因紀錄搬到第一個「已折／已否決」段
- rejected：不改來源，implementation=N-A，原項目連同歸因紀錄搬到第一個「已折／已否決」段
- 休眠：不改來源、不寫 `user_decision`，原項目全文搬到 `## 休眠` 段並補 `[dormant since=…; wake-when=…]`
- 保留待折（僅限「今天沒空讀」）：原項目不搬，只釋放時間鎖

## 歷史比對

新項目進批次審閱時，由該批次的 agent 在提出處置推薦**之前**查找相關歷史；不新增常駐觀察者，也不要求寫入端在記錄前做全庫比對。流程順序固定為：讀本批新項目 → 初步分群 → 查找休眠與已處置歷史 → 核對候選 → 形成推薦 → 人類拍板。初步分群只是讓相近項目共用一次搜尋，不得在查歷史前就假定它們同根因。

**檢索**：兩條路徑並存，原文那條不得只在結構化沒命中時才跑——大量早期紀錄沒有 `target`／`signal_type` 欄位，只靠結構化搜尋會固定漏掉它們。

| 路徑 | 用什麼查 |
|---|---|
| 結構化 | `target`、機制名稱、檔案或介面識別 |
| 原文 | 新項目的 `feedback_quote`、`why` 描述的動作與失敗現象、錯誤字串 |

`source_ref` 用來核對來源與辨識重複記錄，不當成新舊事件必須相同的搜尋條件；`signal_type` 保留給授權判斷，不作語意關聯的硬篩選。

**成本邊界**：本機文字搜尋可跨全部檔案的休眠段與已折段（紀錄落在哪個檔是儲存位置，不是問題身分），但搜尋結果先只回位置與命中片段，模型只展開少量最相關的候選。每群第一輪最多展開三筆作為起點（這個數字未經量測，用過幾輪再校準）；同一筆舊紀錄被多群命中只讀一次。候選受限時結論只能寫「本次未找到」或「比對尚不完整」，**不得寫成「以前沒有發生過」**。

**命中後先排除同一事件被記兩次**：相同 `source_ref` 可能含同一段對話的不同事件，不同 `source_ref` 也可能是同一事件的轉述。要看來源與事件內容，不得靠欄位異同直接算復發次數。

確認是獨立事件後，依歷史處置分四種：

| 命中的歷史 | 先確認 | 對新項目的影響 |
|---|---|---|
| 休眠 | 是否對應原本的 `wake-when` | 條件成立才合併成同一議題的一列重開提案；只增加背景就不重開 |
| 確實折入過 | 新事件是否發生在修改生效之後、是否在原修改的適用範圍內 | 提高「查核原處置是否有效」的優先序——**不是提高「再加一道治理」的優先序** |
| 確實否決過 | 當年否決的是問題、某個方案，還是特定證據與成本條件下不做 | 只有否決理由被新資訊動搖才形成重考提案；同方案同條件不因再被記錄一次就重新請人否決 |
| 處置或理由不明 | 原文能支持到哪裡 | 只當相關背景。位於已折段本身不足以證明它真的折入過 |

**比對不產生授權**：新紀錄保留自己的 `signal_type`。命中一筆曾 approved 的歷史不會升級授權，多幾筆 `agent-observation` 也不會。要引用舊的人類要求、專家意見或測試當本次佐證，必須指出它確實涵蓋本次問題與範圍，不能只說「以前批准過」。

**呈現**：在既有拍板表加一個「歷史對照」欄，回答「對照哪一筆、當時怎麼處理、這次新增什麼、所以為什麼重開／提高查核／維持原決定」。找到五筆相似不等於多五列人類工作，只有會影響當次判斷的歷史才進表。休眠項被重新帶入時與新項目合併成同一議題的一列，不讓人拍兩次。**比對命中本身不得寫成新的摩擦紀錄**，否則比對機制會自己餵養下一次提醒。

### 歷史比對的四種失敗（每次比對前讀一次）

1. **用自己的歷史紀錄替自己的新提案背書。** 失敗鏈長這樣：新問題描述籠統 → 搜尋命中一筆舊紀錄 → 寫成「已確認反覆發生」→ 看到曾折入 → 寫成「現有治理失效」→ 據此提高修改優先級、繼續加治理。整串推論可能只有第一步「文字相似」是真的。防線不是再加一個 reviewer，是要求每個會影響處置的命中，說清楚獨立事件、相同適用範圍、時間先後、原決策理由與本次差異；證據只到哪裡，結論就停在哪裡。
2. **舊資料找不到，卻被說成沒有歷史。** 早期措辭、機制改名、紀錄過短、候選數量限制都會造成漏檢，所以「未命中」不提供「這是首次發生」的確定性。日後發現漏檢，針對實際漏掉的那次改查詢詞，不為了理論上可能漏掉任何東西就先建語意資料庫。
3. **找到一個舊決定，就忽略後來的處置。** 同一議題可能先否決某方案、後來批准另一方案。只取第一個相似命中，會拿過時的否決壓掉新問題，或拿過時的批准當現行方案。命中互相衝突時要看處置範圍與後續關聯，查不明就標不確定，不得任選最方便的一筆。
4. **把重播成本換成無止境的歷史調查。** 每個命中都追 git、補測試、重建完整時間軸，會讓新流程比舊流程更貴。歷史比對的職責是找出足以影響這次決策的已存證據，不是免費附贈根因調查；需要新增查證時說明缺什麼、值不值得查，不讓它變成每筆紀錄的固定前置程序。

**覆蓋邊界**：本機制只保證「新事件或新證據被記錄並進入批次審閱時，相關歷史會受檢查」。沒有被記錄、沒進批次的現實變化不在覆蓋內；對沒有任何可觀測入口的 `wake-when`，要明說需要人工重提，不得聲稱系統正在等它。

## Sweep 掃描範圍口徑

- 個人側 glob：`~/.claude/skills/*/friction-log.md`、`~/.claude/friction/*.md`
- 個人側具名檔：落在上述 glob 之外、但仍走本協議的檔案，維護於 `trial-review.sh` 的 `PRIVATE_FRICTION_FILES`。目前只有 `~/.claude/pr-review/friction.md`——它被 `.gitignore` 單獨排除（條目含公司 repo 名與 PR 編號），**不得搬進 `skills/` 樹**，否則那些內容會進個人 config repo
- 公司側：明文清單常數，維護於 `trial-review.sh` 事件制段檔內（新增檔案改那裡）

## Review 與退場

`/trial-review` 是過門檻摩擦的唯一批次消費入口；同類第 2 次仍可在錨點當場提案。Review 分開計：捕捉數、提案數、已處理數（approved + rejected）、實際折入數（approved + implementation）；其中 `proposal_source=trial-review:file-3` 才能證明摩擦待折掃描接上消費。

一個月內 `proposal_source=trial-review:file-3` 的實際折入為零 → 刪本檔＋trial-review.sh 摩擦段，各紀錄點退回各自為政。沒有適用樣本、提醒沒被承接或提案全被否決只作 verdict 解讀，不放寬既定退場條件。trial 已於 2026-09-06 結案畢業為常設機制（KEEP），entry 見 trials/archived.md `friction-loop-protocol`，不在 active.md。
