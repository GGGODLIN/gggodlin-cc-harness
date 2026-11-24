---
name: agent-dispatch
description: "如果 main 有已驗證的 Herdr 身分（HC_TERMINAL_ID，或 HERDR_PANE_ID 與 HERDR_WORKSPACE_ID 齊全）且需要另一個 agent session，尤其是不同模型的第二意見或 Codex／pi 外殼，就主動觸發 agent-dispatch；使用者不必點名 Herdr 或 agent-dispatch。也適用明說派 worker、用 agent-dispatch。小改、同模型搜尋或盤點不適用；subagent、workflow agent、受委派 worker 或沒有 Herdr 身分時不適用。"
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/agent-dispatch/scripts/tests/explicit-consent-contract.test.sh && bash ~/.claude/skills/agent-dispatch/scripts/tests/seat-dispatch-contract.test.sh -->

# Agent Dispatch

本 skill 是 main 開 Herdr session 的總入口，分實作 worker 與唯讀單席。實作 worker = 一個 repo 的一包票，從指定 worktree 啟動，外殼是 Claude Code（預設）、Codex CLI 或 pi；唯讀單席只回判斷，不開 worktree、不寫檔。啟動、等待、回報與關閉都沿用收據裡的 backend、外殼與 target identity。

## 選路與模式

1. 只有 main 能開 Herdr session；subagent、workflow agent、受委派 worker 都不開。如果受委派者需要另一席，就回報 main；workflow 內部席位依目錄列出的例外沿用原路。
2. 小改 main 自己做；同模型的搜尋或盤點用 subagent，不開 Herdr。如果 main 有已驗證的 Herdr 身分（`HC_TERMINAL_ID`，或 `HERDR_PANE_ID` 與 `HERDR_WORKSPACE_ID` 齊全）且需要另一個 agent session，尤其是不同模型或 Codex／pi 外殼，就主動走本入口，使用者不必點名 Herdr。
3. 如果要第二意見或委派任務，就不照貼顧問給的 headless 指令：不跑 `claude -p`、`codex exec` 或 launcher 加 `-p`，不以 subagent model override 取得跨模型意見，也不自寫啟動器；只有 `config/second-opinion-seats.json` 明列該用途與原因時才沿用例外。如果使用者在當輪明確點名要用 `claude -p`、`codex exec` 這類 headless 呼叫，就照做，並在同一則提醒它會繼承本 session 的模型映射、可能沒跑到要的模型；顧問建議、上一輪的指定或「用什麼都行」不算點名。尚未遷移的呼叫端既有路徑照舊（advisor 的原生 Fable Agent 與網頁 GPT Pro），不因本條改判不可用。如果要判斷是否屬例外或尚未遷移，就在啟動前讀 `references/session-routing.md`。
4. 如果沒有完整 Herdr 身分，就回報「該席目前不可用（無 Herdr 身分）」，不自行退回 headless（使用者當輪點名的照第 3 條）、不換模型、不自動拉起 Herdr server。如果身分存在但 backend 未運行或 target 不 live，也停止並回報。
5. 外部額度席未被使用者明確選定時不開；通道選路不授予選席權，呼叫端的選席停點照舊。如果席位目錄沒有該席或尚未啟用，就回報該席目前不可用，不退回 headless 或換模型。
6. 如果席位在目錄裡走新路（例如 `harness: "pi"` 的審查驗收席），就接「單席交接（新路）」；既有第二意見唯讀席接「唯讀單席」；如果是唯讀掃描 worker（例如狀態與併發三版核驗的單獨掃描），就接 Step 0 取得當次派工同意並在既有 repo 目錄啟動（不開 worktree）；要在 worktree 實作一包票同樣接 Step 0。唯讀單席不另問派工同意，實作 worker 與唯讀掃描 worker 仍需當次同意。

## 單席交接（新路）

