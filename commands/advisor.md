---
description: "Use when 使用者對當前 main model 這一輪的思考品質不滿意、想把單次判斷外包給另一個模型，而不想為此把整個 session 換成更貴的 model；或明說「問一下 advisor」「找個顧問」「換顆腦袋看」「這個叫 Fable 想想」。也用於使用者只輸入 `/advisor`，或尚未決定方案、想請顧問獨立提出候選方案時。Do not use for：要外部模型實際動手改檔或跑第二次實作嘗試（實作委外走 handoff-impl、卡關救援走 codex:rescue）、spec 對抗式審查（review-spec）、事實查證（research-before-answer）。分界是顧問只回判斷、不留下任何改動；需要它動手就不是這支。"
argument-hint: "[--blind|--full] [顧問代號] <要問的問題>；空參數 = 從當前 context 整理理解並列出選項"
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/advisor-codex-desktop-contract.test.sh -->

# /advisor — 外包一次思考，不動整個 session 的 model

切 main model 是讓整個 session 後續都變貴，只為了一次思考。這個 command 把單次判斷派給指定模型，拿回意見後由你決定聽不聽。

顧問只出意見、不動手 —— 但**保證強度按路徑不同**，別一視同仁：

- 選項 3 用 `-s read-only`，**機制層強制**，它想動也動不了。
- 選項 2 在 Claude Code 走獨立網頁，本來就碰不到本機；在 Codex Desktop 走 Direct Web Pro／DevSpace snapshot，controller 只建立並刪除固定的 owner-only snapshot，不對顧問暴露一般修改工具。
- **選項 1 在 Claude Code 走 Agent 時沒有這道鎖**：`advisor-seat` 帶全套工具（含 Write／Edit／Bash）。約束寫在該 agent 定義檔的 body 裡（唯讀紀律段），是**常駐的自律約束、不是機制強制**——它想動仍然動得了。Codex Desktop 改走下方獨立 Claude CLI，明確停用 Write／Edit／NotebookEdit／Bash／Agent、Chrome 與 MCP；代價是該席不能自己跑 Git／shell 查證。Step 4 第 3 段的角色文字仍是補強，不是替代。

（研究結論裡最硬的一條是「看 tool 清單、不看角色名字」。這支 command 自己也適用 —— 所以上面按路徑分開講，而不是統一宣稱「顧問拿不到寫入權」。）

**為什麼選項 1 的 Claude Code Agent 不做機制強制**（2026-09-10 拍板 + 實測，不要重提）：機制路線有兩條，都不划算。(a) `tools:` 白名單砍掉 Bash → 確定有效，但顧問失去查證能力（不能跑 jq / git log / ccsi），這正是選項 1 的價值所在。(b) `permissionMode: plan` → 三輪對照實測確認**是 harness 層真鎖**（逼它硬試，回 `Cannot write ... while in plan mode`、檔案確實沒落地），但本機 `settings.json` 的 `defaultMode: bypassPermissions` 會把它整個壓掉（實測該模式下 plan mode 連啟動都沒有），而 subagent 與母 session 共用權限模式、無法單席開啟。所以 CC Agent 現況是刻意選擇：保住查證能力，接受自律約束。Codex Desktop 的跨 CLI 路徑是另一個 process，可以把 mutation tools 直接停用，不沿用這項取捨。

## 為什麼目前是手動觸發

Sourcegraph Amp 是這批調查裡最乾淨的 shipped shape (A) 實例（覆蓋率 8/17，不宣稱唯一），官方文件寫明刻意不在 system prompt 推 main agent 自己去諮詢，改為建議使用者顯式要求。使用者 2026-07-09 對 CMA Advisor 的判定也是同一結論：讓執行中的模型自評「我現在需不需要求救」是遞迴的判斷題，結構性不穩。

