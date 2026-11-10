# Architecture Visual Candidate Gate — Actual-Delta 執行配方

本檔由 `~/.claude/skills/implement/SKILL.md` Step 8 在候選判定為 `candidate` 且人類選擇 `a. 產生 actual delta` 時載入執行。

🔌 接線點：架構圖產生與審批 — 見 WIRING.md
4. wrapper 成功後驗證 wrapper receipt、artifact path／存在、base/head SHA、最終 `head_sha`；receipt 缺失／無效、artifact 缺失、source receipt drift、base/head/final-head mismatch → closeout `BLOCKED`，不得啟動 adapter。
5. 驗證全過才啟動唯一一支 adapter background task：`Bash(run_in_background=true): node ~/.claude/scripts/plannotator-review.mjs actual-delta <wrapper-receipt> <head_sha>`。記錄 `adapterTaskId`、wrapper receipt identity 與 `head_sha`；Plannotator 取代舊 terminal artifact verdict，先呈現 artifact 與 wrapper receipt。
6. Bash 回報 `running in background` 或 `moved to background` 代表 adapter task 仍在執行，不是 adapter timeout。adapter task 還是 live 時不得啟動第二支、不得讀未完成 receipt，也不得要求 top-level human 用 user shell 重跑；若收到重跑要求，回覆現有瀏覽器審閱仍在等待，繼續等同一支 task。等 harness `task-notification` 明確回報 `completed` 或 `failed`，不主動輪詢；通知後只用 Read 讀 output file 一次，接受唯一 final JSON 的 `receipt` path。task failed、final JSON 缺失／重複或 receipt path 不唯一都維持 closeout `BLOCKED`。
7. 只有 Adapter exit 0 且唯一 receipt `decision=approved`、`transition=accepted` 綁同一最終 `head_sha`，才寫 accepted outcome；保存 adapter receipt path、feedback、最終 `head_sha` 到 visual decision／closeout handoff。
8. 記錄 visual decision `accepted` 並允許 shipping。`Approve with Notes` 仍算 accepted，保存 notes 不阻擋。Shipping 另要求 clean tree、最新 `review-implement` terminal outcome、最新 adapter visual decision receipt 全都綁同一最終 `head_sha`。
9. Adapter exit 1 且 `decision=annotated`、`transition=classification-required` 時，保存 feedback、維持 closeout `BLOCKED`；top-level human 只分類 `artifact-inaccurate` 或 `architecture-rejected`，agent 不得猜測。classification no-answer 仍 `BLOCKED`。
10. `artifact-inaccurate` 只能用同一組 `feature_base_sha`／`head_sha` 重生圖並重跑 wrapper／adapter，不修改 code、不建立新 commit。`architecture-rejected` 回到 implement；code change 建立新 commit，使先前的 review-implement Run 與 visual decision 同時失效，兩道 gate 都重跑。
11. `dismissed`、adapter timeout、`gate-error`、無效或缺少 result、result／artifact／source-receipt／head drift 與其他 adapter／receipt 錯誤都維持 closeout `BLOCKED`；Bash 把 live task 移入 background 不算 adapter timeout。不會變成 waiver 或 `accepted`，並保留 receipt identity。整合 rollback 移除 Plannotator adapter／runtime 變更與 receipts，保留既有 Archify trial evidence。只有 `not-applicable`、`waived` 或有 evidence 的 accepted adapter outcome 才算完成，其餘維持 `BLOCKED`。完成後接 Step 9。
