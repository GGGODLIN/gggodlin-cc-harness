# cc-session-index (`ccsi`)

[English](/README.md) | 繁體中文

單一 Python 檔案、零第三方套件依賴的 SQLite FTS5（`tokenize='trigram'`）本機對話全文索引與正規化事件流工具，涵蓋 **Claude Code**、**Codex** 與 **Pi** 的 `.jsonl` 對話紀錄。

取代對數十 GB `.jsonl` 跑全量 `grep`，也避開預設 `unicode61` 分詞器或純英文 embedding 模型無法搜尋中文子字串的問題；在約 600 行標準庫程式碼內提供中英文子字串檢索、工具檔案參數抽取、append-only 位元組增量游標與同檔前後文展開。

## 為什麼用 `ccsi`

1. **原生繁體中文／CJK 子字串檢索（`trigram`）**：直接搜 3 字以上中文詞彙、檔案路徑、函式名或錯誤訊息。
2. **百萬列秒級增量更新（append-only 位元組游標 ＋ `message_refs` 定位表）**：在作者本機 **44 GB／53,016 個 `.jsonl` 檔／150 萬列訊息**（`3.5 GB` SQLite 索引，2026-10-19 實測）上，全量重建耗時 371.5 秒，日常增量更新僅需 **0.6～6.0 秒**。
3. **高訊噪比的工具參數與控制面抽取**：索引 `Read`、`Edit`、`Write`、`NotebookEdit` 檔案路徑、`Bash` 指令、`Grep`/`Glob` 條件、`Skill` 名稱與參數，同時略過無內容空殼工具列，並過濾 `Base directory for this skill:` 展開全文與 `<system-reminder>` 雜訊。
4. **跨 Agent 統一事件流（`ccsi events`）**：將三家格式正規化為一致的 JSONL 事件流（`vendor, session, path, ts, cwd, role, kind, tool, model, text`），方便用 `jq` 做跨工具統計與治理稽核。

| vendor | 預設根目錄（可覆寫環境變數） | 格式 |
|---|---|---|
| `cc` | `~/.claude/projects/**/*.jsonl`（`$CLAUDE_CONFIG_DIR/projects`，自動排除 `codex/` 鏡像子樹） | 一行一則 `type=user/assistant`＋`message` |
| `codex` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`、`~/.codex/archived_sessions/rollout-*.jsonl`（`$CODEX_HOME`） | 一行一則 `session_meta／turn_context／response_item／event_msg`＋`payload` |
| `pi` | `~/.pi/agent/sessions/**/*.jsonl`（`$PI_CODING_AGENT_DIR/sessions`） | 一行一則 `session／model_change／message` |

## 安裝與接線

需要 Python 3.9+ 且連結的 **SQLite 為 3.34.0+**（支援 FTS5 `trigram`，macOS Homebrew Python 與主流 Linux 發行版皆已內建），不需安裝任何第三方套件：

```sh
git clone https://github.com/example-owner/cc-session-index.git
mkdir -p ~/.local/bin
ln -s "$PWD/cc-session-index/ccsi" ~/.local/bin/ccsi
# 確認 ~/.local/bin 已加入 PATH（例如 export PATH="$HOME/.local/bin:$PATH"）
ccsi index
```

### 寫入 Claude Code 路由規則（`~/.claude/CLAUDE.md` 或 `rules/common/code-search.md`）

光把 CLI 放進 `PATH`，AI 不會主動記得呼叫它（作者環境實測：未寫入規則的 8 月僅被呼叫 **15 次**；寫入 `code-search.md` 後於 9～10 月被呼叫 **2,569 次**／跨 429 個獨立對話）。建議在全域規則加入：

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

- **Trigram 最短詞長（3 字元）**：查詢至少需含一個 `>= 3` 字元的詞或雙引號片語（如 `ccsi search '"測試 假綠"'`）。純 `< 3` 字短詞（或含 `< 3` 字運算元的布林／引號查詢）會明確報錯並回傳 `exit 2`；一般空白分隔的長短詞混搜則會自動對 `< 3` 字詞附加 `LIKE` 過濾。
- **長度上限與 `tool_result`**：FTS 表不收錄 `tool_result` 輸出（僅收錄對話文字與 2,000 字以內的 `tool_use` 參數摘要）；單筆 `text` 在索引與 `ccsi events` 皆截斷於 8,000 字元，需完整長文時請直接讀取命中的 `.jsonl` 原檔。
- **Append-only 假設與已刪除檔案**：增量索引假設既有 `.jsonl` 為純追加寫入，且不自動清除磁碟上已刪除檔案的舊列（需完整清理時刪除 `index.sqlite` 重跑 `ccsi index`）。

## 測試

```sh
python3 test_ccsi.py -v
```

## 授權

[MIT](/LICENSE)