所以觸發權目前在人手上。這是**先後順序、不是原則**：使用者 2026-09-03 拍板「先手動，真的好用再檢討無人值守」。同一份研究的主結論是業界收斂於「事件式檢查點」（綁 Stop / PR / plan 完成這類確定會發生的時機），要接自動觸發時走那條路，帶參數直接派的入口就是為此保留的。

## Step 0：入口與當前 context

`/advisor` 的主要使用方式是無參數。先把當前 session 已知的問題、目標、材料和限制整理出來，不能把空參數解讀成「沒有問題」，也不立即要求使用者重講已知內容。

- **無參數** → 依當前 context 整理一句話理解與任務目的；在同一輪呈現理解、材料策略、完整顧問選項與推薦，然後等待使用者用自然語言糾正或選擇。
- **context 有關鍵缺口** → 只有 context 不足且不同理解會改變任務目標或範圍時才追問；如果只是某個 path 缺材料，仍列出完整選項並標示「需要補材料」。補齊前不派工，也不要求使用者重打 command。
- **帶問題文字或進階參數** → 保留既有快捷入口，依 Step 1–3 處理；參數是進階用法，不是正常使用的前提。
- 同一任務已有明確指定的模式、顧問或組合就沿用；只在該任務的 context 內沿用，不跨任務延用授權，不靜默換模型。推薦永遠只是建議，未獲選定、使用者取消或材料不足時不派工。
- 列出顧問選項與派工前，先讀 `~/.claude/references/subagent-routing.md` 的「派工前核對實際模型」。若當前 subagent 路徑會將 Fable 等別名映射到 GPT，不把 `model: fable` 當成 Fable 可用；使用已批准的原生 TUI 路徑時明確指定模型與 effort。派出後核對實際模型，再標示顧問身分；模型不符不算已完成該席。

這是 runtime 的 context 判斷，不新增自動 advisor 觸發、分類程式、模型 registry 或 provider adapter。

**完成條件**：已從 context 整理出一句話理解、任務目的、材料與限制；有關鍵缺口時追問並停止，否則接 Step 1–3，在同一輪呈現理解與選單後等待選擇。

## Step 1：整理任務目的與材料策略

任務目的用自由文字描述，由 session 依當前 context 先寫成一句話；不要求使用者記住或選固定用途分類。常見說法是「獨立出方案」或「挑戰目前草案」，它們是理解任務的例子，不是新的模式或分類器。

- 如果目的是**獨立出方案**，只提供原始需求、已核對事實與硬限制，不預先附上本地答案、結論、排除項或理由。
- 如果目的是**挑戰目前草案**，提供原始問題、待審草案，以及我的結論和已排除選項；三樣各自標明，讓顧問能指出草案的盲點。
- 如果問題只能從累積脈絡理解，才使用對話文字材料；先確認 context 是否真的不足，不因為無參數就要求使用者重新描述。

以下是既有顧問材料路徑，不是使用者要先選的用途分類。無參數時由 session 依任務目的、材料完整性與限制決定；`--blind`、`--full` 或同一任務已有明確指定時才覆寫。

| 材料路徑 | 何時用 | 顧問看到什麼 |
|---|---|---|
| **提問模式**（挑戰目前草案） | 問題本身講得清楚，要的是對我的結論做壓力測試 | 原始問題 + 我目前的結論 + 我試過但排除的選項，三樣各自標明 |
| **盲審模式**（獨立出方案；`--blind`） | 想讓顧問自己走一遍，不被本地結論錨定 | 原始任務 + 可驗證的證據與約束，**刻意不含我的結論、不含我排除了什麼、不含我的理由** |
| **對話文字模式**（`--full`） | 問題卡在累積的脈絡裡，單獨拎出來會失真 | 本 session 的對話**文字**（機械抽取，不經我摘要）—— 不含 tool 執行紀錄 |

這三條是材料策略，不是要求使用者記住的工作目的。這個模式用機械抽取而不是我寫摘要，理由是摘要會帶上我的視角 —— 顧問讀我濃縮過的版本，等於再看一次我的思路，換腦袋的意義就沒了。

