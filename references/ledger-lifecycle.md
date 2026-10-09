<!-- 本檔在契約測試底下：bash ~/.claude/scripts/ledger-lifecycle/validate-registry.test.sh -->
<!-- 本檔在契約測試底下：bash ~/.claude/scripts/ledger-lifecycle/index-relation-schema.test.sh -->

# 帳本生命週期規則

## 規則正本

> 帳本生命週期：規則見 `~/.claude/references/ledger-lifecycle.md`；門檻以 `~/.claude/scripts/ledger-lifecycle/registry.json` 為準。

本檔說明分類、動作與權責，不重複 registry 的門檻數字或逐檔清單。任何腳本先讀 registry；`validate-registry.py` 是登記格式的機械檢查入口。

registry 採用的 `kind` 代碼為 `state`、`append`、`residue` 與 `pure-log`；validator 也接受 `純log` 作為人工輸入別名，寫入 registry 時統一使用 `pure-log`。每筆資料用 `path` 表示具體路徑或 glob 樣板，用 `threshold` 表示門檻，用 `action` 表示達標後的處理。每個 threshold rule 都要標明 `metric`、`unit`、`operator` 與 `value`，讓數字可直接被腳本讀取。`retirement` 與 `owner` 是選填欄位。觸發固定由每日 channel 負責，不在每筆資料重複登記。`kind` 是 `pure-log` 時，`threshold` 與 `action` 可以省略或留空。

## 類別定義

### 狀態帳本

狀態帳本描述仍在進行中的工作、試用或索引狀態；條目可能結案、過期或被 promote。它的生命週期重點是保留目前要看的內容，將已完成或低頻內容下放到索引、archive 或永久記憶。

### 追加式紀錄

追加式紀錄只新增歷史條目，不改寫舊條。它的生命週期重點是讓 agent 先從旁邊的小索引找定位，再用標題錨點搭配 grep 或 offset 讀主檔需要的段落。

### 殘留

殘留是機制產生的實體副產物，不是供 agent 直接查詢的帳本。它的生命週期重點是保留必要證據、縮小可縮的內容，或把已完成工作區搬到 archive；不能把「整理」偷換成刪除。

### 純 log

純 log 只為留下稽核或執行痕跡而登記。它不設生命週期門檻，也不要求 registry 提供動作；agent 需要查閱時自行選擇 grep、tail 或其他讀法。

## 動作模式

- 狀態帳本可以採索引下放、既有 state-archive、索引瘦身、退場搬遷或只提醒。動作要保留目前工作的最小可讀入口。
- 追加式紀錄以獨立索引檔、主檔檔頭提示、標題錨點與按需讀段為預設。主檔不因為超過門檻就直接切檔；是否切檔要另外拍板。
- 殘留以 git ref 與 status 取代整包快照，或把完成的工作區搬進 archive。活的 review evidence 保持原位。
- 所有動作都以 registry 的數值判定為準；reference 只描述動作形狀。

## 自動與拍板邊界

每日 channel 只做決定性掃描、計算、輸出命中與穩定 `source_key`，再把結果交給既有 digest 的 pending-actions。它不自動改檔，也不自動搬家、切檔或刪除。

使用者拍板後才能執行刪除類動作。即使搬遷或索引下放可逆，也先以提醒交付，不把提醒機制升格成自動寫入機制。

## 登記流程

新增會被 agent 消費的檔案或目錄時，先決定它屬於狀態帳本、追加式紀錄或殘留；若只留下稽核痕跡，就登記為純 log。接著在 registry 新增一筆，填入 `path`、`kind`、`threshold`、`action`，需要時補上 `retirement`、`owner` 與 `known_paths`。

具體路徑與 glob 樣板同時匹配時，具體路徑優先；多個樣板匹配時，以較具體的樣板優先。專案層級樣板放在 registry，讓掃描根下的新 repo 自動納管；已知實際路徑可寫在對應 entry 的 `known_paths`，作為盤點清單而不是第二份門檻正本。

完成登記後執行 `python3 ~/.claude/scripts/ledger-lifecycle/validate-registry.py validate ~/.claude/scripts/ledger-lifecycle/registry.json`。需要查詢某個檔案時使用 `resolve <registry> <path>`，輸出會標示命中的具體路徑或樣板。schema 失敗時先修登記，不把未登記的檔案交給每日 channel 猜測。

## 索引檔格式

索引檔一行代表一個主檔條目，欄位依序為 `id／slug｜日期｜一句結論｜主檔標題錨點`；不同帳本可把中間欄位換成 verdict、類型或判定，但最後一欄一律保留逐字標題。archived 使用 `slug｜verdict｜結案日｜一句理由｜標題原文`；proofread／factcheck 使用 `編號｜文章或主題 slug｜類型或判定｜一句｜標題原文`。

索引指向標題文字，不指向行號。消費者先讀索引，再用標題錨點 grep 主檔並以 offset 讀取需要的段落。主檔達 registry 的索引門檻時，檔頭要提示「先讀索引、再 grep／offset，不要整檔 Read」。

索引 append 與主檔 append 必須在同一個寫入流程處理；共用入口是 `python3 ~/.claude/scripts/ledger-lifecycle/ledger-index.py`。索引寫入失敗時，主檔條目標記 `[index-pending]` 並在當回合明報。每日 channel 以主檔 entry 標題數與索引行數做漂移檢查。

archived entry 的 entry 標題正則有兩種：legacy 形狀是 `^### .*\([^)]*[0-9]{4}-[0-9]{2}-[0-9]{2}[^)]*\)$`；新結案形狀是行首 `### ` 且含 `[結案 YYYY-MM-DD · ...]`。只有符合其中一種才算 entry；entry 內其他 H3 子標題不算 entry。