1. **寫交代並開席**：依 `assets/seat-handoff-template.md` 分開寫任務、邊界、脈絡；使用者原話逐字貼並標明，main 的判讀另列；要求對方回覆的第一行只寫「做完了」或「卡住了：缺什麼」。執行 `python3 scripts/open-seat.py <seat-id> <brief-file> <cwd> --log-dir <目錄>`（只有使用者當次明講模型或 effort 時才加 `--model`／`--effort`，不得指定外殼）。如果開席失敗或 Herdr 沒在跑，就停下回報原因，不改走原生 subagent 或 pi-subtask、不換模型、不自動拉起 Herdr。
2. **核對首則送達並記三項識別**：開席成功回傳 JSON 後，記下 `terminal` 位址、`session_id` 與送出時的 `turn`（首則為 `1`）。只有 `first_message` 的 `sent` 與 `started` 都為 true 才算接到；任一不成立就用 `hc read <terminal>` 看畫面並回報狀態，不自動重送。
3. **掛有時限的背景等待並收件**：用背景 Bash 執行單席等待 `hc wait <terminal> --timeout 300 --json`（指名該席位址，讓 Stop 檢查辨認歸屬）。
   - 被叫醒後，跑 `python3 scripts/worker-turns.py --harness <harness> --session <session_id> --turn <turn>`（Claude Code 外殼另加 `--cwd <cwd>`）讀這一席這一輪的回覆全文。第一行寫「做完了」才算交件；第一行寫「卡住了：缺什麼」、空白、只有上一輪舊答案或讀檔失敗都算未交付並回報原因。
   - 等到逾時還沒消息時，用 `hc read <terminal>` 看畫面並回報未交付，不當成交件。
4. **追問、收起與叫回**：
   - 需要追問時送給同一席：`hc send --json <terminal> "[main] ..."`，把 `turn` 加 1 後重複第 3 步。
   - 讀完回件、確定不再追問就立刻收起：`hc kill <terminal>` 後接 `hc rm <terminal>`。要留席時寫明原因。
   - 收起後還需要原脈絡時，用開席指令帶原 `session_id` 叫回同一席並保留唯讀鎖與新路標記：`python3 scripts/open-seat.py <seat-id> <follow-up-brief> <cwd> --resume <session_id> --log-dir <目錄>`（依原 session 既有的對話輪次把 `turn` 加 1 後收件）。
- **不做**：不做通用回件格式驗證、不自動重試或重播、不掛每席外掛監看腳本、不要對方先回一句「接到了」的握手回覆、不做完整收據檢查；任務需要的格式寫在該次交代檔裡。
- **唯讀鎖變更後必重測**：目錄裡某一席第一次建立、或換了外殼／唯讀鎖之後，正式使用前必做一次「請它寫檔」實測，確認檔案沒出現。

做完的樣子：已記下 `terminal`、`session_id`、`turn`；回覆經 `worker-turns.py --turn` 確認本輪第一行「做完了」或已回報未交付原因；沒有追問的席已用 `hc kill`／`hc rm` 收起，留席者已寫明原因。此模式到此結束，不接實作 worker 的 Step 0–5。

## 唯讀單席

1. 依呼叫端的選席規則確認已選席位，再用 `python3 scripts/open-seat.py --list` 讀席位目錄；選單的額度來源照該席 `quota_source` 顯示，不複製模型或配方到呼叫端。
2. main 準備 brief 檔與收據目錄，在既有 repo 目錄開席，不建立 worktree：`python3 scripts/open-seat.py <seat-id> <brief-file> <cwd> --log-dir <收據目錄>`。指令把 brief 與 review-method 正文以 `[main]` 訊息送入，掛 watcher 後立即回 JSON；main 將輸出存成該席獨立的 `receipt.json`，不自行組 start-worker 步驟。
   - 如果 caller 另有限制，就在開席加 `--permission-mode zero-tools|codex-read-only|tool-allowlist`；白名單用重複 `--allow-tool <規則>`，Codex 續接用 `--resume <session-id>`，仍套用唯讀沙盒、不帶 bypass。
   - Codex 目錄席的 `launch` 寫成 `{"type":"codex","model":"GPT_ASTRA"}`，`model_sources` 存同一 key；開席讀 `config/gpt-models.env` 解析型號到收據，缺 key 或讀不到版本表就不建 terminal；收席比對 rollout 的 model、effort 與 read-only sandbox。
   - 零工具席的可用工具清單只能由啟動參數＋零工具使用判定；session 沒有可用工具清單時，不宣稱已從紀錄驗出清單為空。