**它不是「完整脈絡」，別這樣講。** 抽取只保留文字 block，`tool_use` 與 `tool_result` 全部不在裡面 —— 實測那些佔原始 jsonl 的 70%（tool 內容 588 KB vs 文字 249 KB）。所以顧問拿到的是「我說了什麼」，不是「我做了什麼」，它無法核對我的宣稱有沒有對應的執行動作。

**要執行證據的話，讓顧問自己去讀，不要我幫它抽。** 選項 1 與 3 都有讀檔能力，直接在 prompt 裡給它 jsonl 路徑：

```
~/.claude/projects/<專案目錄>/<CLAUDE_CODE_SESSION_ID>.jsonl
```

它自己翻比我幫它挑好，理由跟上一段同源：我挑證據時會挑到支持我的那些。

**盲審模式為什麼存在**：2026-09-03 一次 ChatGPT Pro 盲點審查指出，提問與對話文字模式構成假兩難 —— 「不是讀原 agent 的摘要，就是讀原 agent 的全部思考」。兩者都會讓顧問停在我的框架內：前者遺漏我沒意識到的前提，後者被我的推理路徑錨定。實證是同一份完整脈絡下，Fable 抓到大量實作缺陷卻沒質疑「該不該做成這種 command」。

所以盲審模式的紀律是**減法**：給任務、給查得到的事實、給硬約束，不給我的答案。顧問得自己走一遍。它的結論跟我不同時，那個差異本身就是最有價值的輸出。

session 內部選擇材料路徑的一句話依據：要它**挑我的錯**用提問或對話文字；要它**自己想一遍**用盲審。無參數時由 session 依 context 決定，不要求使用者記住模式名；只有明確參數或同一任務已有明確指定時才沿用。

抽取一律用這支，不要自己寫：

```bash
python3 ~/.claude/scripts/advisor-extract-context.py --out /tmp/advisor-ctx.txt
```

它會印出回合數、濾掉的 isMeta 量與實際位元組數。session id 預設讀 `CLAUDE_CODE_SESSION_ID`，也可以 `--session <id>` 指定。

不要自己照著描述重寫抽取邏輯 —— 這支存在的原因就是散文版寫錯過：user 的 `message.content` 是**純字串**不是 block list，照「取 type=='text' 的區塊」做會**丟掉全部使用者發言**，只留下我自己的獨白，剛好是對話文字模式要避免的事。另外 hook 注入的 skill 內文（`isMeta`）佔掉約 45% 位元組，也在裡面濾掉了。本 session 實測：190 KB → 101 KB，使用者發言 20 則全數保留。

超過 `--max-bytes`（預設 190000）時它會保留最近的回合並在檔首標明截斷了幾則 —— 顧問必須知道自己看到的是尾段，否則它會對「討論初期」下沒有依據的判斷。

**完成條件**：材料路徑已由 context 或明確進階參數決定；對話文字模式下已跑過這支 script 並拿到它印出的實際位元組數（不是估算，也不是自己寫的抽取）。

## Step 2：讀 Fable 額度，決定推薦選項

Fable 不是另給的配額，它是週額池的 50% cap。所以總額還很鬆的時候 Fable 可能已經見底 —— 不能用 `seven_day` 反推。

CC 原生 statusline 的 `rate_limits` 沒有 per-model 欄位，唯一路徑是 quota cache 的 `.data.limits[]`：

```bash
. ~/.claude/scripts/lib/resolve-account.sh
jq -r '[.data.limits[]? | select(.kind == "weekly_scoped") | .percent] | max // empty' \
  "$(cc_resolve_quota_file)"
```

**要先解析 active 帳號**，不要對 `~/.claude/cache/quota-*.json` 下 glob 再取 max —— 那會跨帳號比較，另一個帳號燒得更兇時回報的是它的數字。`cc_resolve_quota_file` 是 `workflow-limit-watch.sh` 在用的同一支解析。

