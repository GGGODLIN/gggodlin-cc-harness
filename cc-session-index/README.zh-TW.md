# cc-session-index (`ccsi`)

[English](/README.md) | 繁體中文

把本機 **Claude Code**、**Codex** 與 **Pi** 的 `.jsonl` 對話紀錄建進 SQLite FTS5（`tokenize='trigram'`）全文索引，並提供跨工具的正規化 JSONL 事件流。全靠單一 Python 標準庫腳本運作，不裝第三方套件。

對話紀錄累積到幾十 GB 之後，每次回頭找舊結論都跑 `grep -r` 會慢到打斷工作。現成的對話記憶工具不是用 SQLite 預設的 `unicode61` 分詞（切不出中文子字串），就是綁了純英文的 embedding 模型。

在作者的機器上（`44 GB`、`53,016` 個 `.jsonl` 檔、`150 萬`列索引紀錄，SQLite 檔 `3.5 GB`，2026-10-19 量測），首次全量建庫耗時 `371.5 秒`，日常增量更新約 `0.6～6.0 秒`。

## 運作方式

1. `ccsi index` 掃描三個工具的對話目錄，為每個檔案記錄 `(mtime, size, offset, ino, rows)`。檔案在同一 inode 下長大時，直接跳到上次的位元組 `offset` 只讀新增行；若寫入端還沒補上結尾換行，游標會停在該行起點留待下次重讀。
2. 對話文字寫入 FTS5 `trigram` 表，同時在普通表 `message_refs(mid, path)` 記下檔案與列號對應，讓單檔重算與 `-C` 前後文查詢直接走索引，不必全表掃描 FTS5。
3. 工具呼叫會抽出可搜尋的關鍵參數（`Read`／`Edit`／`Write`／`NotebookEdit` 的檔案路徑、`Bash` 指令、`Grep`／`Glob` 條件、`Skill` 名稱與參數、`Agent`／`SendMessage` 提示詞）。沒有內容的空工具列（`input: {}`）、Skill 展開的整份說明書（`Base directory for this skill:`）與 `<system-reminder>` 會略過；手動斜線指令（`<command-name>`）與背景任務結果（`<task-notification>`）則保留。
4. `ccsi events` 讀取同一批對話檔，一行輸出一個正規化事件，讓跨工具統計不用分別寫三套解析器。

| vendor | 預設根目錄（可覆寫環境變數） | 格式 |
|---|---|---|
| `cc` | `~/.claude/projects/**/*.jsonl`（`$CLAUDE_CONFIG_DIR/projects`，自動排除 `codex/` 鏡像子樹） | 一行一則 `type=user/assistant`＋`message` |
| `codex` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`、`~/.codex/archived_sessions/rollout-*.jsonl`（`$CODEX_HOME`） | 一行一則 `session_meta／turn_context／response_item／event_msg`＋`payload` |
| `pi` | `~/.pi/agent/sessions/**/*.jsonl`（`$PI_CODING_AGENT_DIR/sessions`） | 一行一則 `session／model_change／message` |

## 安裝與接線

需要 Python 3.9+ 且連結的 **SQLite 為 3.34.0+**（支援 FTS5 `trigram`，macOS Homebrew Python 與主流 Linux 發行版皆已內建），不需安裝任何第三方套件：

```sh
git clone https://github.com/GGGODLIN/cc-session-index.git
mkdir -p ~/.local/bin
ln -s "$PWD/cc-session-index/ccsi" ~/.local/bin/ccsi
# 確認 ~/.local/bin 已加入 PATH（例如 export PATH="$HOME/.local/bin:$PATH"）
ccsi index
```

### 寫入 Claude Code 路由規則（`~/.claude/CLAUDE.md` 或 `rules/common/code-search.md`）

光把 `ccsi` 放進 `PATH`，模型不會自己想到要呼叫它。在作者的環境裡，還沒寫進規則的 8 月整月只被呼叫 15 次；寫入 `code-search.md` 後，9～10 月在 429 個獨立對話裡被呼叫了 2,569 次。在全域規則加入這一段即可：

```markdown
- **Session 歷史檢索**（我之前怎麼做的、上次為什麼放棄某做法、某決策發生在哪個 session）→ `ccsi search "<query>" -k 5`（加 `-C 2` 展開同檔前後已索引紀錄、加 `--exclude-session <UUID前綴>` 排除當前 session、加 `--vendor {cc,codex,pi}` 篩來源）。SQLite FTS5 全文索引（若已設定排程則自動增量，剛發生的對話若未入庫可先 `ccsi index`）。trigram tokenizer：查詢至少要有一個 `>=3` 字元的詞或雙引號片語（如 `ccsi search '"測試 假綠"'`；純 2 字中文詞會報錯 exit 2），且多詞必須在同一則訊息共現（不確定時拆成多次短查詢）。需要看未入 FTS 的 `tool_result`（單筆上限 8,000 字）時用 `ccsi events --session <id>`，超過上限則讀命中原檔。
```

## 用法

```sh
ccsi index                                          # 建立或增量更新索引（三個 vendor 都掃）
ccsi index --vendor codex                           # 只掃指定 vendor（cc / codex / pi）

