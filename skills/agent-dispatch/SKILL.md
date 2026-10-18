---
name: agent-dispatch
description: "Run one repo's ticket batch in a terminal worker inside a target worktree through Herdr — Claude Code by default, or Codex CLI or pi when the user picks that harness — while main stays in its parent directory. Use when the user explicitly asks to 派 worker、派 Codex／pi worker、用 agent-dispatch、照 brief 做一包票. Requires separate per-run consent before any worktree or worker launch; ordinary implementation approval does not count. Do not use for small edits main can do, or without verified Herdr identity."
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/agent-dispatch/scripts/tests/explicit-consent-contract.test.sh -->

# Agent Dispatch

一個 worker = 一個 repo 的一包票。worker 是從指定 worktree 啟動的完整 terminal agent，外殼是 Claude Code（預設）、Codex CLI 或 pi；main 留在 parent directory 只做派工、轉達、對帳與 review。啟動、等待、回報與關閉都沿用啟動收據裡的 backend、外殼與 target identity。

## 為什麼是這個形狀

- subagent 拿不到 repo 的 hook 與 skill，`/cd` 與 handoff 會換位置；Claude Code worker 讓兩邊都生效，使用者也能直接走進 worker terminal 談。
- Codex 與 pi worker 是為了讓模型配上它表現較好的外殼。它們不套用 repo 的 Claude Code hook、skill 與 settings，所以驗收不靠 worker 內的治理，而靠 main 在 Step 4 核對 commit、測試、票與收據。
- 一包票一 worker，最後只由 main 對 worktree 做一次 review，避免每張票重複 review 與 mutation。
- worker 的 jsonl 裡 main 送的字與人打的字長得一樣，所以 main 送的每一則都加 `[main]` 前綴，對帳時才能分開。

## Step 0：取得當次派工同意

如果本次要啟動或續派 terminal worker，就在建立 worktree、寫 brief 或操作 backend 前，讀 `~/.claude/rules/common/dispatch-and-verify.md`〈終端派工只由 main 管理〉。本 skill 的派工入口只由直接承接使用者需求的 main 執行；subagent 與受委派的 terminal worker 回報需求給 main，不再起下一層 worker。`HERDR_*` 身分與 main 的 brief 都不能代替這個角色邊界。

一般實作授權不等於 agent-dispatch 派工授權。建立 worktree、寫 brief、建立收據目錄或啟動 worker 之前，先確認使用者是否已明確同意這一次派工。

使用者明說「派 worker」或「用 agent-dispatch」，且句子已指向本次任務時，視為當次同意；「可以實作」「照做」「繼續」或同意某份 plan，都不代表同意另開 worker。

如果要呈現派工資訊，就在寫訊息前讀 `references/harness-recommendations.md`：本次模型在表上有列，就附上推薦外殼、理由與證據強度，並照表標「未拍板」；表上沒有的模型不給推薦。使用者明確指定的外殼照辦，推薦表不擋。

如果尚未取得同意，用一段短訊息交代：

- 要派的任務與 repo
- main 不自己做的具體理由
- worker 數、外殼、配方與 backend。配方在 Claude Code 是 model＋effort 或 cc-pick 配方，在 Codex 是 model＋effort，在 pi 是 pi-pick 配方。只寫定一組外殼與配方：使用者沒指定外殼時寫 Claude Code；推薦表推薦別的外殼時另起一句附註，改不改由使用者明說。兩案並列時，使用者回「允許這次派工」同意的是哪一組就不明確
- 額外的 token／等待成本，以及 worktree 隔離方式

外殼是 Codex 或 pi 時，訊息裡寫明：這個 worker 不套用 repo 的 Claude Code hook、skill 與 settings，驗收靠 main 核對 commit、測試、票與收據。使用者已經明說要派這個外殼時，這句照樣寫進開工前的訊息，只是不必再等回覆。

只提供三個回覆方向：`允許這次派工`／`main 自己做`／`暫停`，然後停止。未回覆、拒絕或取消時不派工，也不反覆遊說。

同意只限當次具名的任務、repo、worker 數、外殼、配方與 backend；任務、repo、worker 數、外殼、配方或 backend 任一增加或改變時，重新取得同意。先呈現上述派工資訊後，使用者回「照預設」才算同意，不能把其他語境的「照預設」沿用過來。

