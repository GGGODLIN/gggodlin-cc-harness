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