3. 等 watcher 喚醒。如果只是 timeout check-in 且席位仍在工作，就回報仍在跑，不判失敗、不重送、不關席，除非使用者要求。Core watcher 的已知限制見 `references/session-routing.md`，不把喚醒當成完成證明。
4. 被喚醒後跑 `python3 scripts/finish-seat.py <receipt.json>`，由指令取完整答案、核對回合結束、方法組、實際模型與寫入工具呼叫，預設關閉該席 terminal，失敗也關（註：僅舊路收據走 `finish-seat.py`；目錄已標 `dispatch: "v2"` 的新路席位收據不含舊路 `seat` 欄，一律走上方「單席交接（新路）」的 `hc wait` ＋ `worker-turns.py --turn` 收件）。如果要轉達席位的反問或使用者要求保留，就加 `--keep-open`，下一次收席不帶此旗標再關。
5. 如果任一檢查失敗，就保留答案並標不可當該席意見（模型核對失敗另標模型未核對），不冒充該席意見；不自動重送、不換模型、不重跑其他成功席。寫入工具檢查不涵蓋 Bash／MCP 副作用；如果需要報告檔，就由 main 依回傳全文寫檔，席位不寫。

做完的樣子：每席各有收據，答案取自該 session 的完整末則文字；只在收席檢查通過時標成功，且只關該收據的 terminal；保留席寫明原因。此模式到此結束，不接實作 worker 的 Step 0–5。

## 為什麼是這個形狀

- subagent 拿不到 repo 的 hook 與 skill，`/cd` 與 handoff 會換位置；Claude Code worker 讓兩邊都生效，使用者也能直接走進 worker terminal 談。
- Codex 與 pi worker 是為了讓模型配上它表現較好的外殼。它們不套用 repo 的 Claude Code hook、skill 與 settings，所以驗收不靠 worker 內的治理，而靠 main 在 Step 4 核對 commit、測試、票與收據。
- 一包票一 worker，最後只由 main 對 worktree 做一次 review，避免每張票重複 review 與 mutation。
- worker 的 jsonl 裡 main 送的字與人打的字長得一樣，所以 main 送的每一則都加 `[main]` 前綴，對帳時才能分開。

## Step 0：取得當次派工同意

如果本次要啟動或續派實作 worker 或唯讀掃描 worker，就在建立 worktree、寫 brief 或操作 backend 前，讀 `~/.claude/rules/common/dispatch-and-verify.md`〈終端派工只由 main 管理〉。如果本次要派狀態與併發單獨掃描 worker，就在提出派工同意前讀 `~/.claude/references/state-machine-scan-brief-template.md`（在既有 repo 目錄啟動、不建立 worktree）。`HERDR_*`／`HC_TERMINAL_ID` 身分與 main 的 brief 都不能代替 main 的角色邊界。

一般實作授權不等於 agent-dispatch 派工授權。建立 worktree、寫 brief、建立收據目錄或啟動 worker 之前，先確認使用者是否已明確同意這一次派工。

使用者明說「派 worker」或「用 agent-dispatch」，且句子已指向本次任務時，視為當次同意；「可以實作」「照做」「繼續」或同意某份 plan，都不代表同意另開 worker。

如果要呈現派工資訊，就在寫訊息前讀 `references/harness-recommendations.md`：本次模型在表上有列，就附上推薦外殼、理由與證據強度，並照表標「未拍板」；表上沒有的模型不給推薦。使用者明確指定的外殼照辦，推薦表不擋。

