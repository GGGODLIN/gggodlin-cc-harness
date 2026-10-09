---
name: gate-authoring
description: Use when 使用者要「寫 / 改 / 加一個 hook」「設計 gate / detector / tripwire」「動 settings.json hooks 段」——涵蓋全域 ~/.claude/hooks/、任一 repo 專案級 .claude/hooks/、任何 settings.json / settings.local.json 的 hooks 註冊，以及自動化 loop 控制面設計。Do not use for：一般 settings 權限 / env var 調整（update-config）、trial 到期 review（trial-review）、既有 hook 行為 debug（systematic-debugging）。
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/gate-authoring/scripts/tests/readable-time-fixtures.test.sh -->

# Gate Authoring

設計 gate 的失效模式不是「規則寫錯」，是「沒盤過 agent 會怎麼繞、改動會不會誤殺」。本 skill 是設計期 checklist；觀察期判讀（KPI / 停滯警報）在 memory `_index_hook_experiment_discipline`，enforce 設計案例（mutation tool 四類 gap）在 `feedback_mutation_tool_safety_design`。

## Checklist（設計 / 修改 gate 時逐項過）

### 0. 先寫 threat model，再寫規則

第一段先寫這支 gate 對誰有效、對誰明文不保證，因為它決定後面每一條規則要做多細：

- **防漂移**（誠實但健忘的 agent 順手改了不該改的）→ 攔到常見入口就夠，不必窮盡語法
- **防主動規避**（agent 刻意繞）→ 只有 agent 結構上做不到的事才算數（需要人在場的憑證、事前外部 permit）；字串比對一律不算

字串比對型 gate（掃 Bash command、掃 prompt、掃檔名）另外明寫一句「不承諾完整語意，只認常見入口，認不出來就 fail closed」，並在腳本檔頭留下同一句。同一句旁再寫一條不承諾：字串比對型 gate 會攔到「談論該指令的文字」而不只「執行該指令」——heredoc 內文、測試 payload、文件段落含該指令字樣都會中；deny 訊息要指出替代路徑（內容改走 Write／Edit 落檔再執行），不然使用者只看到被擋、不知道怎麼過（2026-08-22 實例：往 friction-log append 含提交指令字樣的 heredoc 被 agent-contract-gate 自己攔下，改走 Edit 才寫得進去）。沒寫這句的下場是把 gate 當 parser 養：heredoc、跳脫字元、控制結構、worktree cwd scope 一輪一輪修，每輪都覺得再補一次就完整了。

用 permit（事前核可）放行的 gate，threat model 多寫兩句不承諾：**核可是同意執行，不是證明指令真的在驗它標題說的事**；**核可不遞移到指令呼叫的 script／fixture／依賴**——指令文字沒變、被呼叫的檔換了，舊核可照放，要防就把被呼叫檔的 hash 也綁進 permit（2026-08-25 自 Leonxlnx/unlazy SECURITY.md 吸收）。

threat model 寫在文件最後當免責聲明沒有用——它的作用是在動工前把規則的細度框住，事後才寫等於整輪都在無界線的狀態下寫規則。

### 1. Surface 四分表

動工前把系統每個面標成四類、寫進設計說明（一張小表即可）：

| 類別 | 定義 | 例 |
|---|---|---|
| Locked | agent 讀得到、碰不得 | 評分規則、rubric、gate 腳本自身 |
| Editable | agent 可改 | 草稿、待審提案 |
| Append-only | 只能追加 | ledger、audit log、trials/active.md |
| Human-controlled | 只有使用者能動 | merge、放行、規則變更核准 |

沒標 = 邊界靠默契，漏洞從沒人想過的面進來。

**每個 Locked 面再答三條自身路徑**，缺一就是把系統鎖到沒有出口：

| 路徑 | 要回答的事 |
|---|---|
| bootstrap | gate 還沒生效時，第一次把它裝上去的那一次改動走哪條路 |
| update | gate 已生效後，改它自身、改它的 helper、改它的測試各走哪條路 |
| recovery | gate 誤攔時使用者手上有什麼開關（停用 sentinel、旗標、完全繞開本系統的外部路徑） |