取得同意後，再一次收齊尚未明確的 worker 數、repo、外殼與配方（沒指定外殼時是 Claude Code，配方 `opus[1m]` high）。Codex 缺 effort、pi 缺完整 pi-pick 配方時，在這裡問，不自己補。backend 固定為 Herdr，不再增加第二條 terminal backend 決策。

做完的樣子：transcript 裡找得到使用者對本次派工的明確同意，且同意綁定的任務、repo、worker 數、外殼、配方、backend 與即將執行的值完全一致；外殼是 Codex 或 pi 時，送出的訊息含治理差異那句。未達成時停在 Step 0。

## Backend routing

`scripts/start-worker.sh` 只在 Herdr parent identity 完整時派工，不因 CLI 已安裝就猜 backend。

- parent 必須同時有 `HERDR_PANE_ID` 與 `HERDR_WORKSPACE_ID`；只出現其中一個欄位就直接報錯。
- script 會用 `herdr pane get` 驗證 parent target；沒有完整 identity、target 不 live、或 CLI 回傳 `ok:false`，都在建立或注入前停止，也不向任意 active pane 發字。
- 指令或 watcher 回錯時，在重試前讀 `references/herdr-notes.md`。

做完的樣子：Herdr parent identity 齊全且 live；沒有任何第二 backend 的選路或 fallback。

## Step 1：開工位

1. 依 context 裡的專案指示決定 base branch，用 `git -C <repo>` 從 main 所在目錄開 worktree；不 `cd`。若已指定既有 worktree，就不另建 worktree。
2. 複製 worktree 拿不到的 gitignored 檔（env、settings.local）。
3. 依 context 裡的專案指示決定票檔與規格複本放哪個 repo 目錄；沒有慣例就留在正本位置、brief 指路徑。
4. 建收據目錄，選一個不會被測試清空的位置。

做完的樣子：worktree 在正確 base 上、`git status` 只剩預期複本、收據目錄存在。

## Step 2：寫 brief、起 worker

1. 從 `assets/brief-template.md` 填 brief，寫成檔案放正本目錄。使用者原話逐字貼、標「以下為使用者原話」；main 自己的判讀另段標明。多行文字送進 terminal 會被拆成多次送出，所以 brief 一律走檔案。
2. 跑 `scripts/start-worker.sh <name> <worktree> <brief> [外殼與配方] [--label L] [--log-dir D] [--no-watch]`，外殼與配方擇一：
   - Claude Code：不帶外殼參數，`--model M --effort E`（預設 `opus[1m]` high）或 `--recipe '<cc-pick 配方 JSON>'`。cc-pick 配方是 `main`／`fable`／`opus`／`sonnet`／`subagent` 五個槽位都到的字串物件，空字串代表原生。
   - Codex：`--harness codex --model <id> --effort <e>`，兩個都要給。
   - pi：`--harness pi --recipe '<pi-pick 配方 JSON>'`。形狀照 `pi-pick --last --dry-run` 輸出的 `recipe` 欄位。
   帶 `--recipe` 時腳本先跑該 picker 的 `--recipe <JSON> --dry-run`，模型不在 relay 或 JSON 不合法就不建 tab，並帶出 picker 的原因；要先自己確認配方，就直接跑同一行 dry-run。腳本驗證 Herdr parent identity，建立 worker、送 brief，確認 prompt 已開始，再掛 watcher，最後回一行 JSON。
3. 把 JSON 收據記進狀態檔。`tab_id`／`pane_id` 是後續操作的唯一 target；`harness` 與 `recipe` 記實際用的外殼與配方；`session_id` 是日後 `worker-turns.py` 與續接的來源（pi 是 main 指定的 uuid，不是紀錄檔路徑）。

做完的樣子：收據有 `backend`、`harness`、`recipe`、parent/worker identity、`session_id`、`log`；worker 已收到 brief。

## Step 3：等待與轉達

- watcher 在 `agent prompt --wait --until working` 成功後才啟動，等 worker `idle`／`blocked`／`done`，再只向收據裡的 Herdr parent pane 喚醒；worker 用文字問問題時狀態是 `idle` 不是 `blocked`。
- 讀 worker 現況：working 中用 `herdr agent read --source visible`。歷史結果一律用收據的 `session_id` 取，不要用 worktree 最新檔猜 session：Claude Code 用 `scripts/worker-turns.py <worktree> --session <session_id> --last-assistant`；Codex／pi 用 `scripts/worker-turns.py --harness codex|pi --session <session_id>`，這一版只回 `last_assistant`。
- 轉達使用者答案時，用 `herdr agent prompt <name> "[main] 以下為使用者原話：「…」"`。main 的補充另起一句並標「main 判讀」。worker 停下後再從同一收據重掛 `scripts/agent-watch.sh`。
- 使用者若直接進 worker terminal 談，main 不用轉達；Step 4 仍從指定 `session_id` 撈回來。

