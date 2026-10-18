# Compact Guard

Compact Guard 在原生 context 壓縮前保存一份最小、可稽核的 checkpoint，並在壓縮後的新 context 注入經過篩選的原始對話證據。它不取代原生摘要，也不嘗試同步不同產品的 session。

## 支援範圍

| 執行介面 | 轉接器 | 狀態標記 |
| --- | --- | --- |
| Claude Code | Claude | `claude-code` |
| 透過 ccp-gpt 使用 Claude Code | Claude | `ccp-gpt` |
| Codex CLI | Codex | `codex-cli` |
| 本機 Codex Desktop | Codex | `codex-desktop` |

Codex Cloud 不在支援範圍內。ccp-gpt 沿用 Claude Code 的 hook 格式；只有 `CC_VENDOR=gpt` 會把 audit 的介面標為 `ccp-gpt`，且不會略過 checkpoint，其他值仍標為 `claude-code`。

Hook 事件格式請參考 [Claude Code hooks 官方文件](https://code.claude.com/docs/en/hooks) 與 [Codex hooks 官方文件](https://learn.chatgpt.com/docs/hooks)。完整的信任邊界與繞過面分析見 [設計紀錄](/docs/design.md)。

## 第一週運作方式

第一週觀察期不修改任何產品的原生 compact prompt：

1. `PreCompact` 從原始 transcript 篩選使用者與助理文字，遮蔽常見密鑰後寫入私密 checkpoint。
2. 產品照原本方式壓縮 context。
3. `SessionStart(source=compact)` 直接讀取壓縮前 checkpoint，注入最多 8,500 個字元的恢復內容。Claude 另外可能多接一段固定標準：agent 用 📌 宣告的檔，最多 3,000 字；或是壓縮太快時的提醒。細節見 [設計紀錄的固定標準槽位](/docs/design.md)。Claude 必須由當次 transcript 明確證明屬於主 session。Codex 0.144.4 的 [hook 派送邏輯](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/hook_runtime.rs#L103-L128) 只把此事件派給根 session，並把 thread-spawn 子 agent 改派成 `SubagentStart`，所以即使執行期省略或無法再讀取 `transcript_path`，仍可從已驗證的 checkpoint 恢復。Codex 在 compact 完成時先[排入事件](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/session/mod.rs#L3070-L3073)，到下一個使用者回合建立 prompt 前才依[回合執行順序](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/session/turn.rs#L186-L192)實際派送；這條路徑不依賴 `PostCompact` 的執行順序。
4. `PostCompact` 同樣必須先證明當次 transcript 屬於主 session，才寫入不含對話內容的 audit 指標。Claude 可從 `compact_summary` 計算摘要長度與詞彙覆蓋率；Codex 的摘要內容不可讀，因此只記錄 `summaryAvailable=false`。

Codex 的人類輸入只取 `event_msg(user_message)`，助理輸出只取 `response_item(role=assistant)`。`response_item role=user` 在真實 transcript 中會夾帶 plugin 建議、`AGENTS.md` 與環境資訊等內部注入，因此全部排除。

主 session 的 `PreCompact` 無法建立有效 checkpoint 時會阻擋壓縮。非空 `agent_id`、純 Claude sidechain transcript 與 Codex subagent metadata 都會讓三個 compact hook 全部安靜跳過，避免共用父 session ID 時互相覆蓋或注入。Claude 的 `SessionStart(source=compact)` 與兩個產品的 `PostCompact` 若收到空白、無法讀取或無法證明為主 session 的 transcript，也會安靜跳過，不讀取父 checkpoint、不注入且不寫入主觀察期 audit。唯一例外是 Codex 的 compact `SessionStart`：依 [Codex 0.144.4 hook 派送邏輯](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/hook_runtime.rs#L103-L128)，它只在根 session 派送，因此可依 `vendor + session_id` 讀取已通過完整性驗證的 checkpoint，並以該 checkpoint 的 transcript 判定介面。`PostCompact` 的 audit 失敗不會阻擋工作。被注入的引文均標示為舊對話證據，不是新指令。

## 安裝與移除

本專案沒有第三方套件依賴。先執行測試，再合併 hook：

```sh
npm test
npm run check
node bin/install.mjs --install
```

安裝器只管理帶有 `compact-guard/v1/...` 識別碼的三組 hook，保留其他既有設定，並在修改既有檔案前建立權限為 `0600` 的備份。重複安裝不會新增重複項目。

Codex 安裝後仍須在 Codex CLI 與本機 Codex Desktop 開啟 `/hooks`，信任新出現的 command hash。設定檔中有 hook 不等於 hook 已獲信任或實際執行。

立即停用 Compact Guard，但保留 hook 與資料：

```sh
touch ~/.compact-guard/disabled
```

重新啟用時刪除該 `disabled` 檔案。只移除 Compact Guard 管理的 hook：

```sh
node bin/install.mjs --uninstall
```

## 狀態與隱私

| 路徑 | 內容 | 權限與限制 |
| --- | --- | --- |
| `~/.compact-guard/checkpoints/<vendor>/` | 每個 session 的 checkpoint | 目錄 `0700`、檔案 `0600`；含遮蔽後證據、原始 session ID 與完整 transcript 路徑 |
| `~/.compact-guard/audit.jsonl` | 事件、狀態、計數與雜湊 | `0600`；不含對話文字、原始 session ID 或完整 transcript 路徑 |
| `~/.compact-guard/backups/` | 安裝前的 hook 設定備份 | 目錄 `0700`、檔案 `0600` |
| `~/.compact-guard/disabled` | 全域停用旗標 | 存在時 Compact Guard 不建立或注入 checkpoint |

Checkpoint 會遮蔽 Bearer token、常見服務 token、私鑰區塊與常見密鑰欄位，但它仍是敏感資料，不應上傳或加入版本控制。audit 只接受固定欄位；錯誤訊息也不寫入原始內容。

## 觀察報告

```sh
node bin/trial-report.mjs
```

預設讀取 `~/.compact-guard/audit.jsonl`。檔案不存在時，事件與配對計數為 `0`，`maxPacketCharacters` 為 `null`，表示尚未量到任何成功 injection。也可指定其他 audit：

```sh
node bin/trial-report.mjs --audit /path/to/audit.jsonl
```

報告包含事件、狀態、產品、執行介面與觸發方式的計數，以及錯誤、阻擋、停用、無效列數、最大注入字元數與 checkpoint／injection 配對結果。每列都必須有 schema 版本、嚴格 ISO 時間、產品、執行介面與狀態，並符合該事件的必要欄位；缺少成功 injection 的封包字元數也會計為無效列。配對鍵為 `vendor + surface + sessionHash + transcriptHash`，只讓 audit 行序上較早且時間不晚於 injection 的 checkpoint 依 FIFO 一對一配對。錯序、時間倒置與多出的事件分開列為未配對，不會用後來的 checkpoint 回填先前 injection。遭竄改的值會計為無效列，不會原樣出現在報告的 JSON 鍵或內容中。

Codex 在畫面顯示 compact 完成後、下一個使用者回合開始前，checkpoint 尚未配對屬於預期的暫時狀態。必須送出下一個回合，看到 `SessionStart` 完成後再判斷是否漏派；若 session 在 compact 後直接關閉，該 checkpoint 應維持未配對並列入觀察，而不是假設已完成注入。

Claude Code 與 ccp-gpt 可能先派送 `PreCompact`，再以 `Not enough messages to compact` 拒絕過早的手動壓縮。這會留下沒有後續 injection 的 checkpoint。觀察報告應以產品畫面確認該次壓縮是否真的完成，將這類原生拒絕另行註記；不可把它算成已完成壓縮的漏注入，也不可從 audit 靜默刪除。

## 驗證

```sh
node --test test/trial-report.test.mjs
npm test
npm run check
git diff --check
```

永久回歸案例分為三組：known-good 驗證決策與限制能保存；known-bad 驗證密鑰、工具結果與子 agent 對話不會提升成恢復內容；boundary 驗證重複資料、衝突順序、未完成 JSONL 與 8,500 字元上限。案例分布在 [文字處理測試](/test/text.test.mjs)、[transcript 測試](/test/transcript.test.mjs) 與 [固定 transcript](/test/fixtures/)。