如果尚未取得同意，用一段短訊息交代：

- 要派的任務與 repo
- main 不自己做的具體理由
- worker 數；外殼、配方與 backend 寫在同一則同意訊息。配方在 Claude Code 是 model＋effort 或 cc-pick 配方，在 Codex 是 model＋effort，在 pi 是 pi-pick 配方。寫定本次使用的一組：使用者沒指定外殼時寫 Claude Code；推薦表推薦別的外殼時另起一句標「未拍板」，不把推薦當成使用者選定
- 額外的 token／等待成本，以及 worktree 隔離方式

外殼是 Codex 或 pi 時，訊息裡寫明：這個 worker 不套用 repo 的 Claude Code hook、skill 與 settings，驗收靠 main 核對 commit、測試、票與收據。使用者已經明說要派這個外殼時，這句照樣寫進開工前的訊息，只是不必再等回覆。

只提供三個回覆方向：`允許這次派工`／`main 自己做`／`暫停`，然後停止。未回覆、拒絕或取消時不派工，也不反覆遊說。

同意只限當次具名的任務、repo、worker 數。如果任務或 repo 改變，或 worker 數增加，就在副作用前重新取得同意。先呈現上述派工資訊後，使用者回「照預設」才算同意，不能把其他語境的「照預設」沿用過來。

如果同意後只換配方，就告知新配方後繼續，不得重新詢問派工同意。如果同意後只換外殼，就告知新外殼後繼續，不得重新詢問派工同意。如果換到 Codex 或 pi，就在告知訊息附治理差異：worker 不套用 repo 的 Claude Code hook、skill 與 settings，驗收靠 main 核對 commit、測試、票與收據。

只告知的訊息形狀：

> 本次任務、repo 與 worker 數沿用已取得的同意；配方改為 `sonnet medium`，接著啟動。
>
> 本次任務、repo 與 worker 數沿用已取得的同意；外殼改為 pi，使用已具備的完整 pi-pick 配方。worker 不套用 repo 的 Claude Code hook、skill 與 settings，驗收靠 main 核對 commit、測試、票與收據；接著啟動。

取得同意後，一次收齊尚未明確的外殼與配方（沒指定外殼時是 Claude Code，配方 `opus[1m]` high）。如果 Codex 缺 effort 或 pi 缺完整 pi-pick 配方，就只問缺少的參數，不重問派工同意。backend 固定為 Herdr，不增加第二條 terminal backend 決策。

做完的樣子：transcript 裡找得到使用者對本次任務、repo、worker 數的明確派工同意；外殼、配方與 backend 已告知，如果後來只換外殼或配方，也已告知且未重問；外殼是 Codex 或 pi 時，初次訊息與後續外殼告知都含治理差異那句。未達成時停在 Step 0；達成後接 Backend routing 與 Step 1。

## Backend routing

`scripts/start-worker.sh` 只在 Herdr parent identity 完整時派工，不因 CLI 已安裝就猜 backend，支援與 `terminal-backend-routing.md` 一致的兩種等價形式：

- **新版 Herdr App / Core（`BACKEND=herdr-core`）**：parent 存在 `HC_TERMINAL_ID`（若 `hc serve` 從舊版 Herdr 內啟動而同時帶有兩套變數，內層 `HC_TERMINAL_ID` 優先；但若同時出現 `HERDR_PANE_ID`／`HERDR_WORKSPACE_ID` 其中之一而缺另一個仍會直接報錯）。script 會用 `hc get "$HC_TERMINAL_ID"` 驗證 `address` 相符且 `state == "live"`。
- **舊版 Herdr TUI（`BACKEND=herdr`）**：parent 同時有 `HERDR_PANE_ID` 與 `HERDR_WORKSPACE_ID`（只出現其中一個欄位就直接報錯）。script 會用 `herdr pane get "$HERDR_PANE_ID"` 驗證 parent target live 且 `workspace_id` 相符。
- 沒有完整 identity、target 不 live、或 CLI 回傳 `ok:false`，都在建立或注入前停止，也不向任意 active pane／terminal 發字。
- 指令或 watcher 回錯時，在重試前讀 `references/herdr-notes.md`。