**Fable ≥ 95% 時把推薦從選項 1 改掉並說明原因**：顧問需要讀本機東西就推選項 3，否則推選項 2。撈不到數值時當作未知、照常列選單但標明「Fable 額度未知」，不要當成 0。

**完成條件**：手上有一個具體百分比或明確的「未知」，且推薦選項已據此決定。這個推薦只填 Step 3 的標記，不是使用者已選定的顧問，也不能觸發派工。

## Step 3：呈現選單並取得選擇

無參數時，把 Step 0 的一句話理解、任務目的、材料與限制摘要，連同當前 Fable％和下表完整顧問選項，在同一輪呈現。每個選項都要標出當次狀態（**推薦／可選／需要補材料／當下不可用**）、適用理由、必要條件與可確認的實際模型識別；模型識別未知就明寫未知，不可省略或默默換成別的 path。

推薦只是建議，不是已選定的顧問。等待使用者回「照推薦」、用自然語言選擇或調整顧問、或明確取消；不要求使用者把自然語言翻成旗標後重打 command。若有顧問代號或其他進階參數明確指定，保留既有快捷入口並在材料與授權條件滿足後直接派該席。

使用者未回答、明確取消、材料不足或尚未選定時停在選用階段，不派工；未回覆不等於接受推薦。同一任務已有明確指定的顧問或組合時沿用，不能把前一任務的授權帶到新的任務，也不能在被選 path 失敗時靜默換模型或重跑已成功的席位。

下表列出當次既有執行路徑可配置的完整選項；即使某選項當下不可用或需要補材料，也要保留在選單並說明原因，不得只呈現推薦項。

選路徑的軸是**能力**，不是強度。哪個模型「比較聰明」不可靠也難證；「它能不能自己查證」是確定的事實，而且直接決定它能做哪一類審查。

| # | 顧問 | 能自己查本機嗎 | 因此適合審 | 燒什麼 |
|---|---|---|---|---|
| **1** | **Fable 5.1 · xhigh**（額度充足時的預設） | ✅ 帶全套工具（唯讀靠定義檔自律） | 實作層 —— 指令對不對、參數合不合法、程式碼與宣稱是否一致 | Fable 週額 50% cap |
| 3 | Codex `gpt-6-astra` · xhigh | ✅ 讀檔＋跑唯讀指令 | 實作層 ＋ 方法層 —— 能自己去核對證據，所以查得出「你的實驗設計不成立」這類問題 | ChatGPT 訂閱 |

**調用方式**

- 選項 1 在 Claude Code：`Agent(subagent_type:"advisor-seat", model:"fable", description:"<fable-ok> …")`

### Codex Desktop Fable 路徑

選項 1 且環境是 Codex Desktop 時，不用 `spawn_agent`：Codex 的 model allowlist 沒有 Fable，`advisor-seat`／`cc_flagship` 也都固定為 Astra。改用本機 Claude CLI 建立一個獨立 `advisor-seat` session；這是實際 Anthropic Fable，不是 Fable-tier 映射。Step 2 已取得 active 帳號 quota，只有低於 95% 或使用者明知額度狀態仍明確指定時才執行。

1. 把 Step 4 的四段 prompt 寫入 owner-only temporary file，讀進變數後再傳；不要把 prompt 本文嵌進 shell command。Done when：prompt file 權限為 600，`FABLE_PROMPT` 來自該檔完整內容。
2. 執行一次，不重送：

```bash
FABLE_PROMPT=$(cat <prompt-file>)
FABLE_RECEIPT=$(claude -p \
  --agent advisor-seat \
  --model fable \
  --effort xhigh \
  --permission-mode dontAsk \
  --permission-prompts none \
  --disallowedTools Write,Edit,NotebookEdit,Bash,Agent \
  --strict-mcp-config \
  --no-chrome \
  --output-format json \
  "$FABLE_PROMPT")
```