三條都要留得下稽核痕跡（log 或 commit），不能只存在於作者腦裡。**最容易漏的是把「保護強度」直接加到擋住自己更新的位置**：locked 檔一有改動就 deny，看起來嚴謹，實際是連自己都裝不上去，還會連帶擋掉無關改動。真的需要那種強度時，配套的放行路徑要同批設計，不是之後再補。

### 2. 禁 self-scored gate 修改

同一個 agent 不得「提議修改評分規則」又「用改過的規則替自己的提案打分」——這是自動化系統最典型的自肥漏洞。規則變更與依規則打分必須分屬不同 agent 或隔一道 human 拍板。

### 3. Gate 改動配四件 fixture 回歸

改 gate 類 hook（description-gate / T2-routing-gate 這型）時，備四件測資跑過再收工：

- **known-good**：該放行的案例（防改嚴誤殺）
- **known-bad**：該攔的案例（防改鬆放行）
- **邊界案例**：最接近線的一件（鎖住線的位置）
- **自身生命週期**：第 1 條的 bootstrap / update / recovery 三條路徑各跑一件——把 gate 自己、它的 helper、它的測試檔當成待處理的內容送進去，確認走得通。前三件驗的是「輸入分類對不對」，這件驗的是「這支 gate 裝得上去、改得動、關得掉」，兩者抓的是不同類的死法

四件可存 hook 旁的 `*.test.sh` 或 fixture 檔常駐，下次改動重跑。完成判準：四件都實跑過且結果符合預期，不是「看起來沒問題」。

會寫檔的 gate 再加兩件**必測**（2026-08-25 自 Leonxlnx/unlazy tests 吸收）：

- **旁路未受影響**：不只斷言目標被改，還逐字斷言不該碰的檔沒被碰（CLAUDE.md「批次改檔必 assert」在 hook 層的對應）
- **log／state 目標病態**：把 audit log 或 state 檔換成 symlink、hard link、FIFO 各跑一件，斷言「拒寫、沒寫到別處、沒卡住」——FIFO 沒人讀會讓 Stop hook 永久 block，等於整個 session 卡死

按 hook 性質挑用的三件＋一條寫法：**正反配對**（同一件同時驗「該重置的重置了」與「不該重置的沒重置」，單向 fixture 抓不到 metadata 假進度）；回合邊界 gate 寫 matcher 前，先枚舉真實 transcript 的 `origin／turnOrigin／promptSource` 欄位；fixture 要成對證明 human／sdk 該 reset，而 task-notification／peer／tool result／meta 不該 reset，未知 origin 依 gate 型別 fail closed。**read-only 宣稱反證**（宣稱唯讀的 command 斷言它印出來了**且**沒動到目標）；**控制字元／雙向文字注入**（會把外部文字塞進 block 訊息的 hook，餵含終端控制碼與 bidi override 的輸入）；**反向斷言**——修掉一個 gate bug 後加一條「斷言舊寫法不再出現」的檢查並註明哪一版踩過，把「踩過的坑」從散文變成會紅的測試。

**fixture 之外再做一次真實環境 known-bad 實測**：安全型 gate 上線前，在使用者真實機器、真實 repo 上跑一個「應該 DENY」的情境並親眼看到 DENY。fixture 自訂 config root／repo，永遠測不到由環境變數決定的 root 與 scope——`CLAUDE_CONFIG_DIR` 指向 symlink farm、worktree、多 config dir 都會讓套件全綠而實際失效（2026-08-22 實例：33/33 綠，掛上後 8 個應 DENY 情境全 ALLOW，因 `canonical_dir` 停在 `~/.claude-max` 外層、repo 被判外來、locked-surface 檢查靜默跳過）。綠燈只證明邏輯自洽，不證明它在這台機器上有作用。

fixture 內含 epoch／Unix timestamp 時，不要裸寫手算常數：優先從含完整時間與時區的 ISO-8601 字串由測試語言轉換；若必須保留數字常數，常數旁保留等價 ISO-8601，並驗兩者一致。macOS shell 不要只用 `date -j -f "%Y-%m-%d"` 轉換，因為它會繼承執行當下的時分秒，讓測資隨執行時間漂移。

### 4. 新 gate 先列繞行場景表

上線前列一張「agent 會怎麼繞過它」的場景表（3-5 條），每條寫預期攔截點。找不到繞法 ≠ 沒有繞法，但沒列過 = 沒找過。經典繞行形狀：

