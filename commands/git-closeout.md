---
description: 全機 Git 收尾的手動入口，涵蓋個人 repo 與 `~/Desktop/work/acme` 樹下的公司 repo（後者只做 inventory、快照與報告，處置對齊既有 confirm 清單）；其他 session 留下的 uncommitted 內容以工作樹為單位收進 commit。單一 session 收自己改的檔用 `/self-closeout`。Use when 使用者直接 invoke `/git-closeout`，要在新工作前「整理 Git 提醒」或「把 repo 收乾淨」。Do not use for `~/Desktop/work/` 底下非 acme 樹的 repo（oldco-shop、oldco-site、oldco-api 等前雇主快照）、merge conflict、PR review 或一般功能開發。
argument-hint: 不帶參數；使用提醒列出的 repo，沒有提醒時使用目前 cwd
disable-model-invocation: true
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/git-closeout-contract.test.sh -->

# Git Closeout

把 SessionStart 提醒視為「新工作前仍待收斂的 repo 狀態」，不是可以略過的旁支通知。若同一則使用者訊息還包含新任務，先完成本 command；`READY 前不開始新工作`。

## Native pre-push inclusion 邊界

- 使用者的 feature session 仍自行執行 `/git-closeout`；native `pre-push` 只負責 push 前確認送往 `main` 的 ref 通過 inclusion 檢查。
- push 成功後仍要重新執行 `/git-closeout`，取得 fresh Git reconciliation；native gate 不取代 push 後盤點。
- `git push --no-verify`、被刪除或修改的 hook，以及 remote API 旁路不在 native gate 的保證範圍；force push 仍須既有 human confirm。
- client hook 不提供 remote force race 或 final-read race 的原子保證；force push 仍須既有 human confirm，push 後一定要用 `/git-closeout` 做 fresh reconciliation。
- 安裝後另設 worktree-specific core.hooksPath 會繞過，/git-closeout 要查；命令列 -c core.hooksPath 也會繞過。

## 流程

1. **鎖定目標 repo**
   - 從目前 context 最近一次「個人 repo 收尾檢查」取得所有 `repo：` 路徑；沒有提醒時使用目前 cwd。
   - 提醒含「其餘 N 個未掃」或 cwd 是個人專案父目錄時，重新枚舉該父目錄的直接子 Git repos；無法取得完整路徑與數量就回 `BLOCKED`，不得只處理已顯示的 repos。
   - `~/.claude` 一律納入目標，與提醒內容和 cwd 無關：hook 只有在 cwd 落在 `~/.claude` 內時才檢查它，從其他目錄起始的 session 結構性看不到它的狀態，分岔因此會無聲累積。
   - 枚舉子 repo 時要含 dot-prefixed 目錄（例如 `~/Desktop/projects/.claude` 這個 trials ledger repo）；只用 `*/` 展開會靜默漏掉它們，分母當場就少算。
   - 對每個路徑用 Git common directory 找 canonical source repo，worktree 位於其他目錄時仍按 source repo 判斷。
🔌 接線點：多帳號與帳號判定 — 見 WIRING.md
   - canonical source repo 就是 `~/Desktop/work/acme` 本身（父層私人治理 repo、無 remote）時標為 **personal scope**，照個人 repo 處置。canonical source repo 是 `~/Desktop/work/acme/` 底下的巢狀 repo（`acme-dashboard-v2`、`acme-saas-v2-service` 等各自的 git root）時標為 **work scope**：照常做 inventory 與分類，處置受第 5 步的公司 repo 邊界約束。位於 `~/Desktop/work/*` 其他位置（`oldco-shop`、`oldco-site`、`oldco-api` 等前雇主快照）時停止，那些 repo 不走本 command。
   - work scope 的 trunk 取 `origin/stage`；該 repo 沒有 stage 時才退回 `origin/main`／`origin/master`。**不要用 `origin/HEAD`**——它在 `acme-dashboard-v2` 指向 `main`、在 `acme-saas-v2-service` 指向 `master`，兩者都是 production／default 分支，拿它當 trunk 會把已合併進 stage 的 branch 全判成未合併（實測誤報率 2/6）。
   - 提醒只當定位線索，不當完成證據；不得只重述提醒中的「2 項」就下判斷。
   - `~/.claude/policies/personal-main-closeout/ignore.jsonl` 有 `"ref": "*"` 且 identity 對上的 repo，是使用者交給其他工具或 agent 管理的專案（例如 Codex 做到一半的 repo）：仍列在目標清單中計入分母，標 `EXCLUDED`，不做第 2–6 步的 inventory、分類與任何 Git 變更，也不因此把 verdict 改成 `BLOCKED`；回報時照下方「交給其他工具」格式單列一行。identity 判定與 hook 相同：有 origin 用正規化後的 remote URL，沒有就用資料夾名稱。

   **完成判準**：每個 target 都對應唯一 canonical source repo，未掃數量為 0，`~/.claude` 與每個 dot-prefixed 子 repo 都在目標清單中，每個 target 都已標記 personal 或 work scope，`~/Desktop/work/` 底下非 acme 樹的 repo 都不在清單中，且每個實際存在的多帳號 config dir 都跑過一次 symlink 檢查、結果已記錄（靜默或列進 `AMBIGUOUS`）。