這條 Codex 分支沒有明文停用 Read／Grep／Glob 與內建網頁讀取，但本輪 canary 只驗零工具回答，實際 tool call 可用性仍須由當次 receipt 判斷；確定沒有的是 Bash、Chrome 與 MCP。問題必須自己跑 Git／shell 才能判斷時，改選選項 3；不要先跑 Fable 再因工具不足自動補一席。

3. 只有下列檢查通過才標成 Fable 回答：

```bash
printf '%s' "$FABLE_RECEIPT" | jq -e '
  .is_error == false and
  .terminal_reason == "completed" and
  ([.modelUsage[]? |
    select(.provider == "firstParty" and (.canonicalModel | startswith("claude-fable-")))] |
   length >= 1) and
  (.result | type == "string" and length > 0)
' >/dev/null
```

檢查通過後，從 `modelUsage` 回報實際 `canonicalModel` 與 `session_id`，並把 `.result` 原文交給 Step 5。任何欄位缺失、非 first-party Fable、CLI 非零退出或空回答都算本席失敗；**不靜默換成 Astra**、6 Pro、其他 Claude model，也不重送。Done when：terminal receipt 可定位到一個 first-party `claude-fable-*`，且只有一發請求。

🔌 接線點：ChatGPT 網頁版席位 — 見 WIRING.md
- 選項 3：**直接跑 codex CLI，不要走 `codex:rescue` plugin**（理由見下）

```bash
PROMPT=$(cat <prompt 檔)          # 讀進變數再用 "$PROMPT" 傳
codex exec -m gpt-6-astra -s read-only --skip-git-repo-check \
  -o <答案落檔路徑> "$PROMPT"
```

prompt 一定要先讀進變數、再用 `"$PROMPT"` 傳。**不要把檔案內容直接嵌進指令字串** —— 對話正文裡有幾百個反引號（本 session 實測 748 個），嵌進去會被 shell 當 command substitution 執行。變數展開後 bash 不再解析內容，所以這樣是安全的。

跑完**驗一下參數真的有到**（三個都在 codex 自己的 rollout 檔裡，這是唯一驗得到的地方）：

```bash
grep -o -E '"(model|reasoning_effort|sandbox_policy)"[^,}]{0,40}' \
  "$(ls -t ~/.codex/sessions/*/*/*/rollout-*.jsonl | head -1)" | sort -u
```

預期看到 `"model":"gpt-6-astra"`、`"reasoning_effort":"ultra"`、`"sandbox_policy":{"type":"read-only"`。**這步不是可選的**：2026-09-03 我連續三次宣稱參數生效，前兩次拿不出證據、第三次才發現自己其實在降級。

選 2 還是 3 的一句話判準：**需要核對證據就走 3，只需要想清楚就走 2**。

選項 1 與 3 既然能自己查，就在 prompt 裡給它 session jsonl 路徑，讓它自己找執行證據（見 Step 1）。選項 2 拿不到那層，所以別叫它判斷「你的驗證做得夠不夠」——它只能就送進去的文字論述。

**同模型排除**：main 自己就是 Fable 時，不要推薦選項 1。那種情況下「換一顆腦袋」是假的，同一個模型不會有不同盲區。改推 2 或 3，或明確講清楚這次是同模型複查、不是第二意見。

選項 1 的 `<fable-ok>` 要放在 `description` 欄位，放在 prompt 內文不算授權 —— T2-routing-gate 只認 description。這是使用者 2026-07-20 訂的配額政策，不是可以繞的形式要求。

選項 3 的每個旗標都有理由，別省：

