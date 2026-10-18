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

- 多行文字用 `agent prompt` 會被拆成多次送出，worker 只看到第一段。brief 一律寫檔，prompt 只送「讀 <檔> 照做」。
- `pane send-text` 與 `agent send-keys` 是備用，不帶狀態等待。
- `--wait --until working` 確認 worker 收到並開始動；沒等到就是沒送進去。

## 生命週期

- 主機重開後 herdr 會把 tab、agent 名與 session 接回來，watcher 不會；重開後對每個還在跑的 worker 重掛 watcher。
- Claude Code 的 scratchpad 目錄是 session 級，`/resume` 會清空。brief、收據、watch-log 不放那裡。
- 已進「Usage limit reached · continuing at HH:MM」的 worker 不會吃到 main 的 `/login` 切帳號；要 `/exit` 後在同一 pane `claude --resume <session id>`。

## 新 worktree 的信任確認框（2026-09-22 實測）

- 對從未開過 Claude Code 的目錄（新建 worktree 必中）起 worker，CC 會先跳「Is this a project you created or one you trust?」確認框，agent 狀態是 `blocked`；`start-worker.sh` 的 `agent prompt --wait --until working` 會回 `agent_not_ready … blocked during startup`，然後把 tab 關掉、整個失敗。
- 手動補法：自己 `herdr tab create` → `herdr agent start`，`herdr pane read <pane_id>` 看到確認框後 `herdr pane send-keys <pane_id> Down` 再 `Enter`（預設游標在「No, exit」），狀態轉 `idle` 後照 Step 2 送 brief、手掛 `agent-watch.sh`。
- 預防法：起 worker 前在對應 config dir 的 `.claude.json` 把 `projects["<worktree>"].hasTrustDialogAccepted` 設 true（CC 自己的錯誤訊息就這樣建議）。尚未做進 `start-worker.sh`。

## 模型旗標

- `--model 'opus[1m]'` 在 zsh 要單引號，方括號會被當 glob。
- 起 agent 後 `herdr agent list` 的 `agent_session.value` 就是 Claude Code session id。

## Codex 與 pi worker（2026-10-18 實測，herdr 0.9.5、codex-cli 0.159.3、pi 1.3.0）

### 狀態與 session

- Codex：`herdr agent start --kind codex` 成功後狀態是 `done`，`agent_session` 是 null；送出第一則 prompt、狀態轉 `working` 的當下仍是 null，約 2 秒後才出現 `{"kind":"id","source":"herdr:codex","value":"<uuid>"}`。所以 Codex 要在送 brief 之後輪詢 `agent list` 取 session，不能照 CC 在送 brief 前取。回合結束狀態回到 `done`。
- pi：帶 `--session-id <uuid>` 啟動，`agent start` 回傳時狀態就是 `idle`，`agent_session` 立即可得，但 `kind` 是 `path`，`value` 是紀錄檔完整路徑（檔名結尾 `_<uuid>.jsonl`），不是編號。收據的 session 用 main 自己產生的 uuid，路徑另存。回合結束狀態是 `done`。
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
- Codex 對從未信任過的 repo 會跳「Trust this folder?」，狀態 `blocked`；信任寫進 `~/.codex/config.toml` 的 `[projects."<repo 根目錄>"]`，同 repo 的其他 worktree 沿用、不再跳。`-c 'projects."<root>".trust_level="trusted"'` 蓋不掉這個確認框。實測當下 `~/.claude`、`~/Desktop/work/acme` 底下兩個主 repo、`harbor-3arm` 等常用 repo 都已信任。
- pi 只有在 worktree 有 `.pi/settings.json` 等受保護資源時才跳「Trust project folder?」，而且 Herdr 這時回報 `idle`，不是 `blocked`——start-worker 會以為已就緒、把 brief 打進確認框。pi worker 一律帶 `--approve`。

### pi 環境變數與 worker 專屬重試

- pi-pick 配方的環境變數用 `herdr tab create --env KEY=VALUE` 帶進新 tab 的 shell，`agent start` 起的 pi 會繼承。
- Argon 在 pi-pick 的 relay 目錄挑得到（`cc-relay` provider 的 `google/gemini-4-argon`），不需要在全域 pi 設定補模型。
- worktree 的 `.pi/settings.json` 寫 `{"retry":{"provider":{"maxRetries":30,"maxRetryDelayMs":0}}}`：用 pi 自己的 `SettingsManager.create(cwd,{projectTrusted})` 讀，信任時 provider 重試是 30、不信任或其他目錄是預設 0；全域 `~/.pi/agent/settings.json` 前後 `cmp` 相同。
- worktree 的 `git rev-parse --git-path info/exclude` 指向主 repo 共用的 `.git/info/exclude`，寫 `/.pi/settings.json` 一行後所有 worktree 的 `git status` 都看不到它。

### 在新 tab 的 shell 送指令（2026-10-18 實測）

- `herdr pane run <pane> unset A B` 會把多個參數拼成一行指令執行；shell 已就緒時有效。
- tab 剛建、shell 還在初始化（`pane process-info` 看得到前景 bash＋zsh）時送出的 `pane run` 會整個丟失，而且 rc=0、沒有任何錯誤。所以 start-worker.sh 送 `unset …; printf 'AGENT_DISPATCH_UNSET%s\n' _DONE`，再用 `herdr pane wait-output <pane> --match AGENT_DISPATCH_UNSET_DONE --timeout 3000` 等標記，最多重送 5 次；標記用 `%s` 拆開，畫面上回顯的指令文字不會誤中。
- 實測當下新 tab 的 shell 不含任何 `ANTHROPIC_*` 變數；`tab create --env` 只能設值，清變數只能靠上面的 `pane run`。