ccsi search "查詢字串" -k 10                         # 全文檢索（64-trigram 摘要，約 66 個中文字）
ccsi search "Herdr 左下角 狀態" -C 2                 # 印出命中列同檔案前後各 2 筆已索引紀錄（各 300 字）
ccsi search '"測試 假綠"' -k 5                       # 以雙引號將兩個 2 字中文詞包成 5 字元片語送進 FTS5
ccsi search "advisor.md" --exclude-session 94c245bb # 排除指定 session
ccsi search "查詢字串" --vendor pi                   # 限定單一 vendor

ccsi events --vendor codex --since 2026-09-13 --kind tool_call --tool spawn_agent
ccsi events --session 97ac80ca --kind text
```

`events` 每行欄位：`vendor、session、path、ts、cwd、role、kind（text｜tool_call｜tool_result｜session_meta｜turn_context）、text`（單筆截斷上限 8,000 字），加上 `tool`、`model`；CC 的 Agent 呼叫多帶 `agent_type`／`agent_model`、Skill 呼叫帶 `skill`；Codex 多帶 `effort`、子 thread 的 `agent_role`（來自 `session_meta.source.subagent`）、`spawn_agent` 的 `agent_type`。Codex 子 agent 的真實模型只信 `turn_context`（會跟在同 session 的後續事件 `model` 欄），不信它自報的文字。

- 索引預設落點（自動設為目錄 `0700`、檔案 `0600` 私密權限）：
  - macOS：`~/Library/Caches/cc-session-index/index.sqlite`
  - Linux／其他：`${XDG_CACHE_HOME:-~/.cache}/cc-session-index/index.sqlite`（僅接受絕對路徑之 `XDG_CACHE_HOME`）
  - 自訂覆寫：設定環境變數 `CCSI_DB_DIR=/path/to/dir`
- 並發安全：`ccsi index` 在讀取檔案狀態前會對 `<DB_DIR>/index.lock` 取得 `flock` 獨占鎖
- 定時背景增量更新（選用）：macOS `LaunchAgent`（`StartInterval=900`）與 Linux `crontab` 設定範例見英文版 [README.md](/README.md) 的 `Scheduled Background Refresh` 小節

## 已知限制

- FTS5 `trigram` 要求查詢裡至少有一個 3 字元以上的詞或雙引號片語（如 `ccsi search '"測試 假綠"'`）。只含 1～2 字元的查詢（或含 `< 3` 字運算元的布林／引號查詢）會回傳 `exit 2` 並印出說明，不會假裝成 `(no hits)`；一般空白分隔的長短詞混搜則會自動對短詞補上 `LIKE` 過濾。
- FTS 表不收錄 `tool_result` 輸出，只收錄對話文字（上限 8,000 字）與 `tool_use` 參數摘要（上限 2,000 字）。要看工具輸出可用 `ccsi events --session <id> --kind tool_result`（單筆上限 8,000 字），超過上限時直接讀 `.jsonl` 原檔。
- 增量更新假設既有 `.jsonl` 只往後追加（`st_ino` 未變且 `st_size` 變大），且不會自動刪除已從磁碟移除的舊檔紀錄；需要完整清理時，刪掉 `index.sqlite` 再跑一次 `ccsi index`。

## 測試

```sh
python3 test_ccsi.py -v
```

## 授權

[MIT](/LICENSE)