- 提案修改「用來核准它自己」的規則（見第 2 條）
- 滿足字面格式、不滿足意圖（塞 token 過 gate 但內容空洞）
- 走 gate 沒覆蓋的旁路（另一個 tool / 另一層級的同功能路徑）
- 讓數字自報而非由 validator 重算（判分數學必須確定性重算、不信 LLM 自報）
- **授權由受檢對象自己證明**——從待執行的 prompt 反解析出授權欄位再自我重算、commit message 自帶核准字樣、輸入裡的固定 marker 當放行憑證。這類形狀都是自洽的：被檢查的東西同時是核准來源，agent 只要照抄格式就過。授權必須來自事前建立、gate 外部保管、綁定當次內容（session、內容 hash、單次消耗）的 permit；輸入裡的 marker 只能是那張 permit 的參照，不是 permit 本身。三項綁定缺一就是跨 session 授權外洩，而漏掉的那項在單 session 測試裡不會現形——2026-08-22 實例：permit 只綁 index tree＋到期＋單次消耗，使用者為 A session 簽的 permit 在 19 秒後被併發的 B session 領走放行（audit log issue 08:13:05 → allow 08:13:24），A 的四個檔被掃進 B 的提交。簽發時記下 session id、gate 從 hook payload 的 session_id 比對、不符即拒，fixture 配一件「另一個 session 拿同一張 permit」。permit 放行的是**指令**時，綁定再加一軸執行環境——resolved cwd、shell、PATH、platform——同一條指令換目錄跑或 PATH 指到另一個 binary 就是另一件事，環境變即失效（2026-08-25 自 Leonxlnx/unlazy gate-check 吸收；本機 dcg allow-once 綁指令全文＋單次消耗、未綁環境軸，新寫 permit 型 gate 時補上）
- **判定用的 helper 掛掉時整支 gate 放行**——import 失敗、檔案不存在、逾時、非 0 退出、吐出非法 JSON，任一格寫成靜默 return 就等於「想繞過只要弄壞 helper」

每個「判不出來」的分支都要選邊倒，方向由 gate 的型別決定、不是逐格憑感覺：

| gate 型別 | 判不出來時 | 例 |
|---|---|---|
| 安全型（擋的是不該發生的事） | 一律 deny | 授權判定、locked surface、破壞性指令 |
| 提示型（只是提醒或補脈絡） | 可以放行 | nudge、reminder、統計 |

抄別支 gate 的錯誤處理前先確認型別對得上。把提示型 gate 的靜默 `exit 0` 抄進安全型 gate 是常見死法：平常看不出差別，helper 一掛整道鎖就開了，而且沒有任何輸出會提醒你。安全型 gate 的每個錯誤分支都要有對應 fixture（第 3 條的第四件涵蓋自身生命週期，錯誤分支另外算）。

### 5. Stop gate 的放行條件綁狀態、不綁次數

會 `block` 的 Stop gate 必須有機制側放行，否則 session 卡死；但放行條件不能是「擋了 N 次」——agent 真在推進也會被放掉，改個註解假裝有動也算一次。放行綁**受檢狀態的指紋**（例：還沒拿到收據的 skill 集合、還沒 VERIFIED 的 gate 集合），指紋連續 N 次未變才算真卡死；指紋不得含行號、時間戳、路徑 hash 這類會隨無關改動漂移的欄位。指紋之外保留一道無條件 total 上限當保險，內部錯誤一律放行。

加自動放行前先認清代價：安全型 Stop gate（擋的是「該做的事沒做」如 TDD、或完整性失敗如 marker 被竄改）一旦有 total 上限，就等於「連續停 N 次就能繞過」，型別從安全型降成提示型偏安全——要降就明寫在 gate 檔頭，不要默默降。不降的替代：指紋計數只用來在連擋時升級 block 訊息、明寫走正路與人控兩條出口。歷史實例：`skill-eval-receipt-gate.sh` 曾採 same>3／total>6 兩層放行（2026-09-21 連同 SkillEvaluator Stop gate 一起拆除，改為 local-analysis 每日 `skill-changes` channel 純回報）；`matt-tdd-gate.sh` 2026-08-25 同樣降型（使用者拍板 1.b，理由：怕卡死的成本高於被繞的成本），2026-09-06 再降為純提示型（Stop 只出 systemMessage、不 block，loop guard 轉為提醒上限；依據＝12 天 4 次 BLOCKED 零真陽性）。（2026-08-25 自 Leonxlnx/unlazy stop-hook 吸收）