做完的樣子：Herdr（`herdr` 或 `herdr-core`）parent identity 齊全且 live；沒有任何 Herdr 以外的第二 backend 選路或 fallback。

## Step 1：開工位

1. 依 context 裡的專案指示決定 base branch，用 `git -C <repo>` 從 main 所在目錄開 worktree；不 `cd`。若已指定既有 worktree，就不另建 worktree。
2. 複製 worktree 拿不到的 gitignored 檔（env、settings.local）。
3. 依 context 裡的專案指示決定票檔與規格複本放哪個 repo 目錄；沒有慣例就留在正本位置、brief 指路徑。
4. 建收據目錄，選一個不會被測試清空的位置。

做完的樣子：worktree 在正確 base 上、`git status` 只剩預期複本、收據目錄存在。

## Step 2：寫 brief、起 worker

1. 從 `assets/brief-template.md` 填 brief，寫成檔案放正本目錄。使用者原話逐字貼、標「以下為使用者原話」；main 自己的判讀另段標明。多行文字送進 terminal 會被拆成多次送出，所以 brief 一律走檔案。
2. 跑 `scripts/start-worker.sh <name> <worktree> <brief> [外殼與配方] [--agent <agent-name>] [--inline-brief] [--label L] [--log-dir D] [--no-watch]`，外殼與配方擇一：
   - Claude Code：不帶外殼參數，`--model M --effort E`（預設 `opus[1m]` high）或 `--recipe '<cc-pick 配方 JSON>'`。cc-pick 配方是 `main`／`fable`／`opus`／`sonnet`／`subagent` 五個槽位都到的字串物件，空字串代表原生。
   - Codex：`--harness codex --model <id> --effort <e>`，兩個都要給。
   - pi：`--harness pi --recipe '<pi-pick 配方 JSON>'`。形狀照 `pi-pick --last --dry-run` 輸出的 `recipe` 欄位。
   - launcher：`--launcher <name>` 讓新 terminal 直接打目錄列的 launcher（如 `ccp-gemini`），僅支援 Herdr App／Core，不能搭配 `--recipe` 或明確的 `--model`，也不補預設模型；`--agent`、session id 與明確給定的 `--effort` 原樣傳入。舊版 backend 拒絕 launcher；launcher 不存在時不建 terminal，並指名缺哪一個。
   `--agent <agent-name>` 僅適用 Claude Code，指定 agent 定義。`--agent` 搭配 `--recipe` 時，可再指定 `--model`／`--effort`：model 優先取明確參數，否則取配方的 `ANTHROPIC_MODEL`；兩者皆空就拒絕啟動；明確的 effort 會傳入，未指定時不額外補旗標。沒有 `--agent` 時，Claude Code 的 `--recipe` 不能混用 `--model`／`--effort`；pi 的兩者都放進配方。
   腳本將 `[main] Read …` 作為啟動指令的單一位置參數。如果 agent 開工前不能用工具讀 brief，就用 `--inline-brief`，由啟動 shell 讀取 brief 檔並將內容當成同一個位置參數。如果 pi 的 inline brief 以 `@` 開頭，先加 `[main]` 標頭，因為 pi 將 `@` 開頭的參數當成檔案引用。
   帶 `--recipe` 時腳本先跑該 picker 的 `--recipe <JSON> --dry-run`，模型不在 relay 或 JSON 不合法就不建 tab，並帶出 picker 的原因。要先自己確認配方，就直接跑同一行 dry-run。腳本驗證 Herdr parent identity，建立 worker 並確認首輪啟動，再掛 watcher，最後回一行 JSON。
