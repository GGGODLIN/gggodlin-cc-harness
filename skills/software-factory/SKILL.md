---
name: software-factory
description: 'Use when the user wants to discover, design, or build an unattended Software Factory (軟體工廠) — turning recurring manual workflows into an automated Trigger → Run → Three Brakes loop, or says "做成軟體工廠", "有哪些事可以轉成軟體工廠", "幫這個流程建軟體工廠", "/software-factory". Do not use for single-hook gates inside an interactive turn (use gate-authoring), general feature specs without unattended automation (use grill-me or to-spec), or one-off cron reminders (use schedule or loop).'
metadata:
  upstream: mattpocock/skills
  upstream-path: skills/in-progress/software-factory/SKILL.md
  upstream-pinned: 4ae2317
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/software-factory/scripts/tests/software-factory-contract.test.sh -->

# Software Factory（軟體工廠探索、白話訪談與安全落地）

> **出處注記（2026-10-24，2026-11-04 補對帳）**：受控詞彙（9 槽位與三道煞車）借鑑自 [mattpocock/skills#1316](https://github.com/mattpocock/skills/pull/1316)（已於 2026-10-31 以 `4ae2317` 合入上游 `main`）；三階段動線（既有自動化反查 → 白話防呆訪談與掛機保護 → 調度器獨立複驗與 7 天觀察期落地）為本機自寫流程。踩坑紀錄見 [LESSONS.md](LESSONS.md)。

把需要真人開視窗喊「開始」的重複工作，轉化為「自動觸發（Trigger）→ 隔離黑盒子執行（Run）→ 三道煞車驗收（Three Brakes）」的無人值守產線。沒有煞車與防重跑鎖的自動化只會變成狂燒額度與刷通知的垃圾大砲（slop cannon），因此設計與實作必須綁定下方的除錯對帳、白話防呆與確定性複驗。

## 觸發與呼叫邊界

- **Invocation capability**：保留模型自動選用（model-callable）、使用者直接輸入 `/software-factory`，以及從其他流程（如 `grill-me` 或 `retro-workflow`）交入的接線；不設 `disable-model-invocation`。
- **Trigger condition（與 frontmatter description 同步）**：當使用者想從近期工作挖掘可轉化為軟體工廠的候選、為某個重複流程設計無人值守工廠規格，或直接把工廠排程落地時使用。不要用於單一回合內的互動式 hook 攔截（改用 `gate-authoring`）、不涉及無人值守自動化的普通功能規格（改用 `grill-me` 或 `to-spec`），或單純的定時提醒（改用 `schedule` 或 `loop`）。

---

## 階段 1：候選探索與既有自動化反查

不論使用者是請你從近期紀錄挖掘候選，還是已經直接點名某個流程（使用者可能因看到大量收據或 log 而誤以為該流程仍是手動），動手設計前都先執行步驟 1 對帳既有自動觸發器；確認目標流程尚未自動化後，若使用者已指定目標即可跳過步驟 2 的跨領域海選、直接進入階段 2。

1. **先盤點既有自動觸發器，不單憑收據數量提名**：
   - `.scratch/` 或 `logs/` 裡出現幾十份收據，往往是因為某支 `PreToolUse` hook 或 `LaunchAgents` 排程早已在自動運轉，不代表每次都是人類手動發起。
   - 執行內建盤點腳本列出已掛載的 hooks 與排程（若在測試沙盒或指定工作區目錄 `<root>` 下操作，傳入 `--root <root>`）：
     ```bash
     python3 ~/.claude/skills/software-factory/scripts/inventory-existing-automations.py
     ```
   - 同步檢查目標專案的 `.git/hooks/` 與 `.github/workflows/`（或在沙盒目錄下枚舉設定檔與 `LaunchAgents/*.plist`）。
2. **比對活動紀錄、自動觸發器與實際產出／消費端，分流三類結果**：
   - 對每個手動重複流程回答：「目前卡在哪一步還要真人按開始？」以篩出真正的新候選。
   - 對已被 `settings.json` hook、`LaunchAgents` plist、`.github/workflows/` 或既有 workflow channel 自動觸發的流程，同步核對**近期有無實際產出，以及產物有無下游消費端（腳本、hook、digest 或對話實際讀取）**，拆成兩類呈現：
     - **排除項目（已由既有機制自動化且有實際消費）**：觸發器正常產出且有下游消費端，附檔案與行號出處標明排除，不端出來當新候選。
     - **殭屍排程／無消費端提醒（待健檢或退役）**：雖掛有自動觸發器，但近期零產出、持續失敗，或產出檔案無任何下游讀取與消費端，單獨列在此區並附證據交使用者決定修復或退役，**不得混入正常排除項目掩蓋**。
   - 若掃描範圍涵蓋多個工作領域，先完成跨領域盤點再拿 Top 候選、殭屍排程提醒與排除清單跟使用者討論。

**完成條件**：每個被提名的候選都已對照 `inventory-existing-automations.py`（或沙盒內的 `settings.json` 與 `LaunchAgents/*.plist`）確認無既有自動觸發器；每條已有自動觸發器的流程都已核對近期產出與消費端，分別歸入「排除項目」或單獨列出「殭屍排程／無消費端提醒」並附出處。完成後接階段 2。

---

## 階段 2：白話防呆訪談與軟體工廠規格表

先閱讀目標專案裡人寫的既有規範與腳本，把已經定死的事實直接對齊，只針對會改變執行環境、分支權限、交付落點與防撞規則的分歧向使用者提問。

1. **白話防呆訪談（禁止丟底層術語牆）**：
   - 向使用者確認輪詢頻率、防重跑與讓鎖規則時，將內部機制翻譯成以下三個白話日常情境提問：
     - **情境 A（無新事時 0 成本跳過）**：排程醒來先做純 git 或檔案檢查，沒新事就花 0 token 直接退下。若工作來源是上游 git 標籤，必須先找出「目前已是目標分支（如 `dev`）祖先的最高正式版 SemVer 高水位線（`highest_merged`）」，只對嚴格匹配正式版 `^v\d+\.\d+\.\d+$` 且版號 `> highest_merged` 的新標籤觸發——說明這能避開歷史未合併的舊標籤（如早期 `v0.x`）與 `-edge.*`／`-rc.*`／`-beta.*` 預發版。
     - **情境 B（同一件事卡住只跑 1 次，但模型缺油／斷線不鎖死版本）**：無人值守工廠遇到語意衝突或測試紅燈時，自動重試 2～3 次只會白燒數倍 token 並重複刷通知。因此 `state.json` 採 **1-shot 狀態機**（`in_flight` → `merged` / `needs_human` / `failed` / `retry_pending`）：一旦版號或任務產出收據後進入 `merged`、`needs_human` 或 `failed`，最多只跑 **1 次**、發 **1 次**通知就鎖定跳過，等人類處理；但若無頭 worker 因模型額度耗盡（429／憑證失效）連收據都沒產出，會先自動切換 `config.json` 的 `launcher_chain` 備援鏈下一順位（如 `["agent-cli-primary", "agent-cli-fallback", "claude-sonnet"]`），整條鏈都缺油或結尾 `git push` 撞到遠端 non-fast-forward 競態時，一律標 `retry_pending`（**絕不誤鎖成 `failed`**）等下一輪重跑。
     - **情境 C（你在忙時怎麼讓路——掛機視窗絕不誤擋）**：操作者常在主工作目錄開著多個終端機與 Claude Code 視窗掛機數小時至隔夜，因此**不能用「有沒有開著 Claude 視窗」或「主目錄有沒有未提交改動」當忙碌判斷**。固定採雙層保護：
       1. 工廠全程在 `/tmp/<slug>-<id>` 獨立臨時 `git worktree` 作業，完全不碰主工作目錄；
       2. 只在**活躍鎖持有 `< 30` 分鐘**（例如 `lane-lock.sh status` 顯示持有程序存活且 `< 30` 分鐘；若 `>= 30` 分鐘視為閒置掛機、不阻塞工廠）或**目標分支有 `in_progress` 的 CI workflow**（避免推播觸發 `cancel-in-progress` 砍斷進行中的 CI）時才禮讓退出。
2. **產出完整軟體工廠規格表（四段必填骨架）**：
   - 訪談收斂（或在單輪規劃請求中）產出規格時，必須完整列出下列四個結構化區塊，不省略任何槽位：
     1. **六欄重述（Six-field Restate）**：`Outcome`、`User`、`Why now`、`Success`、`Constraint`、`Out of scope`。
     2. **9 大受控詞彙槽位（9 Controlled Glossary Slots）**：
        - `Task`（單一工作單元）
        - `Trigger`（啟動排程或事件）
        - `Run`（單次黑盒子執行生命週期，中途絕不停下等真人對話）
        - `Runner`（可拋棄式隔離執行環境，如 `/tmp` 下的 `git worktree`）
        - `Ticket tracker`（狀態機檔案如 `state.json` 與收據目錄）
        - `Ticket source`（工作來源與高水位線篩選條件）
        - `Git host`（遠端倉庫與目標分支）
        - `Orchestrator`（掌控前置檢查、建拆 worktree、呼叫 worker、獨立複驗與推播的調度腳本）
        - `Observability platform`（無外部 APM 時填 `none`，並指明本地 log、收據 JSON 與通知通道如 Discord Keychain webhook）
     3. **三道煞車（Three Brakes）**：
        - `Automated checks`（第一道煞車：型別、lint、版本檢查與雙端測試等確定性檢查）
        - `Automated review`（第二道煞車：零對話脈絡的獨立審查 subagent，例如 `prepare_merge_review.py` 三方 diff + 雙盲 `routed-judge` 或 `task-verifier`）
        - `Human review`（第三道煞車：何時直推目標分支、何時退守候審分支如 `sync/upstream-vX.Y.Z` 並發單次通知請人類裁決）
     4. **5+1 設計問答對映（Q1～Q5 + 演進路線）**：逐題回答 Q1 任務來源、Q2 開工條件、Q3 Runner 隔離與權限邊界（明定 worker 禁止自行 `git push`）、Q4 完成定義與獨立複驗、Q5 失敗交接與防洗版機制。

**完成條件**：防呆題目已涵蓋「0 成本跳過（含 SemVer 高水位線與排除預發版）」、「1-shot 不重試 `needs_human`/`failed`」與「掛機視窗不誤擋（`/tmp` worktree ＋ `< 30` 分鐘活躍鎖與 `in_progress` CI 才讓路）」；規格表已完整填齊六欄重述、9 大槽位、三道煞車與 Q1～Q5。完成後接階段 3。

---

## 階段 3：安全硬化落地、五類回歸測試與觀察期登記

- 如果使用者確認要直接實作工廠調度器與排程，就在動工寫任何腳本前讀 `~/.claude/skills/gate-authoring/SKILL.md`，將調度器視為自動化控制面套用安全設計。
- 如果工廠將透過 `launchd`、`cron` 或常駐排程上線，就在宣告完工前讀 `~/.claude/rules/common/trial-observation.md`，完成 +7 天觀察期登記。

實作調度器（Orchestrator）或撰寫「調度器必備安全與驗收檢查清單」時，必須逐項落實下列 5 條硬性防護：

1. **Threat Model、Surface 四分表與 `factory.disabled` 停機開關**：
   - 在設計文件（`DESIGN.md`）開頭寫明防護目標與明文不承諾事項（點名 `factory.disabled` 是操作者的一鍵緊急停機開關，不是防禦本機主動攻擊者的安全邊界）。
   - 標出 `Locked`（調度器、worker prompt、測試檔）、`Editable`（臨時 `/tmp` worktree 與收據）、`Append-only / State`（`state.json` 與純 runtime log `logs/factory.log`）、`Human-controlled`（`factory.disabled`、plist 與候審分支裁決）四分表，並寫明 `bootstrap`、`update`、`recovery` 三條自身生命週期指令。
2. **調度器確定性獨立複驗與備援鏈換手防護（絕不盲信 Worker 自報 JSON）**：
   - 無頭 Claude worker 明文禁止自行執行 `git push`，只能產出變更與收據（如 `factory-verdict.json`、`merge-review.md`）。（在 `DESIGN.md` §0 明示同帳號下的禁止 `git push` 與 Locked 面屬 `gate-authoring §0` 防漂移架構分工，非跨 OS 帳號沙盒）。
   - `launcher_chain` 換手迴圈必須以 `start_new_session=True` 執行子行程並捕捉 `TimeoutExpired`（逾時以 `os.killpg` 回收整個 process group）與 `OSError`；判斷某腿是否成功產出收據時，必須驗證該收據為合法 JSON 且含有效 `verdict` 與匹配的 `tag`（若為空檔或截斷 JSON 則視為該腿崩潰、刪除後繼續切換下一腿，絕不因半份 JSON 提前停下並誤鎖為 `failed`）。
   - Orchestrator 在推播或判定通過前必須親自執行確定性檢查：驗證 `git status --porcelain` 完全為空（防止 worker 修好工作樹卻漏 commit 導致推播舊 `HEAD`）、驗證開工時固定的 `origin_dev_sha` 與 `<target_tag>` 祖先關係、重跑 `scripts/check-version.sh`（檔案不存在視為失敗）、核對 `merge-review.md` 非空與雙判官 `CLEAR`；任一項不符立即攔截並降級為 `needs_human`。
   - 降級為 `needs_human` 時，若工作樹有未提交衝突，先建立自動快照 commit 並寫入本機 `refs/factory-recovery/...` 持久 ref，再推送至不覆蓋人類分支的候審分支；推播目標分支前再次檢查 `factory.disabled` 且一律不加 `--force`，遇 non-fast-forward 競態時記為 `retry_pending`。
3. **病態檔案防護（`lstat` + `O_NOFOLLOW`）、原子寫入與單實例互斥鎖（`fcntl.flock`）**：
   - Orchestrator 進入主流程前先對 `factory.lock` 取得非阻塞排他鎖 `fcntl.flock(fd, LOCK_EX | LOCK_NB)`（拿不到鎖即以 `busy_self_lock` 0-token 退出），防止排程與手動重入互拆 worktree；所有前置忙碌與 `git fetch` 檢查遇失敗時一律 fail-closed 禮讓退出；`--dry-run` 保持純唯讀、不寫入 `state.json`。
   - 讀寫 `state.json`、`config.json` 與 `logs/factory.log` 前，先用 `os.lstat` 與 `os.O_NOFOLLOW | os.O_NONBLOCK` 驗證目標：若為 symlink、FIFO 或 `st_nlink > 1` hardlink，立即拋錯拒寫；寫入設定與狀態時採「同目錄 `O_CREAT | O_EXCL | O_NOFOLLOW` 暫存檔 → `fsync` → `os.replace` 原子替換」（不用原地 `O_TRUNC`），且既存的空 `state.json` 視為損壞拋錯、不靜默重置。
4. **零內容雜湊紀律（No Content Hashing）**：
   - 不在 `state.json`、收據或 manifest 計算、儲存或比對檔案內容 hash（`sha256`、`md5`、`checksum`、`digest`）；只記錄版號、git commit SHA 與結構化狀態欄位。
5. **五類回歸測試 ＋ 實機乾跑 ＋ 7 天 Trial 登記**：
   - 撰寫並實跑涵蓋 5 大類情境的測試套件：① `known-good`（無新版 0-token 跳過 ＋ 乾淨合併推進）、② `known-bad`（已標 `failed`/`needs_human` 單次熔斷不重跑 ＋ 攔截 worker 謊報 `ready_to_push`）、③ `boundary`（`lane-lock` `< 30` 分鐘禮讓 vs `>= 30` 分鐘掛機放行 ＋ `in_progress` CI 禮讓）、④ `lifecycle`（bootstrap / update / `factory.disabled` recovery 停機與恢復）、⑤ `pathological`（拒絕 symlink / FIFO / hardlink），全過才印出專用通過 token（如 `FACTORY_TEST_SUITE_ALL_GREEN`）。
   - 對真實倉庫跑一次乾跑、載入排程（`plutil -lint` + `launchctl bootstrap`），並在 `~/Desktop/projects/.claude/trials/active.md` 新增 +7 天觀察期條目與 detail 檔。

**完成條件**：上述 5 項調度器安全與驗收檢查（Threat Model + Surface 四分表 + `factory.disabled`、調度器獨立複驗禁 worker push、`lstat` + `O_NOFOLLOW` 防 symlink/FIFO/hardlink、零內容雜湊、五類測試＋7 天 Trial 登記）已全數列入檢查清單或實作驗證通過。