2. **取得 fresh ground truth**
   - 確認 trunk 與 remote；有 `origin` 且後續要和 remote trunk 比較時，先執行 `git fetch origin`。
   - fetch 失敗就標記 remote 未驗證，不得拿 stale `origin/main` 或 `origin/master` 宣稱內容已整合或已被取代。
   - 用 `cwd=<repo>`、`source=startup` 的 JSON stdin 執行 `python3 ~/.claude/hooks/personal-main-closeout.py`，保存原始 baseline；它只負責揭露候選，不替本 command 做產品判斷。

   **完成判準**：每個 repo 都有 trunk、remote freshness 狀態與 hook baseline。

3. **做 repo-wide inventory**
   - 執行 `git worktree list --porcelain`，取得 Git 自己列出的完整 worktree 分母，並保留每筆 `locked`／`prunable` 狀態與理由。
   - 對每個 worktree 執行 `git status --porcelain=v1 --branch --untracked-files=all`，不可只查目前 checkout。
   - 被 `.gitignore` 忽略的檔不進日常 inventory、ignored path 不計入 READY 判準：它們本來就不會被 commit 收走，逐一證明可重建只會讓 READY 永遠到不了（2026-09-23 實測 851 項分佈在 50 個目錄）。第 5 步刪東西前才對那個範圍枚舉。
   - 枚舉 local branches 與 trunk 的 ancestry／左右 commit 數、stash、trunk 未 push commits、detached worktree、staged、unstaged 與 untracked 內容。
   - 對每個 dirty worktree 執行 `python3 ~/.claude/scripts/closeout-provenance.py --repo <path>`，取得每個 dirty 檔的候選寫入 session、最後寫入時間與該 session 最後活動時間。這是參考資訊，不是授權：它證明「誰寫過」，證明不了「現在沒人在寫」。
   - 呼叫 `ListAgents` 一次，只讀 busy／idle 旗標；**不對任何 peer session 發 SendMessage**，不等它們回覆。喚醒閒置 session 要重送整段 context、cache 已過期，而它能回答的只有「不是我」。ListAgents 的短 id 與 session id 無已驗證的對應（2026-09-20 實測 `c466b8a3…` 對到 `[77abd4]`），對不上就標「未知」，不得當成「session 已退出」。
   - ListAgents 的 busy 旗標與檔案 mtime 都只是線索，寫進報告供使用者判斷；不能單獨把整個 repo 判成不可收，也不能單獨證明可以刪除或接管。`ACTIVE` 只給有明確保留條件的項目：使用者本輪或 ignore.jsonl 指定保留、檔案在等另一個 session 的 audited commit、同一個檔同時有 staged 與不同的工作樹內容（`closeout-provenance.py` 的 `staged_differs`）。其餘 dirty 走 `SNAPSHOT`。
   - 讀 `~/.claude/policies/personal-main-closeout/ignore.jsonl`，把每筆已登記的 ref 當成使用者既有的 `PRESERVE` 處置帶進 inventory。它記的是「刻意保留、不要再吵」的決定，分類前沒讀它，刻意留的快照與等 upstream 的 branch 會被算成已合併可刪。
   - 用表格列出每個來源：worktree／branch／stash、路徑、dirty／ignored 數、unique commits、lock、owner 狀態與下一步證據。領先幾個 commit 不能單獨證明內容有效、已整合或已退役。

   **完成判準**：`git worktree list` 的每個 worktree、每個未合併 branch、每個 stash、ignored path 與 trunk ahead 狀態都恰好出現一次，沒有 silent skip；ignore.jsonl 每筆 ref 都已比對過本次 inventory。