## Step 4：收工對帳

1. 依收據的 `harness` 取交付：Claude Code 跑 `scripts/worker-turns.py <worktree> --session <session_id> --last-assistant`，`human` 是使用者在 worker 裡打的裁決，逐條寫回規格與狀態檔，`main` 是 main 轉達，`last_assistant` 是交付訊息。Codex／pi 跑 `scripts/worker-turns.py --harness <harness> --session <session_id>`，只拿得到 `last_assistant`。
2. worker 宣稱「使用者已同意 X」的每條，在 `human` 裡找得到才算；找不到列成待拍板。Codex／pi worker 沒有 `human` 可查，它宣稱的使用者同意一律列成待拍板，向使用者確認。
3. 核 commit 範圍、票檔勾選與 Verification Log、收據檔存在、worktree 乾淨。
4. 票檔或規格複本有改動就同步回正本。
5. **關不關 worker，看這條 branch 有沒有開 PR**：同一 feature branch 上還有下一包票要派（或 main 的 review-implement findings 要修）→ 不關，續派同一 worker，它的 context 還值錢；branch 已 push 且 PR 已開（Draft 也算，邊界是「有了對外的 review 入口」）→ 關，PR 之後的改動都會有 review 留言當新 brief，舊 context 沒有再用的價值，留著只會變成「idle 待命」這種沒人記得的懸置狀態。關法：只關本次收據裡的 worker，用 `herdr tab close <tab_id>`；不要用 workspace 全量關閉，也不要關 parent、hub 或其他既有 terminal。

做完的樣子：狀態檔有 worker 的 commit 範圍與 `session_id`，每句使用者裁決都落到規格；branch 已開 PR 的 worker terminal/tab 已關，還有下一包的 worker 在狀態檔寫明「續派中、待哪一包」而不是「idle 待命」。

## Step 5：review 與修

review-implement 由 main 對 worktree 路徑跑，不在 worker 裡跑：routing gate 要看到真人在 invoke 後的下一輪回答，worker 裡沒有真人。findings 要修就用同一收據的 session 重新接回，帶 findings 檔；修完回 Step 4。

如果要接回已退出的 worker（續修 findings、額度或 429 後續跑），就在下指令前讀 `references/herdr-notes.md`「續接」段，依收據的 `harness` 在原 pane 回到 shell 後接回同一 session：

- Claude Code：`herdr agent start <name> --kind claude --pane <pane_id> -- <啟動參數> --resume <session_id>`；啟動參數是當初的 `--model M --effort E`，帶配方的是 cc-pick dry-run 的 args（漏掉會讓配方的 `--settings` 等設定失效），配方環境變數還在原 tab 的 shell 裡。
- Codex：`herdr agent start <name> --kind codex --pane <pane_id> -- resume <session_id> -c check_for_update_on_startup=false --dangerously-bypass-approvals-and-sandbox`。
- pi：`herdr agent start <name> --kind pi --pane <pane_id> -- <配方 dry-run 的 args> --approve --session-id <session_id>`；配方環境變數還在原 tab 的 shell 裡。

接回後照 Step 3 重掛 watcher。

PR 開出後 reviewer 的留言另派**新** worker，brief 帶 PR 號與留言原文，不重接舊 session：舊 worker 依 Step 4 第 5 點已關，而且留言本身就是完整的任務描述，接回舊 context 只會讓它帶著已過時的 brief 假設去改。

## 邊界

- worker 不 push、不開 PR、不 rebase、不 amend；push 與 PR 由 main 依專案規則問過使用者再做。
- 本 skill 不決定派幾個、派給誰、要不要平行；那是 main 每次的判斷。
- Workflow、codex:rescue 這類 subagent 包裝與其他無關 dispatch skill 不在本 skill 的路徑內；Codex 只以 Herdr worker 外殼的身分出現在這裡。
- 只操作本次啟動並由收據識別的 Herdr worker；不能用 active pane 或 workspace 全量關閉。
