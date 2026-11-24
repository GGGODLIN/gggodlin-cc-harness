# cc-session-index (`ccsi`)

[English](/README.md) | 繁體中文

把本機 **Claude Code**、**Codex** 與 **Pi** 的 `.jsonl` 對話紀錄建進 SQLite FTS5（`tokenize='trigram'`）全文索引，並提供跨工具的正規化 JSONL 事件流。全靠單一 Python 標準庫腳本運作，不裝第三方套件。

https://github.com/user-attachments/assets/4cd592d2-1cb5-4b1a-a1f0-5212c901bb6f

影片裡的對話是虛構的。0.05 秒是在作者的真實索引上跑同一句搜尋的耗時（2026-10-20，含 Python 啟動）。

對話紀錄累積到幾十 GB 之後，每次回頭找舊結論都跑 `grep -r` 會慢到打斷工作。現成的對話記憶工具不是用 SQLite 預設的 `unicode61` 分詞（切不出中文子字串），就是綁了純英文的 embedding 模型。

在作者的機器上（2026-11-19 量測），`index.sqlite` 從 v2 的 `17.2 GB`（`6,327,719` 列）降到 v3 的 `3.09 GB`（`70,212` 個檔、`2,176,258` 列）。升級前，v2 的 `files` 表有 `207,509` 筆路徑，實際只有約 `70,000` 個 `.jsonl` 檔。大多數路徑是同一批檔案透過不同設定目錄重複建索引，或指向已刪除的檔案。v3 的 `dbstat` 顯示 trigram 索引資料占 `2.888 GB`、`message_refs` 占 `0.107 GB`，其餘各表合計約 `0.1 GB`。整套重建掃描 `70,202` 個檔，耗時 `466.8 秒`。增量更新約 `2 秒`。

## 運作方式

1. `ccsi index` 掃描三個工具的對話目錄，為每個檔案記錄 `(mtime, size, offset, ino, rows)`。如果檔案在同一 inode 下長大且已有位移紀錄，就從上次的位元組 `offset` 只讀追加內容。如果最後一筆 JSON 尚未寫完，游標會留在該筆開頭，等下次重讀。如果 Claude Code 設定目錄的 `projects` 是符號連結，`ccsi` 會跟到它指向的位置，讓指向同一對話目錄的帳號在同一份索引中共用同一組紀錄。
2. FTS5 的 `messages` 表用 `tokenize='trigram'`、`content=''` 和 `contentless_delete=1` 建立索引，不存訊息全文。每個檔案的路徑只在 `paths` 表存一次，`message_refs` 記錄每列的檔案編號、檔內序號、時間與角色。
3. 文字抽取會保留對話文字，並摘要可搜尋的工具參數，例如檔案路徑、終端機指令、搜尋條件、Skill 名稱與參數、agent 提示詞。沒有可搜尋文字的工具呼叫、展開的 Skill 說明與多數 `<system-reminder>` 區塊會略過。斜線指令和背景任務通知的摘要與結果會保留。
4. `ccsi search` 將每個候選 `.jsonl` 原檔讀取一次，用建索引時的同一套邏輯重算命中文字，再放入記憶體中的臨時 FTS5 表，呼叫 SQLite 的 `snippet()`。如果文字和查詢相同，產生的摘錄會與 v2 逐字一致。
5. `ccsi events` 讀取同一批對話檔，每行輸出一個正規化 JSONL 事件，讓 `jq` 能查詢三種工具的對話紀錄。

| vendor | 預設根目錄（可覆寫環境變數） | 格式 |
|---|---|---|
| `cc` | `~/.claude/projects/**/*.jsonl`（`$CLAUDE_CONFIG_DIR/projects`，自動排除 `codex/` 鏡像子樹） | `type=user/assistant`＋`message` |
| `codex` | `~/.codex/sessions/**/*.jsonl`、`~/.codex/archived_sessions/**/*.jsonl`（`$CODEX_HOME`） | `session_meta`／`turn_context`／`response_item`＋`payload` |
| `pi` | `~/.pi/agent/sessions/**/*.jsonl`（`$PI_CODING_AGENT_DIR/sessions`） | `session`／`model_change`／`message` |

## 安裝與接線

