# Changelog

公開版 harness 的變更紀錄。每一節對應一次發布；「Unreleased」是已整備、尚未推上公開 repo 的候選。只記對讀者有意義的變動，不逐檔列 diff。

## 2026-10-18

### 新增
- `references/failure-mode-taxonomy.md`：失敗模式探針表（F1–F7 問句與登記區格式骨架，補齊回流機制樞紐檔）。
- `hooks/claim-detect-keywords.json`：`T1-claim-detect-local-first.sh` 的宣稱詞正規式與計分規則表。
- `skills/review-method`、`review-standards/`、`references/review-dispatch-principles.md`：審查 subagent 共用方法原則、必報清單（must-report）與審查派工原則。
- `skills/agent-dispatch/references/harness-recommendations.md`：模型 × 外殼推薦表。

### 修正
- 匯出路徑與去識別化：修正 `.sh` 預設值 `${VAR:-...}` 產生 `/Users/you/...` 與 Node.js／Python 未展開 `'~/...'` 的問題；隨附測試改用同庫相對路徑定位。
- 公開版契約測試對齊：移除依賴私人歷史 commit 的 `hooks/taskoutput-settings-contract.test.py`，將 `review-spec`、`implement`、`e2e`、`write-pr-description`、`ledger-bootstrap`、`local-analysis` 等契約測試對齊公開版 `🔌` 接線點與白名單範圍，並修正 `scripts/failure-mode-daily.test.py` 的固定日期過期問題。
- `install/hooks/*.md`：補齊 `T1-claim-detect-local-first`、`T1-evidence-level-detect`、`T2-routing-gate`、`checkpoint-judge`、`ledger-bootstrap`、`matt-tdd-gate` 六份安裝說明的必備隨附檔案與測試段落。
- `commands/rules-slim.md`、`scripts/recall-before-answer-leakage.py`、`config/gpt-models.env`、`openspec/specs/harness-trust-binding/spec.md`：補註歷史盤點目錄 `rule-review/` 缺省行為、移除未匯出檔案註解並補齊 spec `Purpose` 與中性化描述。

### 變更
- `skills/agent-dispatch`：支援依任務指定 worker 外殼（預設 Claude Code，可選 Codex CLI 或 pi），派工同意門檻一併涵蓋外殼與配方。
- `commands/pr-review.md`、`commands/review-spec.md`：審查席位推薦與選席規則更新（`review-spec` 未給級別時於 Tier 1/2 間自選，Tier 3/4 只推薦不自動簽發 permit）。
- `rules/common/fact-check.md`、`skills/research-before-answer`：公開 HTML 研究頁與直接交付的 X 研究連結讀取流程更新。

### 移除
- `hooks/recall-before-answer-jev.py`：`recall-before-answer.sh` 簡化為關鍵字直接提醒，移除 Jev 判官依賴。
- `skills/implement` 的 `material-preparation` 試用元件（`references/material-preparation.md`、`scripts/compose-materials.mjs` 與對應測試，試用期結案移除）。

## 2026-10-13

### 新增
- 接線點「全機文件定位」：不知道東西在哪個 repo／目錄時用描述找原始檔。公開版只定義介面並推薦 DigUp，不是強依賴；規則其餘路由不靠它。見 WIRING.md。
- `skills/implement`：派工材料接點（`references/material-preparation.md`＋`scripts/compose-materials.mjs`，試用中）：同任務會多次派工時用 `materials.json` 組材料區，只交付一次時沿原路。
- `skills/research-before-answer`：Monid 當次選用流程（`references/monid-opt-in.md`）：補查社群評價時先問一次、查價後才確認本次支出上限，不當自動 fallback。
- `rules/common/fact-check.md` 第 17 條：最新外部事實直接查外部來源，本機 memory、wiki、session 紀錄不作探索入口，也不作搜尋失敗的替代。
- `hooks/T1-evidence-level-detect.sh`：判官鏈加第三順位備援（Drex），Jev 與 Groq 都失敗時補判；端點可由 `T1_EV_*` 環境變數覆寫，API key 從 Keychain 讀、項目名寫在檔頭。

### 修正
- `skills/debugging/SKILL.md`：分層排錯範例原本會把 secret 值印進輸出（`${VAR:-UNSET}` 有值時會展開成值），改成只印存在性；與上游 superpowers v7.0.0 同一修法。
- `rules/common/browser-routing.md`：退役瀏覽器工具的還原路徑改成純文字描述，不再指向公開版沒有的目錄。
- `social-info/scripts/local-analysis/skill-upstream-check-weekly.sh`：capability delta 的提示行不再被撈進「巡邏警告升級」段，避免每週假警報。

### 變更
- `skills/implement`、`to-tickets`、`wayfinder`：上游對賬完成，`upstream-pinned` 推進到 mattpocock/skills `49dd158`；本輪不吸收上游內容（tracker 相關改動本地用不到）。
- `skills/model-onboard`：免費模型的輸出上限改用實測值。
- `skills/research-before-answer`：抓取退路說明對齊目前的 fetch 行為（HTML 階先抽正文再換下一階）。
- `skills/review-implement`：授權範圍內、不改驗收的審查意見由主 session 自行裁決，只把會動到需求的取捨交給使用者。
- `skills/workflow-hardening`：瀏覽器讀頁改派 `chrome-fetcher`（vendor 版 workflow 用 `chrome-devtools-fetcher`），經 LCU 讀日常 Chrome，不再走 Open Browser Use／Agent Chrome adapter。
- `hooks/T1-warning-check.sh`：啟動警告對齊目前實際存在的檢查。
- `scripts/plugin_hook_drift.py`、`skill-changes-daily.py`：plugin 可能裝在多個位置，比對時全部檢查；安裝位置或 hook 內容與批准基準不同就列為「未審」，直到重新批准。只比對 manifest 與受追蹤模組的檔案特徵，不是完整的行為稽核。
- `folder-level/.claude/commands/trial-review.md`：決策報告的「現在」段改成 3–4 句短背景（用途與來源、當時批准的改動、本輪一個案例、現在只決定什麼），不另開四段介紹。
- `settings.json`：hook 註冊對齊目前私人版（公開版照例剪掉私人 hook）。
- `commands/advisor.md`：審查分級格式的「為什麼」只留結論，不帶案例。
- `openspec/specs/harness-trust-binding/spec.md`：hash 例外新增一條有限條款：不在公開版的私人發布 skill 可用 SHA-256 核對下載的 app archive 與發布者同一版 checksum；不涵蓋其他檔案、收據、manifest 或 permit 綁定。

### 移除
- `hooks/better-rm-env.sh` 與其測試、安裝說明：better-rm 已全機移除，這支 hook 沒有對象。

## 2026-10-10

### 變更
- README：加介紹影片；拿掉多帳號設定段（該機制留在私人版）。

## 2026-10-09

### 新增
- 首次公開匯出：治理層（rules／hooks／skills／commands／agents／workflows）、WIRING.md 接線點清單、安裝說明、第三方授權聲明。
- README 依「你想做什麼」重排入口。

### 修正
- 匯出契約補洞：recovery 摘錄的結尾保留、匯出前後置檢查缺口補齊。
