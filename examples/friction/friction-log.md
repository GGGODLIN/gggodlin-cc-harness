# friction-log（範例）

> mock 範例：摩擦紀錄的格式照 `friction/PROTOCOL.md` 寫，三條紀錄都是虛構的。實際使用時，有主的摩擦寫在 `~/.claude/skills/<名稱>/friction-log.md`，無主的寫在 `~/.claude/friction/workflow-general.md`。

## 待折

- 2026-01-08 [source_ref=session:0000aaaa#12; signal_type=user-correction; target=skill:demo-skill; feedback_quote=N-A; why=使用者說回報太長、找不到結論] 回報把結論放在最後一段，使用者要捲很久才看到；建議回報第一句固定寫結論。
- 2026-01-15 [source_ref=test:skills/demo-skill/scripts/tests/output.test.sh; signal_type=test-failure; target=skill:demo-skill; feedback_quote=N-A; why=unknown; flags=minor] 輸出範本少了「未驗證項目」欄，契約測試紅；建議範本補一欄並在 SKILL.md 說明何時填。

## 休眠

- 2026-01-10 [source_ref=session:0000bbbb#4; signal_type=agent-observation; target=unknown; feedback_quote=N-A; why=unknown; flags=speculation] 同一個查詢在兩個 session 各跑了一次；建議加快取，但目前一週只發生一次。重開條件：一週內再出現 3 次以上。

## 已折／已否決