需要 Python 3.9+ 且連結的 **SQLite 為 3.43+**，並支援 FTS5 `trigram`。索引用到的 `contentless_delete` 從 SQLite 3.43 起才支援。不需安裝任何第三方套件。

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
- **Session 歷史檢索**（我之前怎麼做的、上次為什麼放棄某做法、某決策發生在哪個 session）→ `ccsi search "<query>" -k 5`（加 `-C 2` 展開同份對話檔的前後文、加 `--exclude-session <UUID 前綴>` 排除當前 session、加 `--vendor {cc,codex,pi}` 篩來源）。SQLite FTS5 `trigram` 需要至少一個 3 字元以上的詞或雙引號片語（如 `ccsi search '"測試 假綠"'`）。如果找不到剛發生的對話，先跑 `ccsi index`。不確定多個概念是否出現在同一則訊息時，拆成幾次查詢。要看未入索引的 `tool_result`，用 `ccsi events --session <id>`（單筆上限 8,000 字元），或直接讀對話原檔。
```

## 用法

```sh
ccsi index                                          # 建立或增量更新索引（三個 vendor 都掃）
ccsi index --vendor codex                           # 只掃指定 vendor（cc / codex / pi）

ccsi search "查詢字串" -k 10                         # 全文檢索（64-trigram 摘要，約 66 個中文字）
ccsi search "Herdr 左下角 狀態" -C 2                 # 顯示同檔案中命中列前後各最多 2 筆訊息
ccsi search '"測試 假綠"' -k 5                       # 以雙引號將兩個 2 字中文詞包成 5 字元片語送進 FTS5
ccsi search "advisor.md" --exclude-session 94c245bb # 排除指定 session
ccsi search "查詢字串" --vendor pi                   # 限定單一 vendor

ccsi events --vendor codex --since 2026-09-13 --kind tool_call --tool spawn_agent
ccsi events --session 97ac80ca --kind text
```

`events` 輸出 `vendor`、`session`、`path`、`ts`、`cwd`、`role`、`kind`、`text`（最多 8,000 字元）和 `model`，適用的事件另帶 `tool`。Claude Code 的 `Agent` 呼叫另帶 `agent_type` 和 `agent_model`，`Skill` 呼叫另帶 `skill`。Codex 另帶 `effort`、取自 `session_meta` 的子 agent `agent_role`，以及 `spawn_agent` 的 `agent_type`。Codex 從 `turn_context` 讀取模型名稱，沿用到後續事件。

- 索引預設落點（自動設為目錄 `0700`、檔案 `0600` 私密權限）：
  - macOS：`~/Library/Caches/cc-session-index/index.sqlite`
  - Linux／其他：`${XDG_CACHE_HOME:-~/.cache}/cc-session-index/index.sqlite`（僅接受絕對路徑之 `XDG_CACHE_HOME`）
  - 自訂覆寫：設定環境變數 `CCSI_DB_DIR=/path/to/dir`
- `ccsi index` 會持有 `<DB_DIR>/index.lock` 的 `flock` 獨占鎖。如果資料庫結構或文字抽取版本變更，請執行不帶 `--vendor` 的 `ccsi index`，從所有設定的來源重建。程式會先在同一目錄建立新索引，完成後在鎖內原子換上。重建期間仍可搜尋舊索引。
- 定時背景增量更新（選用）：macOS `LaunchAgent`（`StartInterval=900`）與 Linux `crontab` 設定範例見英文版 [README.md](/README.md) 的 `Scheduled Background Refresh` 小節

## 已知限制

- FTS5 `trigram` 需要至少一個 3 字元以上的詞或雙引號片語。如果查詢只有短詞，或在 FTS 語法中使用不到 3 字元的運算元，會以狀態碼 `2` 結束。如果用空白分隔長短詞，FTS5 先以長詞比對，依排名傳回候選。`ccsi` 重算候選文字後，用 Python 確認每個短詞都出現在同一列，直到湊足指定筆數或用完候選。
- v3 的 FTS 表只有 `text` 一欄，不支援 `path:`、`role:` 等欄位篩選。可用 `--vendor` 限定來源，或用 `--exclude-session` 按路徑子字串排除 session。
- 對話文字每列最多取 8,000 字元建索引，工具呼叫摘要每列最多取 2,000 字元。要看未入索引的 `tool_result` 輸出，可用 `ccsi events --session <id> --kind tool_result`（單筆上限 8,000 字元），或直接開啟 `.jsonl` 原檔。
- 增量執行 `ccsi index` 時，會清除本次掃描範圍內確認已刪除的檔案紀錄。如果整個來源根目錄不存在，就保留該來源的索引紀錄。
- 如果原檔已刪除、讀不到、比建索引時小，或 inode 已變，搜尋會跳過該檔的命中，依排名用下一筆可用候選補上。`-C` 從原檔讀取相鄰列，因此追加的新列可先出現在前後文中，等跑過 `ccsi index` 後才成為搜尋命中。

## 測試

```sh
python3 test_ccsi.py -v
```

## 授權

[MIT](/LICENSE)