- `-m gpt-6-astra` —— `~/.codex/config.toml` 預設現在也是 `gpt-6-astra`，明確指定是為了不受 config 日後變動影響。
- `-s read-only` —— **這是機制強制**，不是靠任務文字說服誰。顧問改不了東西，也就不必花篇幅交代它別動手。
- **effort 不要指定** —— `~/.codex/config.toml` 現在是 `model_reasoning_effort = "ultra"`（2026-09-05 隨 astra 換代一起改）。codex CLI 確實吃 config 的值：2026-09-03 config 還是 `max` 時從 rollout 檔實測到 `"effort":"max"`。帶 `-c model_reasoning_effort=xhigh` 是**主動降級** —— `xhigh` 是 `codex-companion.mjs:69` 那個 plugin 的上限，不是 codex 的上限。誤把 plugin 限制當成工具限制，就會在直接 CLI 這條路上白白降一級。
- `-o <檔案>` —— 最終訊息落檔，不用從 stream 撈。
- `--json` 可選 —— 它印事件流（看進度、看錯誤有用），但**不帶 model 欄位**，別拿它當驗證手段。
- `--skip-git-repo-check` —— 在非 git 目錄跑時不會被擋。

**為什麼不走 `codex:rescue` plugin**（2026-09-03 實測，兩者都跑過）：

| | plugin | 直接 CLI |
|---|---|---|
| 產出判斷 | ❌ 兩輪都失敗（46 分鐘後 process 消失、state 卡 `running`；`--resume` 35 秒 no output） | ✅ 成功，exit 0 |
| read-only | forwarder 讀任務文字推斷後設 `write: False` | `-s read-only` 旗標強制 |
| 用了哪個 model | ❌ log 與 job json 都不記 | ✅ `--json` 事件流 |

plugin 那條路整體不可觀測：失敗時看不出為什麼，成功時也證明不了參數有生效。附帶一筆：`426 Upgrade Required, ws://127.0.0.1:17841/v1/responses` 這個錯誤是假警報，CLI 會降級成 HTTP 後正常完成 —— 別因為看到它就以為壞了。

**完成條件**：使用者已選定顧問（可回「照推薦」或用自然語言選擇），或已有明確進階參數；推薦本身不算選定。材料不足、未回答或取消時不派工。選項 1 在 Claude Code 的 description 內確實含 `<fable-ok>`、且已確認 main 本身不是 Fable；選項 1 在 Codex Desktop 的 terminal receipt 已核對 first-party `claude-fable-*`、非空結果與 session id；選項 2 走 Direct Web Pro（Codex Desktop 與 Claude Code 共用同一套判定）的 terminal receipt 必須同時記錄 `sourceThreadId exact`、`transport=direct`、`model/resolvedModel=gpt-6-pro`、`power=pro`、`submitted=true`、`terminalAsyncStatus=4`、非空 answer、`devspaceUsed=true`、`devspaceScopeClosed=true`、`devspaceCoverage` 的 `openScope`／`statPath`／`queryJsonl`／`closeScope` 全為 true、`snapshotMode=0600`、`snapshotDeleted=true`、`quickChatUiUsed=false`、`uiFallback=false`、`resubmitCount=0`，以及非空的 `conversationId` 與 `streamRequestId`；在 Claude Code 環境另外確認命令帶了 `--sessions-root ~/.claude/projects`、`--source-thread-id` 是當前 CC session id，且前置的 main renderer 計數為 1；保存 native conversationId 只供使用者明確要求的 follow-up，不做清單差集或標題匹配，也不自動 follow-up；選項 3 的情況下跑完已用上面那條 grep 從 rollout 檔看到 `model`、`reasoning_effort`、`sandbox_policy` 三個實際值（不是「我帶了旗標」，是「它真的收到了」）。

## Step 4：打包問題

給顧問的 prompt 固定四段，缺一段就補。無參數 path 以 Step 0 整理出的自由文字任務目的為準，不把它改寫成要求使用者記住的固定分類：

