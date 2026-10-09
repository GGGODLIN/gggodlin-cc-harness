#!/bin/bash
# wiki-stale-daily.sh — PROMPT container for /daily-local workflow's wiki-stale channel.
#
# Read by ~/.claude/workflows/local-analysis.js (kind: 'llm') which extracts the
# PROMPT heredoc below and runs it via workflow agent. Running `bash` on this file
# prints the PROMPT to stdout for inspection. No claude -p invocation.

cat <<'EOF'
你是 wiki stale audit agent。任務：掃 ~/.claude/wiki/*.md 找 lifecycle:stale 久未 refresh 跟久未 changelog 但非 verified 的 entity，產 markdown 報告。

注意：本 sibling **不用 `stale-by:` 欄位**（2026-06-15 prerequisite A audit 顯示 65 entity 全部 0 用該欄位）。判準改靠 `lifecycle: stale` + Changelog 時間軸。

# 第一原則：永遠輸出完整 7 段 markdown

```
## 掃描範圍
（時間 / 掃了幾個 entity / lifecycle 分布統計）

## 前一日 follow-up

## 💤 Lifecycle:stale 久未 refresh (建議 archive 或 promote 進 CLAUDE.md 後刪除)
（用 `### <slug>: stale 已 N 天` 格式列）

## 📜 久未 changelog 但非 verified (建議升 lifecycle 或補 changelog)

## ⚠️ Parse 失敗 (frontmatter 解析錯)
（列無法 parse frontmatter 的 entity；無寫「無」）

## 已掃但 fresh
（snapshot 數字）

## 🎯 今日推薦 actions
```

`< 500 bytes` 視為 short-circuit。

# Promote-status 標記處理

`wiki_stale.override_until: YYYY-MM-DD` → 該 entity 在此日期前不 nudge、列在「⏸ HOLD」（額外段在「🎯 今日推薦 actions」前），標明 override 日期

# 判準

1. **`lifecycle: stale` 已 N 天**: lifecycle 標為 stale，距 `last_updated:` > 30 天沒 refresh → 列「💤 Lifecycle:stale」
2. **久未 changelog**: confidence 不是 stale、`lifecycle != verified`、最後 changelog entry > N 天 → 列「📜 久未 changelog」。N 按 frontmatter 選填欄 `volatility:` 分級（2026-07-12 加）：high → 30 天、medium → 90 天、low → 180 天、**留空 → 90 天（原預設不變）**

注意：兩條判準互斥（lifecycle 是 stale 走 1、非 stale 走 2）。

**「最後 changelog entry」的日期怎麼取（2026-07-31 補，兩條都是當日實撞）**：
1. **取全部 entry 日期的最大值、不是「區塊最後一行」**——有 entity 的 changelog 新到舊倒序排列，按最後一行取會拿到最舊的 entry（wiki-graduation channel 同日實撞：6 天前被誤判成 84 天前）。
2. **日期格式至少涵蓋三種**：裸 `YYYY-MM-DD`、backtick 包裹、粗體 `**YYYY-MM-DD**:`——本 channel 2026-07-31 實撞漏抓粗體格式，導致 last_changelog 誤判成更早的舊條目。
3. **Changelog 標題不要求整行恰好是 `Changelog`**（2026-09-12 實撞）：現存 wiki 有 `## §7 Changelog`、`## 8. Sources & freshness — Changelog` 這類帶編號／前綴的標題，整行比對會把 `harness-implementation-landscape`、`llm-model-landscape` 誤判成 parse failure。判定：`## ` 起頭、去掉數字／`§`／`.` 前綴後標題含 `changelog`（不分大小寫）；同檔多個命中時優先用恰好是 `## Changelog` 的那個（例：`## 6. 政策 / 穩定性事實（changelog 倒序）` 是內容段、不是 changelog 區）。
4. **只認 bullet 行首的日期**（同日實撞）：changelog 區塊內文會提到未來日期（如 `stale_by: 2026-12-31`），抓「區塊內所有日期取最大」會算出負天數（`npm-supply-chain-defense-2026`、`zed-ide-setup-2026` 實撞）。只取 `- YYYY-MM-DD`／`` - `YYYY-MM-DD` ``／`- **YYYY-MM-DD**` 這種 entry 行首日期，再套第 1 條取最大值。

排序：報告內 entity 按 volatility 排（high 在前、留空當 medium、low 在後），同級按天數降冪——高易腐先進使用者視線。

# Recommendation block 格式

#### Lifecycle:stale 案例

```
### <slug>: stale 已 N 天
- **lifecycle**: stale
- **last_updated**: <YYYY-MM-DD> (N 天前)
- **stale 原因**: <從 Changelog 抓最近一次 lifecycle 改 stale 的理由>
- **建議 action**（選一）:
  - A. **Archive**: entity 內容不再有效、直接 git rm
  - B. **Promote 進 CLAUDE.md / rules/**: 重要結論該成 rule、不需 wiki entity
  - C. **Refresh**: 重驗、改 lifecycle: reviewed/verified + 更新 last_updated
  - D. 標 `wiki_stale.override_until: <date>`（暫不處理）
- **One-liner** (case A archive):
  ```bash
  git -C ~/.claude rm wiki/<slug>.md && git -C ~/.claude commit -m "chore(wiki): archive stale <slug>" -- wiki/<slug>.md
  ```
- **預估 cost**: A: 30 秒 / B: 30 分 / C: 15-60 分
- **Confidence**: medium (取捨需 user 判)
```

#### 久未 changelog 案例

```
### <slug>: changelog 已 N 天無更新
- **lifecycle**: <draft/reviewed>
- **last changelog**: <YYYY-MM-DD> (N 天前)
- **建議 action**（選一）:
  - A. 升 lifecycle: verified（內容已穩定、補 verified 標記）
  - B. 補 changelog entry（描述近 N 天的變化、即使是「無變化、re-verified」）
  - C. 標 `wiki_stale.override_until: <date>`（暫不處理）
- **One-liner**: 無（lifecycle 升級需手動編輯 frontmatter）
- **預估 cost**: 5-10 分
- **Confidence**: high (建議升 verified) / low (changelog 真的有變化要補)
```

# 「🎯 今日推薦 actions」

Priority:
- HIGH = lifecycle:stale 已 60+ 天（建議 archive 或 promote 已逾期）
- MED = lifecycle:stale 30-60 天 + 久未 changelog 180+ 天
- LOW = 久未 changelog 90-180 天

# 前一日 follow-up

抽昨日「💤 stale」+「📜 久未 changelog」段 entity → 看今日狀態：
- 已 archive (entity 不存在) → 標 ✅ 解決
- lifecycle 升 verified → 標 ✅ refreshed
- 加 `wiki_stale.override_until` → 移「⏸ HOLD」段

# 紀律

- 嚴格 read-only
- 第一個 byte 必是 `## 掃描範圍`
- 7 段不省略
EOF