4. **逐項分類**

   | 分類 | 判準 | 動作 |
   |---|---|---|
   | `INTEGRATE` | 有不在 fresh trunk 的有效成果，且 task／session／commit history 或目前 session exact paths 能證明 provenance；diff 與相關測試能證明成果有效 | personal：依 repo 慣例驗證、commit，再整合到 trunk。**work scope：把成果搬到一條活的 feature branch（cherry-pick 或 commit）後停下**，不整合進 `stage`／`main`／`master`——那三條一律走 PR；push 與開 PR 等使用者決定 |
   | `SUPERSEDED` | 無需保留的 unique commits，且 fresh trunk 已有等價或更新實作；需附 diff／commit／測試證據 | 加入待清理清單 |
   | `PRESERVE` | 使用者明確核准保留，變更已收進 commit、worktree 乾淨，並有 branch／tip／理由 | 保留；需要靜音時走明確 policy 提案 |
   | `SAFE_REMOVE` | worktree 乾淨、branch 已整合、沒有保留條件、lock、stash、untracked，且刪除範圍內的 ignored 內容已確認可重建或已另存 | 加入待清理清單 |
   | `ACTIVE` | 有第 3 步列的明確保留條件；busy 旗標與 mtime 不算 | 保留並寫出條件；不擋同 repo 其他項目 |
   | `AMBIGUOUS` | 證據不足、無 provenance、雙邊都有修改、remote 未驗證、locked／prunable 未取得處置，或無法判斷產品價值 | 保留並一次提出所有待拍板題 |

   `SUPERSEDED` 不能只靠 branch 落後、檔案較少、commit 標題相似或 main 較新；dirty worktree 必須把工作樹最終內容和 fresh trunk 實際比較。Locked worktree 不得列入 `SAFE_REMOVE`，也不得用 `--force` 繞過 lock。

   **其他 session 留下的 uncommitted dirty** 另有一類處置 `SNAPSHOT`：不屬 `ACTIVE`（沒有明確保留條件）時，以**工作樹為單位**整包收進 commit，不按 session 拆 branch、不猜唯一作者。personal scope 直接在該 worktree 當前 branch 上 commit（HEAD 前進、檔案內容不變，閒置 session 醒來只需重看一次 `git status`）；work scope 不能在 `stage`／`main`／`master` 上 commit，改存到 `closeout/<repo>-<YYYYMMDD>` branch，原 worktree 保持 dirty 並在報告寫明「已保存、原處未乾淨」。閒置時間只用來排序與提醒使用者，不單獨授予接管資格；mutation 前照第 5 步重核 fingerprint。

   **完成判準**：inventory 每列恰好有一個分類與可追溯證據；`AMBIGUOUS` 不得偷算成可刪，沒有 provenance 的 dirty 內容不得偷算成 `INTEGRATE`。