1. **要判斷什麼** — 一句話講清楚要回答的問題與任務目的。若是獨立出方案，明確要它自己提出方案；若是挑戰目前草案，明確要它找草案盲點與更小替代。提問／對話文字材料要**明確要它找我容易漏掉的角度**，而不是只重跑我的推理看結論同不同；盲審材料相反 —— 要它獨立走一遍並給出自己的方案。
2. **脈絡** — 按任務目的與材料路徑給：
   - **獨立出方案**：只放原始需求、已核對事實與硬限制，**不含我的答案或本地預想答案、結論、排除項與理由**。逐字檢查一遍有沒有洩漏我的結論 —— 「我認為」「我們決定」「已排除」「比較好的做法是」這類句子全部拿掉，連暗示都不留。
   - **挑戰目前草案**：原始問題、待審草案、我的結論與我排除的選項各自標明，不能把草案、結論和排除項混在一起。
   - 提問模式：三樣（原始問題／我的結論／我排除的選項）各自標明。
   - **盲審模式**：原始任務 + 可驗證證據（檔案路徑、實測數字、外部事實）+ 硬約束；逐字檢查一遍有沒有洩漏我的結論 —— 「我認為」「我們決定」「已排除」「比較好的做法是」這類句子全部拿掉，連暗示都不留。
   - 對話文字模式：script 抽出的對話正文。
3. **它的角色** — 逐字寫：只給判斷、不要出手改任何東西、不確定就說不確定，不要為了給答案而編；再加一句「找不到問題就直說沒有，不要為了交差而製造問題」
4. **要什麼形狀的回答** — 例如「最可能的問題，每個附你依據哪一段」。盲審模式改成「你的方案 + 你為什麼排除其他做法」
   - **審程式碼或送出前審查**：每個問題除了後果，另要它填兩欄——觸發條件（要同時滿足哪些情況才會發生）、真實使用會不會碰到（會／偏少見／邊角，附一句理由）。邊角的問題不能標成擋送出，列為小事並附觸發條件，由使用者決定修不修。不寫「最多 N 個」，找不到就說沒有。
   - **複審**（同一份東西修完再問）：只請它逐條判斷上一輪的問題修好沒有、修法有沒有帶進回歸；不寫「刻意找修法本身的漏洞」。新問題沿用上面兩欄。
   - 為什麼：只給固定分級格與名額、再要求複審刻意找漏洞時，Pro 會依後果把邊角情況標成擋送出，修進真實使用碰不到的情況；不給分級格式時，Pro 自己會分清「推得出」與「會發生」。

第 1 段那個要求不是修辭。使用者自己的 `fable-routing-downgrade` trial 結論寫在 `~/.claude/references/subagent-routing.md:108`：架構審查時兩個模型**各有獨有的採納 finding**。也就是說顧問對 main model 是**互補**、不是**更強** —— 品質提升來自換一個視角，不是換一顆更好的腦袋。叫它「重做一遍看看對不對」等於放棄這支 command 的價值來源。

第 3 段的理由：顧問看到我一路在動手，容易接著提議「那我來改」。選項 1 的第一道界線是 `advisor-seat` 定義檔 body 的唯讀紀律段（常駐、不必每次重打），**這段任務文字是它的補強**——兩者都是自律層，`advisor-seat` 帶全套工具；選項 2、3 有各自的機制擋著，那裡寫這段是為了省掉它花時間確認自己能不能動手。

**完成條件**：四段都有內容；挑戰目前草案時第 2 段的「待審草案」、「我的結論」與「我排除的選項」是分開標示的（混在一起顧問無法分辨哪些是已否決的）；**獨立出方案或盲審模式下已把第 2 段從頭讀過一遍確認零本地答案與結論洩漏** —— 這條漏掉，盲審就退化成提問模式而且沒人會發現。

## Step 5：呈現回答

顧問的意見原文貼給使用者，然後用一句話標出它跟我的看法哪裡不同。

