# Dispatch + Verify 正反例集

`~/.claude/rules/common/dispatch-and-verify.md` 的完整正反例，2026-07-06 從 always-on rules 搬出（context 稅審計）。判斷模糊時讀本檔對照。

## Verify — 逐項對照範例

```markdown
1. 預期：POST /api/foo 回 200 + {"id": <number>}
   實際：curl -X POST ... → 200 {"id": 42}
   ✅ match

2. 預期：點 Reply 按鈕 → inline composer 出現在 comment 下方縮排
   實際：composer 出現但沒縮排
   ❌ 縮排缺 — 待修
```

## 方向錯訊號 — 正反例

1. **同一 key 的修正嘗試額度用盡**
   - 正例：同一個 `TypeError` 第三次出現、第一次加 null check、第二次改初始化順序都沒解 → 停手重看呼叫鏈、懷疑問題定義（是不是根本不該在這層呼叫）
   - 反例：同一 error 第二次出現、第一次修法明顯改錯位置 → 還在額度內、正常 debug 迭代
   - 反例：兩次失敗驗的是不同項（第一次 API 通不過、第二次 UI 縮排錯）→ 不同 key、各自計數
2. **diff 越滾越大**
   - 正例：任務是「修 date 格式錯誤」、diff 已經動到 auth middleware → 停手、這是切錯層的訊號
   - 反例：修 shared util 時同步改它的 3 個 caller → caller 是任務的直接影響面、不算無關檔
3. **繞過驗證而不是通過驗證**
   - 正例：想把 `assert result == 42` 改成 `assert result is not None` 好讓測試過 → 立刻停手：這不是修 bug、是掩蓋 bug
   - 反例：測試本身寫錯（斷言與 spec 不符）、修測試前先列出 spec 對照說明為什麼是測試錯 → 合法修測試、不是繞過

## 停下問使用者 vs 自己決定 — 正反例

1. **不可逆 / 破壞性動作且未被既有授權涵蓋**
   - 正例：解法需要 `git push --force` → 問
   - 反例：`~/Desktop/projects/` 下 commit + push feature branch → 已被既有授權涵蓋、直接做
2. **scope 變更**
   - 正例：修 bug 發現根因在另一個 service 的 schema、要改它才能真正解 → 問（使用者沒提那個 service）
   - 反例：修 bug 需要同步改同 repo 內的呼叫端 → 順著原請求的影響面、直接做
3. **goal-gen 五類 human blocker**（`~/.claude/commands/goal-gen.md` PENDING_USER_ACTION 同款五類）
   - 正例：需要 `gcloud auth login` → 給出「請在終端跑 `! gcloud auth login`」後停
   - 反例：有非互動 setter 的 config 變更（`config set` / flag / 直接寫 documented schema）→ 先查三點再說做不到（[[feedback_dont_overapply_interactive_cli_rule]]）
4. **修正額度用盡 + 換路仍不過**
   - 正例：「額度用盡 + 換路都卡在 X；試過 A（因 Y 排除）、B（因 Z 排除）；剩 C 但要動 prod config，要走嗎？」
   - 反例：第一次失敗就問「怎麼辦」（還沒用完自己的修正額度）