5. **先整合，再清理**
   - `INTEGRATE` 只接回 provenance 與行為都已能驗證的現成成果；相關測試失敗時停止為 `BLOCKED`，不要在 cleanup command 裡擴大成新一輪功能修復。Pre-existing dirty 有明確保留條件時保持 `ACTIVE`；沒有就走 `SNAPSHOT`，busy 旗標不改變這個判定，不整合進 trunk 之外的任何地方、不判斷內容好壞，只確保沒有未 commit 的東西。
   - `SNAPSHOT` commit 前先 `git diff --cached --name-only` 確認暫存區沒有本輪之外的內容；commit 訊息固定 `chore(closeout): snapshot uncommitted work in <worktree>`，內文列 provenance script 給的候選 session 與時間。personal scope 的 trunk 在 push 前用 `git log origin/<trunk>..<trunk>` 核對每顆將發布的 commit，多出非本輪的 commit 就照常 push（個人 repo 的 unpushed commit 也是待收項）並在報告點名。
   - `PRESERVE` 的 dirty／stash 內容先收進可追溯 branch commit 並讓 worktree 乾淨；不能直接靜音 mutable state。
   - 遵守 context 裡既有的 commit、push 與 trunk 政策；本 command 不覆蓋公司 repo 或多人協作 repo 的確認規則。
   - **work scope 的處置邊界**——對齊既有 confirm 清單，不因為是 closeout 就變嚴或變鬆：
     - 不必問：inventory、分類、報告、`git fetch`、`git add` ＋ `commit`（把散落的 dirty 收進 branch）、`git branch -d`（安全刪；未合併時 git 自己會拒絕）、`git worktree prune`、cherry-pick 到一條活的 branch
     - 一律先問：`git push`、`gh pr create`、`branch -D`、`reset --hard`、`checkout .`／`restore .`、`rebase`、`commit --amend`、會丟掉 dirty 的 `worktree remove`、discard dirty、drop stash
     - 一律不做：在 `stage`／`main`／`master` 上產生任何新 commit，也不把別的 branch 合併進它們。**本機 commit 同樣算**——「我沒 push」不是理由，那顆 commit 下次 push 就進去了
   - 刪 worktree／目錄前，先對那個範圍跑 `git status --porcelain=v1 --ignored --untracked-files=all` 枚舉 ignored 內容。Ignored path 不自動等於可刪、也不代表已備份；只有能證明是可重建產物或使用者明確核准時才連同刪除，其餘列進下一條的破壞性操作清單一起問。
   - 對 discard dirty changes、drop stash、`git worktree remove --force`、branch delete 等破壞性操作，一次列出所有破壞性操作、完整路徑、branch、會遺失的內容與分類證據，取得一次明確同意後才執行；不要逐項來回問。
   - 取得同意後、每批 mutation 前，重新核對 HEAD、branch tip、完整 status／diff、ignored paths、locked／prunable 與 owner。任一 fingerprint 改變就使原授權失效，停止、重新分類並重新取得同意；不得沿用過期證據執行。
   - 若安全 gate 阻擋，原樣轉交它要求的 `dcg allow-once` 指令；使用者放行後，一字不差重發原命令，驗證另發一條。
   - `~/.claude/policies/personal-main-closeout/ignore.jsonl` 只能保存使用者明確核准的長期處置；不能用 ignore.jsonl 讓驗收假綠。若確實需要靜音，先提案 repo、branch、tip 與理由，等使用者明確同意。

   **完成判準**：有效成果已整合或取得 `PRESERVE` 處置；`SNAPSHOT` 項全部進了 commit；每批破壞性操作都有 fresh fingerprint 與本輪明確授權；未授權或已變動項保持原狀並使 verdict 為 `BLOCKED`；work scope 的成果只停在 feature branch 或 `closeout/` 快照 branch，`stage`／`main`／`master` 一個 commit 都沒被加進去。

6. **從外部來源重新驗證**
   - 重新枚舉 `git worktree list --porcelain`，再查每個 worktree 的 status、未合併 branches、stash 與 trunk ahead 狀態。
   - 重新執行 `python3 ~/.claude/hooks/personal-main-closeout.py`；預期不再輸出 `systemMessage`。
   - hook 沉默仍不夠：main 乾淨但 side worktree dirty、ignore policy 隱藏項目或 active worktree 仍可能存在；repo-wide inventory 也必須沒有未解列。
   - code 未再變更時不重跑相同測試；Git cleanup 後改用重新枚舉 refs／worktrees 的角度驗證。

   **完成判準**：personal scope 的 hook 沒有 `systemMessage`，沒有保留條件的 worktree status 都乾淨，stash／unpushed trunk／部分掃描皆為 0，ignored path 不計入；未合併 branch 只能是有明確理由與 policy 的 `PRESERVE`，其餘 unresolved 為 0，且未靠未核准 ignore 條目消音。有保留條件的項目逐一列出並寫出條件；verdict 仍可 READY，但報告寫「本輪收尾完成，仍有進行中修改」，不寫「全機乾淨」。有人持續寫入時不承諾全機零 dirty；使用者要某一刻真正清空，得讓相關 writer 在收尾期間停筆，mtime 門檻替代不了這件事。

   **work scope 的完成判準不同**：等 PR 的 feature branch 本來就會讓 hook 一直有 `systemMessage`，所以不拿 hook 靜默當 READY 條件。改為三項全中才算完成：inventory 每列都有分類；每個「一律先問」的項目都已列給使用者且沒有擅自執行；沒有任何項目未分類就跳過。剩下等使用者決定的項目列進 `待處理`，verdict 用 `BLOCKED`。

## 回傳格式

成功時：

```text
Git closeout：READY
repo：<canonical path>（scope：personal）
處理：<整合／快照／移除項目與數量>
實際證據：hook 無 systemMessage；worktree=<N>；dirty=0；unresolved=0；preserved=<N>；stash=0；trunk ahead=0
保留／收尾後新增：<path（原因）>…或 0
未處理：0
```

報告表每個 worktree 一列，固定兩欄分開寫：`已保存`（內容已在某顆 commit 裡，不會丟）與 `原處已乾淨`（該 worktree `git status` 為空）。personal scope 兩欄通常同時為是；work scope 的 `SNAPSHOT` 是前者為是、後者為否，不得合併寫成「已處理」。

