# herdr 行為筆記（`--help` 查不到的部分）

實測環境 2026-09-10，macOS、herdr 由 `HERDR_ENV=1` 的 pane 內呼叫。

## 狀態語意

- worker 用文字問問題、等答案時，狀態是 `idle`，不是 `blocked`。`blocked` 只認權限框與選擇 UI。所以等待一律 `--until idle --until blocked --until done` 三個都帶。
- `agent wait` 不帶 `--timeout` 就無限等；Bash tool 自己有 600000 ms 上限，所以無限等要放 `nohup` 背景，不放 Bash 前景。
- `agent read --source recent` 在 worker working 時回 `agent_not_idle`；要看歷史改讀 `~/.claude/projects/<路徑編碼>/<session>.jsonl`，路徑編碼是把絕對路徑的非字母數字全換成 `-`。`--source visible` 隨時可讀，但只有螢幕那一頁。

## 從 nohup 殼呼叫 herdr

- nohup 殼沒有 UTF-8 locale，帶中文的參數會被拒 `argument N is not valid UTF-8`。腳本開頭 `export LC_ALL=en_US.UTF-8`，而且送給 main 的喚醒訊息用 ASCII。
- macOS 沒有 `setsid`；`nohup … & disown` 就夠。
- watcher 被 kill 時 `agent wait` 回 rc ≥ 128，這時不要送喚醒，否則 main 會收到假訊號。

## 送字進 worker

- `start-worker.sh` 從檔案準備首則訊息，將它以單一位置參數交給啟動中的 agent。舊版 Herdr 用 `pane run` 送啟動命令，Core 用 `hc send` 送啟動命令，兩者都在確認首輪活動後才掛 watcher。
- 如果 pi 的 inline brief 以 `@` 開頭，呼叫端先在檔案加上 `[main]` 標頭。`start-worker.sh` 會在建窗前直接拒絕以 `@` 開頭的 pi inline brief，因為 pi 會將該參數視為檔案引用。

## 生命週期

- 主機重開後 herdr 會把 tab、agent 名與 session 接回來，watcher 不會；重開後對每個還在跑的 worker 重掛 watcher。
- Claude Code 的 scratchpad 目錄是 session 級，`/resume` 會清空。brief、收據、watch-log 不放那裡。
- 已進「Usage limit reached · continuing at HH:MM」的 worker 不會吃到 main 的 `/login` 切帳號；要 `/exit` 後在同一 pane `claude --resume <session id>`。

## 新 worktree 的信任確認框（2026-09-22 實測、2026-11-23 更新）

- Claude Code 在新 worktree 跳「Yes, I trust this folder」信任確認框時（預設游標在 `No, exit`），`start-worker.sh` 的 `herdr-core` 在首輪輪詢逾時未啟動後會讀畫面，自動送出方向鍵與 Enter 代按同意並重新計算首輪啟動等待。
- 帶 `--add-dir` 開席時，代按工作目錄那個之後，每個未信任的額外目錄會再跳「Adding a new directory… Yes, add it」。`start-worker.sh` 依序代按，最多「`--add-dir` 數＋1」次；只看畫面底部最後一個確認框，捲動歷史裡已按過的不會再按。2026-11-23 實測：多 PR 審查的 Gemini Pro 席因只代按第一個而卡死。
- 若代按後仍停留在確認框或首輪未開始，`start-worker.sh` 會附註 `folder trust dialog remained active after auto-accept`，執行 `kill`＋`rm` 後再以 `hc get` 核對視窗不再為 `live`，若仍活著則如實回報 `terminal close failed`。

## 模型旗標

- `--model 'opus[1m]'` 在 zsh 要單引號，方括號會被當 glob。
- 起 agent 後 `herdr agent list` 的 `agent_session.value` 就是 Claude Code session id。

## Codex 與 pi worker（2026-10-18 實測，herdr 0.9.5、codex-cli 0.159.3、pi 1.3.0）

### 狀態與 session

- Codex：舊版 Herdr 從 `agent list` 取同一 pane 的 session。Core 從 rollout 核對工作目錄、待送出的首則 user 訊息與回合事件，續接則檢查本次附加的紀錄。
- pi：腳本以 `--session-id <uuid>` 啟動，收據記 main 產生的 UUID。舊版 Herdr 的 `agent_session.value` 是紀錄檔路徑，腳本用檔名結尾 `_<uuid>.jsonl` 核對它屬於這次啟動。
- 兩者停下時都落在 `idle`／`done`，watcher 照舊帶 `--until idle --until blocked --until done`；兩者 session 在整段實測都穩定，判定可靠。

### 紀錄位置與交付訊息

- Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-<時間>-<session>.jsonl`，用 session 編號 `find`。最後交付訊息取最後一筆 `type=event_msg`、`payload.type=task_complete` 的 `payload.last_agent_message`；或最後一筆 `type=response_item`、`payload.role=assistant` 的 `output_text`。續接後同一檔繼續 append。
- pi：`~/.pi/agent/sessions/<cwd 編碼>/<時間>_<session>.jsonl`，路徑直接由 Herdr 的 `agent_session.value` 給。最後交付訊息取最後一筆 `type=message`、`message.role=assistant` 的 `content[]` 中 `type=text` 的文字。
- 去敏感樣本在 `scripts/tests/fixtures/codex-session.jsonl`、`pi-session.jsonl`（各兩輪；兩輪回答文字相同，測「取最後一則」時要自行造變體）。

### 續接

- Codex：在原 pane 回到 shell 後 `herdr agent start <name> --kind codex --pane <pane> -- resume <session> -c check_for_update_on_startup=false --dangerously-bypass-approvals-and-sandbox`，接回同一 session 與同一檔，模型沿用原 session。實測當下沒帶 `-c`，resume 時同樣跳更新選單；`codex resume --help` 列有 `-c`。
- pi：同樣參數加 `--approve --session-id <同一 uuid>` 重開即接回同一檔。pi 要用 `/quit` 離開，Ctrl-C 只清輸入列。

### 啟動時會擋住的畫面

- Codex 每次啟動都可能先跳「Update available」選單，Herdr 回 `agent_not_ready … blocked during startup`。啟動參數加 `-c check_for_update_on_startup=false` 即不跳，不改全域設定。
- Codex 執行中跳出額度換模型選單（例如「Approaching rate limits, switch to gpt-6-luna?」）或要開 `/model` 時，`hc send --force <t> "2"` 會將文字貼入並按 Enter 誤選第 1 項，`hc send <t> "/model"` 會被包成 `<hc from=…>` 訊息送給模型。
- 針對上述互動選單與 slash command，實測須改用 `hc keys <t> <數字>` 或 `hc keys <t> / m o d e l` 再 `hc keys <t> enter` 才會觸發真實按鍵（2026-11-20 實測 `hc keys t1ss 2` 正確選中「保留目前模型」）。
- 透過 Codex 互動介面（`/model` 或額度換模型選單）切換模型時，實測會同步改寫 `~/.codex/config.toml` 的全域預設 `model` 欄位。
- Codex 對從未信任過的 repo 會跳「Trust this folder?」，狀態 `blocked`；信任寫進 `~/.codex/config.toml` 的 `[projects."<repo 根目錄>"]`，同 repo 的其他 worktree 沿用、不再跳。`-c 'projects."<root>".trust_level="trusted"'` 蓋不掉這個確認框。實測當下 `~/.claude`、`~/Desktop/work/acme` 底下兩個主 repo、`harbor-3arm` 等常用 repo 都已信任。
- 如果 worktree 有 `.pi/settings.json` 等受保護資源，pi 可能顯示「Trust project folder?」。`start-worker.sh` 以 `--approve` 啟動 pi，並將首則訊息交給 pi 的單一位置參數。

### pi 環境變數與 worker 專屬重試

- 舊版 Herdr 用 `herdr tab create --env KEY=VALUE` 將 pi-pick 配方的環境變數帶進新 tab，再用 `pane run` 執行帶 `--approve` 與首則訊息位置參數的 pi 啟動命令。
- Argon 在 pi-pick 的 relay 目錄挑得到（`cc-relay` provider 的 `google/gemini-4-argon`），不需要在全域 pi 設定補模型。
- worktree 的 `.pi/settings.json` 寫 `{"retry":{"provider":{"maxRetries":30,"maxRetryDelayMs":0}}}`：用 pi 自己的 `SettingsManager.create(cwd,{projectTrusted})` 讀，信任時 provider 重試是 30、不信任或其他目錄是預設 0；全域 `~/.pi/agent/settings.json` 前後 `cmp` 相同。
- worktree 的 `git rev-parse --git-path info/exclude` 指向主 repo 共用的 `.git/info/exclude`，寫 `/.pi/settings.json` 一行後所有 worktree 的 `git status` 都看不到它。

### 在新 tab 的 shell 送指令（2026-10-18 實測）

- `herdr pane run <pane> unset A B` 會把多個參數拼成一行指令執行；shell 已就緒時有效。
- 舊版 Herdr 在 shell 初始化時可能靜默丟掉 `pane run`。腳本先用 `pane wait-output` 等 `AGENT_DISPATCH_SHELL_READY` 標記，若配方要求 unset，就在印標記前執行。腳本只重送就緒探針，啟動命令只送一次。
- 實測當下新 tab 的 shell 不含任何 `ANTHROPIC_*` 變數；`tab create --env` 只能設值，清變數只能靠上面的 `pane run`。