### 6. 驗收 oracle 與綠燈保鮮期

gate 或驗收項若靠跑指令判 PASS：成功條件必須是 **exit 0 且輸出含一個只有全過才會印的專用 token** 兩者同時成立——非零退出但錯誤訊息碰巧含 token 不算過；token 不能是 `ok`／`done`／`passed` 這種失敗輸出也會出現的字。指令本身是 `echo ok`／`true`／`exit 0` 這類固定輸出＝不可能失敗的 oracle，寫的時候就要抓掉。

「已通過」的記錄要標它綁的輸入（指令、被驗檔案 hash、環境）；綁的輸入變了，記錄自動降級成「待重驗」而不是繼續顯示綠——CLAUDE.md「上一輪是綠的 ≠ 現在是綠的」在 gate 設計上的落點。（兩段 2026-08-25 自 Leonxlnx/unlazy gates.md／hardening-tests 吸收）

### 7. Hook 輸出擺位（順手做對）

注入內容裡的動態值（日期 / 計數 / session id）放輸出尾端、穩定文字在前（prompt cache 判準，詳見 workflow-hardening §10 與 memory `feedback_instruction_altitude_and_prefix_cache_placement`）。完成後接第 8 段的四條指針，命中哪條就在動工前讀那段。

### 8. 型別、guard 判準與歸因（指針，2026-09-29 自 wiki `cc-hook-mechanism-deep-dive-2026` 提煉）

每條都是「如果 X，就在 Y 前讀 Z」；規則本身留在 wiki，這裡只放足以決定要不要去讀的一句：

- 如果 hook 掛在 Stop event 或需要乾淨的 `additionalContext` channel，就在選 `type:prompt` 前讀 wiki §4：`type:prompt` 沒有 fire-time gate、Stop 上 100% fire 且把 prompt＋回應原文塞進 user message，production 只能用 `type:command` 配 shell early-exit。
- 如果 hook 要叫模型判斷，就在選模型與部署前讀 wiki §7 與 §9：Opus 準但 `claude -p` 撞 41K cache_creation（100 turn $3）、regex 篩流量也救不回成本；可行組合是 `type:command`＋本機或第三方免費 API＋cascade cooldown。
- 如果 hook 屬 security／policy／guard 類（擋安裝、擋 mutation、攔 secret），就在寫規則前用 wiki §15 三判準過一遍：fail-closed（自己出錯預設擋）、self-protection（AI 不能改 guard 自身檔）、AI 不可自授權（放行依據不能只是 AI 塞的欄位）；上線前配 labeled corpus 迴歸，不靠 assert。
- 如果在 trial review 寫「deny rate 由高降到 0」，就在下歸因前讀 wiki §16：hook 是 runtime guard、audit baseline 與保險絲，不是 LLM trainer；「教育成功」「已內化」是紅旗措辭，要量的是「擋下後當 turn 是否真補對」。

## 收尾接線

- 新 gate 屬 trial → 照 CLAUDE.md Trial 紀律登 `~/Desktop/projects/.claude/trials/active.md`（+7 天 review）；保留 `## <name> (YYYY-MM-DD)` H2，H2 下只填 `started`／`status`／`detail`，長段另存 `trials/active/<slug>-<started>.md`，缺 detail 時停止並回報
- 觀察期 KPI 設計 → 讀 memory `_index_hook_experiment_discipline`（含 trivial-diff 停滯警報條）
- 摩擦盤點：本次設計／修改過程有無預見或撞到的摩擦 → append 所屬機制的 `friction-log.md`，無主的落 `~/.claude/friction/workflow-general.md`（格式與門檻見 `~/.claude/friction/PROTOCOL.md`）；無摩擦不留紀錄
- 帳本盤點：本次 authoring 有無引入會被 append、供未來 agent 讀的檔案或目錄 → 登記 registry 或標明純 log；無則不留紀錄
- Codex 已於 2026-09-20 停用：新掛或改 matcher 的 hook 不進 `~/.codex/hooks/cc-hooks.json`，也不補 Codex 端測試