選項 2 的 receipt 帶 `snapshotProof` 時，原文前先寫一行讀取範圍：`mismatch` 寫「Pro 只讀到快照第 `snapshotLinesReached` 行（共 `snapshotLineCount` 行），之後的對話它沒看到」，`missing` 寫「Pro 沒回報讀到第幾行」，`verified` 不用寫。這行是告示、不是收件失敗：本席過不過只看上面第 4 點的條件，答案照常呈現、照常進 Step 6。為什麼要寫：快照讀不完時，漏掉的通常是最近的脈絡，使用者要知道顧問的判斷少看了哪一段。

不要先消化再轉述 —— 那等於用我的視角再過濾一次，跟對話文字模式用機械抽取是同一個理由。

意見與我的結論衝突時，不預設誰對：把分歧點講清楚交給使用者判斷。顧問跑的是另一顆模型，它可能看到我的盲區，也可能因為缺少脈絡而誤判。

**做完的判準**：顧問原文已呈現，且已明確寫出「一致」或具體指出分歧在哪；`snapshotProof` 是 `mismatch` 或 `missing` 時，原文前已有那行讀取範圍。**接著進 Step 6，不要停在這裡。**

## Step 6：逐條裁決

顧問給了幾條，這張表就要有幾列：

| 顧問的意見 | 裁決 | 依據 |
|---|---|---|
| （一句話濃縮，不要改變原意） | 接受／拒絕／待驗證 | 接受 → 具體要做什麼；拒絕 → **反證**；待驗證 → 用什麼方法、什麼時候驗 |

三條紀律：

- **拒絕必附反證。** 「這個情境不適用」「我不同意」不算依據 —— 那是換句話說的忽略。
- **不准挑軟的打。** 質疑整體方向的那幾條最容易被跳過，因為修起來最貴。表格列數對不上顧問條目數就是漏了。
- **待驗證不是拖延檔位。** 寫不出驗法與時機，那條就該直接裁成接受或拒絕。

為什麼這步不能省：2026-09-03 的 ChatGPT Pro 審查點出，這支 command 只設計了「取得建議」，沒設計「建議如何可靠地改變後續工作」；缺這一步，顧問會退化成**昂貴但不具約束力的評論產生器**。那次之所以有效，是因為使用者在場、而且主 session 主動去實測了三條高嚴重度發現 —— 那是行為，不是 command 保證的東西。無人值守時尤其危險：模型會挑容易的修、合理化拒絕根本性批評，然後照原方向收工。

**做完的判準**：表格列數等於顧問條目數；每個「拒絕」都有反證；每個「待驗證」都有驗法與時機；沒有任何一條被靜默略過。

## 資料流向

選項 1 留在 Anthropic，選項 2、3 送到 OpenAI。兩家都是使用者已在使用的可信任服務，**不需要為此加確認步驟或限制範圍** —— 直接派即可。

## 顧問回來之後

意見不具強制力 —— 但**不具強制力不等於可以不回應**。Step 6 要求的是對每條給出裁決，不是全部接受；拒絕是合法裁決，只要說得出反證。

真的要照著改，那是另一段工作、走原本的實作路徑；裁決表只負責讓「不改」是個明講過的決定，而不是默默飄走。

## 踩過的坑

只留正文沒交代的那一條：

- **`<fable-ok>` 的位置，讀過警告還是會放錯。** 本檔作者第一次實跑就把它寫進 `prompt` 開頭、`description` 留空，被 T2-routing-gate 當場擋下。Claude Code 走 Agent 的選項 1 時直接照抄這個形狀，不要重打；Codex Desktop 的 Fable CLI 路徑不使用此 marker：
  ```
  Agent(subagent_type:"advisor-seat", model:"fable",
        description:"<fable-ok> <一句話說明這次要顧問判斷什麼>")
  ```

（2026-09-03 由一次 Fable 自審找出的其他缺陷 —— `web-cli` 收件子指令、companion 的 effort 上限、`--full` 會丟掉使用者發言 —— 都已改進正文對應步驟，不在此重複。）
