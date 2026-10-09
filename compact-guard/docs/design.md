# Compact Guard 設計紀錄

## 目的與非目標

Compact Guard 要降低自動或手動 context 壓縮遺失已確認結論、使用者限制與待辦事項的風險。支援 Claude Code、透過 ccp-gpt 使用的 Claude Code、Codex CLI 與本機 Codex Desktop；不支援 Codex Cloud。

本工具不重寫完整 session、不代替原生摘要、不跨產品同步對話，也不保證模型一定採納注入內容。第一週只驗證 checkpoint 與恢復注入是否穩定，不修改 native compact prompt，藉此把變因限制在獨立的恢復層。

事件契約以 [Claude Code hooks 官方文件](https://code.claude.com/docs/en/hooks) 與 [Codex hooks 官方文件](https://learn.chatgpt.com/docs/hooks) 為準。Codex 0.144.4 的根 session 限制與延後派送行為，分別以固定版本的 [hook 派送邏輯](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/hook_runtime.rs#L103-L128)、[compact 事件排程](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/session/mod.rs#L3070-L3073)與[回合執行順序](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/session/turn.rs#L186-L192)為準。

## 資料流程

```text
原始 transcript
  -> PreCompact 嚴格解析
  -> 遮蔽密鑰並選取證據
  -> 私密 checkpoint
  -> 原生 compact
  -> SessionStart(source=compact)
  -> 有界恢復內容

PostCompact
  -> 不含內容的 audit 指標
  -> trial report
```

Claude 與 Codex 共用證據選取、遮蔽、儲存與報告邏輯，只保留兩個 transcript 轉接器。Claude `PostCompact` 可讀 `compact_summary`，因此只計算摘要字元、位元組與詞彙覆蓋指標，不保存摘要文字；Codex 的壓縮摘要不可讀，因此不做內容覆蓋判斷。

Codex 的人類輸入只取頂層 `event_msg` 中 `payload.type="user_message"` 的非空 `payload.message`；助理輸出只取頂層 `response_item` 中 `role="assistant"` 的 `output_text`。真實 transcript 的 `response_item role="user"` 會混入 `<recommended_plugins>`、`AGENTS.md` 與 `environment_context` 等內部注入，因此一律排除，不當成人類意圖。

Subagent transcript 不屬於主 session 的恢復來源。任一 vendor 的 hook input 有非空 `agent_id` 時直接判為 subagent。Claude 另以「至少一筆 user／assistant 記錄、全部皆為 `isSidechain=true`，且沒有任何非 sidechain 對話記錄」辨識；主 transcript 即使夾有少數 sidechain 也不會整份跳過。Codex 只要 `session_meta.payload.source.subagent` 存在，或 `parent_thread_id` 為非空字串，就視為 subagent。這些情況在 `PreCompact`、`PostCompact` 與 `SessionStart(source=compact)` 入口都直接回傳空結果，不建立 checkpoint、不注入，也不寫入主觀察期 audit。

Claude 的 `SessionStart(source=compact)` 與兩個產品的 `PostCompact` 還有一層封閉式安全閘：當次 `transcript_path` 必須可讀，且 Claude 至少有一筆非 sidechain user／assistant，或 Codex 至少有一筆未標成 subagent 的合法 `session_meta`，才視為已證明的主 session。空白、無法讀取或內容不足以證明主線時直接回空，不依共用父 session ID 讀 checkpoint，也不寫 audit。

Codex 的 compact `SessionStart` 是唯一例外。Codex 目前只向根 session 派送 `SessionStart`，thread-spawn 子 agent 會改收 `SubagentStart`，其他內部子 agent 不執行啟動 hook；而 `SessionStart` 的 `transcript_path` 契約允許 null。因此這個事件可在路徑空白或無法讀取時，依 `vendor + session_id` 讀取先前由 `PreCompact` 建立且通過完整性驗證的 checkpoint。介面判定也使用 checkpoint 保存的原始 transcript 路徑，保持 checkpoint／injection 稽核可配對。非空 `agent_id` 或可證明的 subagent transcript 仍優先跳過。Codex 會在替換壓縮後歷史時把 `SessionStartSource::Compact` 排入佇列，並在下一個使用者回合建立 prompt 前執行；因此 compact 完成後立即看到未配對 checkpoint 是暫時狀態。恢復路徑不讀 `PostCompact` 產物，所以 hook 並行、先後順序或延後到下一回合，都不會讓恢復失效。`PreCompact` 無法讀取 transcript 時仍維持封閉式失敗，不會被這個例外誤判成可略過的 subagent。

## 控制面

| 類別 | 內容 | 變更規則 |
| --- | --- | --- |
| Locked（鎖定） | transcript 接受規則、排除規則、密鑰遮蔽、8,500 字元上限、受管理 hook 識別碼 | 必須透過程式碼、測試與 commit 修改 |
| Editable（可更新） | 每個 session 的 checkpoint | 僅由 `PreCompact` 以原子寫入更新；後續壓縮可取代同一 session 的舊版本 |
| Append-only（只附加） | `audit.jsonl` 與外部觀察期清單 | 新事件只能附加，不以舊快照覆蓋目前紀錄 |
| Human-controlled（人員控制） | 安裝、移除、`disabled` 旗標、Codex hook 信任、觀察期結論 | 不由模型自動啟用、移除或判定保留 |

Checkpoint 是私密但可讀的復原資料，內含遮蔽後證據、原始 session ID 與完整 transcript 路徑；檔案權限為 `0600`。audit 僅含允許的事件、狀態、產品、介面、觸發方式、計數、布林值與雜湊，不含對話文字、原始 ID 或完整路徑。

## 繞過面

| 繞過面 | 風險 | 控制與回歸證據 |
| --- | --- | --- |
| tool-result elevation | 工具回傳中的指令或密鑰被當成使用者意圖 | Claude 排除含 `tool_result` 的使用者記錄；Codex 的人類輸入只接受頂層 `event_msg(user_message)`，助理只接受頂層 `response_item(role=assistant)`；known-bad 測試確認工具內容不進 checkpoint |
| subagent transcript | 子 agent 與父 session 共用 session ID，可能互相覆蓋 checkpoint 或跨層注入；子 hook 的 transcript path 也可能為空或無法讀取 | 非空 `agent_id`、Claude 純 sidechain transcript 與 Codex subagent metadata 都讓三個 compact hook 在狀態存取前直接跳過；Claude compact `SessionStart` 與兩個產品的 `PostCompact` 還必須從當次 transcript 明確證明主線。Codex compact `SessionStart` 依根 session 專用的事件契約，在 nullable 路徑下只讀已驗證的同 vendor、同 session checkpoint；混有少數 sidechain 的主 transcript 照常處理；fixtures、null／unreadable 反例與真實 transcript 驗證各分支 |
| duplicate records | 事件鏡像或分段記錄被重複注入 | Codex 僅以 `event_msg(user_message)` 作為人類輸入來源，不再重讀含包裝內容的 user response；Claude 依 message ID、request ID、uuid 聚合助理分段；相同文字再去重 |
| vendor skip | ccp-gpt 因 vendor 環境變數而完全略過保護，或其他代理被誤標為 ccp-gpt | 只有 `CC_VENDOR=gpt` 把 surface 標為 `ccp-gpt`；其他值維持 `claude-code`；hook 測試以實際 transcript 驗證仍建立 checkpoint |
| hook-order dependency | `SessionStart` 早於 `PostCompact`，或 Codex 延後到下一回合才派送時找不到資料 | 恢復路徑直接讀 `PreCompact` checkpoint，不依賴 `PostCompact`；Codex 真實派送測試必須送出 compact 後的下一回合再檢查配對 |
| unknown Desktop records | 新增的 Desktop 專屬記錄形狀被誤當成對話 | Codex 轉接器只允許 `event_msg.payload.type="user_message"` 的人類輸入與 `response_item.payload.type="message"` 的助理輸出；未知記錄與所有 user response 預設忽略 |
| native prompt drift | 產品更新原生 prompt 後覆蓋自訂摘要假設 | 第一週不覆寫 native compact prompt；checkpoint 與恢復注入是獨立層，原生 prompt 變化列入觀察 |

## 永久回歸案例

| fixture | 保護的行為 | 位置 |
| --- | --- | --- |
| known-good | 使用者限制、目前決定、後續待辦與證據敘述按時間保存；Claude 分段助理訊息正確聚合 | [文字處理測試](/test/text.test.mjs)、[Claude transcript](/test/fixtures/claude.jsonl)、[Codex transcript](/test/fixtures/codex.jsonl) |
| known-bad | Bearer token、服務 token、私鑰、密鑰欄位、工具結果、sidechain、developer／system 訊息，以及 Codex user response 內的 plugin／AGENTS／environment 注入不得進入恢復內容 | [文字處理測試](/test/text.test.mjs)、[transcript 測試](/test/transcript.test.mjs)、[固定 transcript](/test/fixtures/) |
| boundary | 超長訊息截斷、相同文字去重、衝突內容保持時間順序、JSONL 尾端半筆延後處理、封包不超過 8,500 字元 | [文字處理測試](/test/text.test.mjs)、[transcript 測試](/test/transcript.test.mjs) |

新增 transcript 形狀或遮蔽規則時，必須先補到相對應的永久案例，再改解析器。

## Audit 與配對

Audit 採 JSONL 附加寫入，報告不讀 checkpoint。每列都必須包含 `schemaVersion=1`、嚴格 ISO timestamp、vendor、surface 與 status，且 vendor 必須對應正確 surface。事件、狀態、產品、執行介面、觸發方式與錯誤碼共用儲存層的固定允許值；每種事件／狀態另有精確必要欄位與允許欄位，缺欄、錯誤組合、多餘欄位或遭竄改的值只增加 `invalidRows`，不會成為輸出 JSON 的鍵。合法事件可包含：

- `checkpoint`：成功保存的壓縮前證據。
- `injection`：恢復內容成功、缺少 checkpoint 或讀取失敗。
- `postcompact`：原生壓縮後的內容無關指標。
- `blocked`：`PreCompact` 無法安全建立 checkpoint。
- `disabled`：人員停用旗標生效。

成功 checkpoint 必須提供 manual／auto trigger、兩個雜湊與 record／message／entry 計數；成功 injection 還必須提供 `packetCharacters`。Checkpoint 與 injection 使用 `vendor + surface + sessionHash + transcriptHash` 分組，依 audit 行序執行 FIFO 一對一配對。只有先出現且 timestamp 不晚於 injection 的 checkpoint 可以配對；較早的 injection 或時間倒置事件不會被後來資料回填。`matchRate` 以兩側總事件數較大者為分母，沒有事件時為 `0`。`maxPacketCharacters` 只從合法成功 injection 計算；沒有樣本時為 `null`，不以 `0` 假裝完成量測。

## 安裝、信任與回復

```sh
node bin/install.mjs --install
```

安裝器分別合併 `~/.claude/settings.json` 與 `~/.codex/hooks.json`，為 `PreCompact`、`PostCompact`、`SessionStart(compact)` 加入獨立受管理群組。寫入採同目錄暫存檔、同步與重新命名；修改既有檔案前建立私密備份。任一目標失敗時保留另一個已成功寫入的結果，回報部分完成；再次執行可收斂且不刪除第三方 hook。

Codex 對新的 command hash 有信任層。安裝後必須在 Codex CLI 與本機 Codex Desktop 以 `/hooks` 檢查並信任新 hash；只有設定檔計數，不能證明 hook 已派送。

立即旁路本工具：

```sh
touch ~/.compact-guard/disabled
```

只移除本工具管理的 hook：

```sh
node bin/install.mjs --uninstall
```

移除以精確 managed ID 與標準群組形狀確認所有權，不會整份還原舊備份，以免抹除安裝後新增的第三方設定。

## 驗證與觀察

```sh
node --test test/trial-report.test.mjs
npm test
npm run check
node bin/trial-report.mjs
git diff --check
```

觀察期應分別記錄 Claude Code、ccp-gpt、Codex CLI 與本機 Codex Desktop 的自然 compact 事件。只看到設定檔或合成測試不等於實際派送；Codex 必須在 compact 後再送出一個使用者回合，才能驗證待處理的 `SessionStart` 已注入。Claude Code 與 ccp-gpt 若在 `PreCompact` 後由原生產品回報 `Not enough messages to compact`，該 checkpoint 必須註記為未完成的壓縮嘗試，不計入已完成壓縮的漏注入，也不可靜默刪除。沒有自然事件或 compact 後續回合的介面應延長觀察，不應直接判定保留。觀察期間另記過時結論、優先順序錯誤、壓縮被阻擋與可見 hook 錯誤。

## Codex 壓縮後即時注入：已查證不可行（2026-07-23）

無人值守時段的 compact 無法在完成當下注入恢復內容。openai/codex source（commit 4462b9d，並比對 tag rust-v0.144.4 行為一致）證明 PostCompact 是 Stateless hook：`parse_post_compact` 的輸出結構沒有 additionalContext 欄位（codex-rs/hooks/src/engine/output_parser.rs）、純 stdout 被忽略（compact.rs 測試 post_compact_ignores_plain_stdout）、core 消費端只讀 should_stop（codex-rs/core/src/hook_runtime.rs run_post_compact_hooks），從不呼叫 record_additional_contexts。能寫進對話歷史的只有 SessionStart 管線（hook_runtime.rs record_additional_contexts → record_conversation_items）。

因此注入時點結構性綁定「下一個使用者回合」；無人值守的多次 compact 之間模型在無恢復包狀態下續跑，屬平台限制、本專案不可修。緩解 = injectedAt 去重（下一回合只注入最新 checkpoint 一份，其餘 audit 記 superseded）。重測條件：codex 上游為 PostCompact 增加 additional context 支援（監看 output_parser.rs 的 PostCompactCommandOutputWire 結構）。