work scope 的 repo 換這組證據（hook 靜默不適用，理由見第 6 步）：

```text
Git closeout：READY
repo：<canonical path>（scope：work）
處理：<搬到哪條 branch／收進哪個 commit，含數量>
實際證據：trunk=<origin/stage 或退回的 ref>；inventory=<N> 列全部已分類；已搬上活 branch=<N>；等你決定=<N>；stage／main／master 未被寫入
未處理：0
```

目標是 ignore.jsonl 以 `"ref": "*"` 交給其他工具管理的 repo 時，單列一行，不影響整體 verdict：

```text
交給其他工具：<canonical path>（ignore.jsonl：<reason 摘要>）；未做 inventory 與任何 Git 變更
```

目標落在 `~/Desktop/work/` 底下非 acme 樹（第 1 步的停止條件）時，既不是 READY 也不是 BLOCKED：

```text
Git closeout：不適用
repo：<canonical path>
理由：canonical source repo 在 ~/Desktop/work/ 底下、不在 acme 樹內，第 1 步明訂停止
處理：0 項；未做任何 Git 變更
```

仍有待拍板、active owner、測試失敗或 remote 未驗證時：

```text
Git closeout：BLOCKED
repo：<canonical path>
已確認：<可證明的事實>
待處理：<逐項列出>
下一個唯一動作：<一次性授權、單一決策或修復 remote>
```

## 踩過的坑

- 2026-08-28：主 worktree 的 `git status` 乾淨，不代表整個 repo 乾淨；side worktree 的 2 項 dirty 內容要另查。
- 2026-08-28 RED：fresh agent 把 SessionStart 提醒判成與新任務無關並直接開始開發；本 command 因此把「先收尾、再工作」接成明確 gate。
- 2026-08-28 review：plain status 會漏 ignored，`--force` 也能繞過 worktree lock；兩者都必須進 inventory，不能當噪音。
- 2026-08-28 review：分類到使用者授權之間可能有新寫入；mutation 前 fingerprint 不同就讓原授權失效。
- 2026-09-04 RED：`~/.claude` 從 `~/Desktop/projects` 起始的 session 完全掃不到，實際累積到本地落後 44 個 commit、工作區 92 項未 commit 才被使用者問出來。它是最容易壞又最不會被看到的 repo。
- 2026-09-04：只用 `*/` 枚舉會漏掉 dot-prefixed 子 repo；`~/Desktop/projects/.claude` 因此整個不在分母裡，還把「53 個 repo 全掃過」講成了完成宣告。
- 2026-09-04：inventory 沒讀 ignore.jsonl，把一個登記為刻意保留的 checkpoint branch 當成可刪並實際刪掉（commit 物件仍可從姊妹 branch 到達，但保留標記與 policy 條目雙雙失效）。
- 2026-09-20 GPT-6 Pro 審查：「查到誰寫的」只是線索不是授權；點名 `git add` 擋不住暫存區裡別人的東西一起被 commit，push 也會帶出 trunk 上別人的 commit；另存 branch 不會讓原工作樹乾淨。三條都已改進第 3～5 步與報告格式。
- 2026-09-22：多帳號 config dir（`~/.claude-team-p` 等）完全不在分母裡。第 1 步的 canonical 判定會把它們正確摺疊回 `~/.claude`，但沒有任何一步檢查它們自己的 symlink 有沒有被打斷。實際發生：`moshi-hook install --target claude` 把 team-p 的 `settings.json` 換成 70 KB 實體檔、`defaultMode` 從 `bypassPermissions` 漂成 `auto`，三天無人察覺——整場 closeout 跑到一半，使用者問「我是用 -team-p 開的 session，是不是也要處理」才被發現。第 1 步因此加了 symlink 檢查。
- 2026-10-09 檢討：近 20 天 66 份回報 39 份 BLOCKED，24 份卡在 busy 旗標判 ACTIVE、14 份卡 ignored 證明可重建；使用者「強制收」實測無損。ACTIVE 改為只認明確保留條件，ignored 移到刪除前檢查，報告加「保留／收尾後新增」欄（GPT-6 Pro 審查第三案）。
- 不加 Self-Verify：核心產物是 live Git state 與破壞性授權，不是只靠文字 deliverable 能獨立對表的報告；用步驟 6 的真實 repo probe 驗收。