3. 把 JSON 收據記進狀態檔。`tab_id`／`pane_id` 是後續操作的唯一 target；`harness` 與 `recipe` 記實際用的外殼與配方；`session_id` 是日後 `worker-turns.py` 與續接的來源（pi 是 main 指定的 uuid，不是紀錄檔路徑）。

做完的樣子：收據有 `backend`、`harness`、`recipe`、parent/worker identity、`session_id`、`log`；worker 已收到 brief。

## Step 3：等待與轉達

- 首則訊息隨啟動命令進入 agent。腳本確認首輪活動後才掛 watcher。如果無法確認首輪，腳本會嘗試關閉 terminal 並回報結果。watcher 等 worker `idle`／`blocked`／`done`，再向收據裡的 Herdr parent target 喚醒；worker 用文字問問題時狀態是 `idle`。
- 讀 worker 現況：working 中依收據 `backend` 讀畫面——`herdr-core` 用 `hc read <pane_id>`，舊版 `herdr` 用 `herdr agent read --source visible`。歷史結果一律用收據的 `session_id` 取，不要用 worktree 最新檔猜 session：Claude Code 用 `scripts/worker-turns.py <worktree> --session <session_id> --last-assistant`；Codex／pi 用 `scripts/worker-turns.py --harness codex|pi --session <session_id>`，這一版只回 `last_assistant`。
- 轉達使用者答案時，依收據 `backend` 送訊：`herdr-core` 用 `hc send <pane_id> "[main] 以下為使用者原話：「…」"`，舊版 `herdr` 用 `herdr agent prompt <name> "[main] 以下為使用者原話：「…」"`。main 的補充另起一句並標「main 判讀」。worker 停下後再從同一收據重掛 `scripts/agent-watch.sh`。
- 使用者若直接進 worker terminal 談，main 不用轉達；Step 4 仍從指定 `session_id` 撈回來。

## Step 4：收工對帳

1. 依收據的 `harness` 取交付：Claude Code 跑 `scripts/worker-turns.py <worktree> --session <session_id> --last-assistant --full`（working 預覽用 `--last-assistant` 預設截 3,000 字並標 `last_assistant_truncated`；正式取件必加 `--full` 保留尾段），`human` 是使用者在 worker 裡打的裁決，逐條寫回規格與狀態檔，`main` 是 main 轉達，`last_assistant` 是交付訊息。Codex／pi 跑 `scripts/worker-turns.py --harness <harness> --session <session_id>`，這一版只回完整 `last_assistant`。
2. worker 宣稱「使用者已同意 X」的每條，在 `human` 裡找得到才算；找不到列成待拍板。Codex／pi worker 沒有 `human` 可查，它宣稱的使用者同意一律列成待拍板，向使用者確認。
3. 核 commit 範圍、票檔勾選與 Verification Log、收據檔存在、worktree 乾淨。
4. **接手 worker 交回的稽核**：brief 禁止 worker 再派 agent，或外殼是 Codex／pi 時，skill 的 Self-Verify 稽核（例如 auto-choice 帳本的 auditor）worker 跑不了，只會在交付訊息、收據或帳本寫「未執行、交 main」或 `NEEDS_DELEGATION`。先讀 `last_assistant`，再對交付訊息連到的收據所在目錄跑 `command grep -rn -E 'NEEDS_DELEGATION|auditor|Self-Verify|稽查|稽核' <收據目錄>`（沒有連結就改查 `<worktree>/.scratch`），找出每一條，讀原文。只有寫明未執行、交 main、`NEEDS_DELEGATION` 或 `SKIPPED` 的才由 main 補派；已經有 `COMPLIANT`、`FIXED_AFTER_AUDIT` 或 `FAILED` 結論的算稽核過，不重派（各 skill 規定同一份稿只稽核一次），只把結論寫進狀態檔，`FAILED` 的缺口列進待拍板。補派時照該 skill 的 Self-Verify 規格，每個 skill 各派一次（rubric 不同，不合併；同一 skill 的多份帳本放進同一次派工），結果寫進狀態檔；決定不派的，列進待拍板並寫原因。這是 Step 4 的一部分，不是之後再做的事：沒處理完不算收工。
5. 票檔或規格複本有改動就同步回正本。
6. **關不關 worker，看這條 branch 有沒有開 PR**：同一 feature branch 上還有下一包票要派（或 main 的 review-implement findings 要修）→ 不關，續派同一 worker，它的 context 還值錢；branch 已 push 且 PR 已開（Draft 也算，邊界是「有了對外的 review 入口」）→ 關，PR 之後的改動都會有 review 留言當新 brief，舊 context 沒有再用的價值，留著只會變成「idle 待命」這種沒人記得的懸置狀態。關法：只關本次收據裡的 worker——`herdr-core` 用 `hc kill <pane_id>` 後接 `hc rm <pane_id>`，舊版 `herdr` 用 `herdr tab close <tab_id>`；不要用 workspace 全量關閉，也不要關 parent、hub 或其他既有 terminal。

