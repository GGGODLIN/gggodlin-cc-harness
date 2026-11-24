# Lessons Learned — software-factory

- 2026-10-24 `.scratch/` 或 `logs/` 的高頻收據數（如 82 份註解收據）常來自已在同回合自動觸發的 `PreToolUse` hook 或 `LaunchAgents`，探索候選時先跑 `scripts/inventory-existing-automations.py` 對帳並排除已自動化流程。
- 2026-10-24 防重跑與讓鎖問題若直接拋出內部腳本名與 git 術語會造成閱讀阻礙，改拆成「無新事 0 成本、卡住只跑 1 次不重試、忙時讓路但掛機視窗不誤擋（`< 30` 分鐘活躍鎖或 `in_progress` CI 才讓路）」三個白話情境提問。
- 2026-10-24 上游倉庫常留存早年未直接合併的舊標籤（如 `v0.x`）與 `-edge.*` 預發版，標籤探索不可只看 `--no-merged`，須先求目標分支祖先中最高正式版 SemVer 高水位線再篩選。
- 2026-10-24 不加 `skill-verify-auditor` 常駐 Self-Verify：階段 1～2 屬多輪互動訪談，階段 3 落地已有 5 類回歸測試與 `task-verifier` 實跑驗收。
- 2026-10-24 GPT-6 Pro 審查兩座工廠抓出 5 項通用調度器陷阱並收斂進階段 3：① `launcher_chain` 必須捕捉 `TimeoutExpired`（配 `os.killpg`）且驗證收據為完整合法 JSON 才停下，否則半份截斷 JSON 會終止備援鏈並誤鎖版本；② 推播前必驗 `git status --porcelain` 為空並綁定開工時的 `origin_dev_sha`，防止 worker 修好工作樹漏 commit 卻把舊 `HEAD` 推出去；③ `safe_write_text` 改用同目錄 `O_EXCL` 暫存檔＋`fsync`＋`os.replace` 原子替換，且既存空 `state.json` 拋錯不靜默重置；④ 每座工廠必掛 `fcntl.flock` 非阻塞 `factory.lock` 防止排程與手動重入互拆 worktree；⑤ `--dry-run` 必須純唯讀、零持久化副作用。