## 踩過的坑

- **設計「hook 叫模型」前先 `grep -l '8317\|urllib' ~/.claude/hooks/` 抄既有接法，有 audit log 先讀數字再派實測**（2026-08-26，C068 LLM judge 派 agent 用 `agy` CLI 做 bake-off、量到 8 s 延遲才發現 `memory-ripple-runtime.py` 早已直呼 relay `127.0.0.1:8317`、runtime audit 有 955 筆真實延遲）。
- **secure_dir 逐段 `O_NOFOLLOW` 開目錄會把含 symlink 段的路徑（`/tmp`、`/var`）判 unsafe_directory，且 audit_result 靜默吞錯；jq 讀多行 JSONL 取 `.[0]` 必加 `-s`**（2026-08-29，memory-ripple 換 groq-qwen 時撞到：用 /tmp 路徑 debug 假陰性耗掉兩輪；不加 `-s` 是對 object 做 indexing、靜默 exit 5）。
- **陰性路徑測過 ≠ 測過：hook 的 smoke test 必須跑「會觸發」那條分支**（2026-08-01，額度守護三支改帳號解析時撞到）。改完 `session-limit-nudge.sh` 先跑一次真實環境，exit 0 靜默通過、看起來乾淨——但那只證明它在「未達門檻、提早 return」的路徑上沒事。強制把門檻壓到 0 逼它走完整條，才炸出 `line 37: email: unbound variable`：我抽掉帳號解析時漏了下游還在引用 `$email`。**這個 bug 潛伏在門檻檢查之後，也就是這個 hook 唯一有意義的那一刻**——不強制觸發就永遠測不到，會一路帶到真的撞額度那天才爆。判準：hook 的每個 early-exit 之後若還有程式碼，就得用環境變數/參數強制走到底測一次；同理適用 debounce marker、`pgrep` 短路等所有提早返回的守衛。第 3 條的 known-bad fixture 指的就是這條，別只備 known-good。
- **epoch 手算常數會讓考卷反咬實作**（2026-08-06）：fixture 把 2026 手打成 2025，先浪費一輪除錯才發現錯的是測資；時間測資保留完整 ISO-8601 來源，數字只是可驗算的衍生值。
- **macOS sed 處理 byte-level pattern 必 `LC_ALL=C`，且淨化管線要配「產出非空」斷言**（2026-08-25，checkpoint-judge 剝控制字元／bidi 時撞到）：`sed $'s/\xe2\x80[\xaa-\xae]//g'` 在 UTF-8 locale 下報 `illegal byte sequence`、輸出空字串，整段注入文字被吃掉；fixture 全綠是因為 fixture HOME 裡本來就沒有那個 memory 檔、走的是 fallback 路徑。Stop hook 真觸發才現形。淨化＝在資料路上多一道會失敗的濾網，每加一道就補「濾後非空／長度不低於濾前的 90%」斷言，並讓 fixture 帶真檔而不是靠 fallback。
- **bash 3.2 變數插值緊貼全形字元必用 `${VAR}` 大括號**（2026-08-17，T1-warning-check firing 分支撞到）：`"$VAR（說明）"` 這種 `$VAR` 後直接接全形括號／句號的寫法，bash 3.2 會把多位元組字元併進變數名解析，`set -u` 下炸 unbound variable。此雷只在 firing 分支引爆——hook 上線以來從未真觸發所以一直潛伏，靠上面「強制觸發 firing 分支」條才抓到（那條規則的正面實證）。訊息組字串裡 `$VAR` 後緊貼任何非 ASCII 字元，一律寫 `${VAR}`。
- **LLM 判官 hook payload 必設 `temperature:0`，且判官換 model 時 fixture 基準必重驗**（2026-08-29，evidence-level 逐則 hook 復活撞到）：archive 版 payload 沒設 temperature，known-bad fixture 連打三發 false/false/true——回歸結果不可重現；補 temperature:0 釘住定性後，發現新判官（groq-qwen-3.8-27b）對舊判官（gemini-3.5-flash-low）的穩定 TP 案例 3/3 穩定漏判。兩層教訓：不設溫度 = fixture 回歸無意義；判官選型不可跨 model 移植（同任務同 rubric 也一樣），換判官 = fixture 基準重驗 + 不得為了變綠弱化 fixture。