做完的樣子：狀態檔有 worker 的 commit 範圍與 `session_id`，每句使用者裁決都落到規格；worker 交回 main 的每條稽核都已派出並收回結果，或已列進待拍板；branch 已開 PR 的 worker terminal/tab 已關，還有下一包的 worker 在狀態檔寫明「續派中、待哪一包」而不是「idle 待命」。

## Step 5：review 與修

review-implement 由 main 對 worktree 路徑跑，不在 worker 裡跑：routing gate 要看到真人在 invoke 後的下一輪回答，worker 裡沒有真人。findings 要修就用同一收據的 session 重新接回，帶 findings 檔；修完回 Step 4。

如果要接回已退出的 worker（續修 findings、額度或 429 後續跑），就在下指令前讀 `references/herdr-notes.md`「續接」段，依收據的 `backend` 與 `harness` 在原 pane／terminal 回到 shell 後接回同一 session（配方環境變數皆留在原 shell 裡）：

- **Claude Code**：`herdr-core` 用 `hc send <pane_id> "claude <啟動參數> --resume <session_id>"`；舊版 `herdr` 用 `herdr agent start <name> --kind claude --pane <pane_id> -- <啟動參數> --resume <session_id>`。啟動參數是當初的 `--model M --effort E`，帶配方的是 cc-pick dry-run 的 args（漏掉會讓配方的 `--settings` 等設定失效）。
- **Codex**：`herdr-core` 用 `hc send <pane_id> "codex resume <session_id> -c check_for_update_on_startup=false --dangerously-bypass-approvals-and-sandbox"`；舊版 `herdr` 用 `herdr agent start <name> --kind codex --pane <pane_id> -- resume <session_id> -c check_for_update_on_startup=false --dangerously-bypass-approvals-and-sandbox`。
- **pi**：`herdr-core` 用 `hc send <pane_id> "pi <配方 dry-run 的 args> --approve --session-id <session_id>"`；舊版 `herdr` 用 `herdr agent start <name> --kind pi --pane <pane_id> -- <配方 dry-run 的 args> --approve --session-id <session_id>`。

接回後照 Step 3 重掛 watcher。

PR 開出後 reviewer 的留言另派**新** worker，brief 帶 PR 號與留言原文，不重接舊 session：舊 worker 依 Step 4 第 6 點已關，而且留言本身就是完整的任務描述，接回舊 context 只會讓它帶著已過時的 brief 假設去改。

## 邊界

- worker 不 push、不開 PR、不 rebase、不 amend；push 與 PR 由 main 依專案規則問過使用者再做。
- 本 skill 不決定派幾個、派給誰、要不要平行；那是 main 每次的判斷。
- 如果用途在席位目錄列為例外，就沿用原執行路徑；不藉本入口改動 workflow、pr-review 或 pi-subtask 的既有路由。尚未遷移的呼叫端照現行規則保留，例外與遷移邊界見 `references/session-routing.md`。
- 只操作本次啟動並由收據識別的 Herdr worker；不能用 active pane 或 workspace 全量關閉。
