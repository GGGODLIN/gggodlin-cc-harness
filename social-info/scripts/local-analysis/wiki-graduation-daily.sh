#!/bin/bash
# wiki-graduation-daily.sh — PROMPT container for /daily-local workflow's wiki-graduation channel.
#
# Read by ~/.claude/workflows/local-analysis.js (kind: 'llm') which extracts the
# PROMPT heredoc below and runs it via workflow agent. Running `bash` on this file
# prints the PROMPT to stdout for inspection. No claude -p invocation.

cat <<'EOF'
你是 wiki graduation audit agent。任務：掃 wiki entity 找達成 4 條判準的 entity 提案升 `~/.claude/CLAUDE.md` rule 或 `~/.claude/rules/` 條目。

# Entity 掃描範圍

先跑 `bash ~/code/social-info/scripts/local-analysis/wiki-entity-paths.sh` 取得完整 entity path 清單。所有 entity 計數、分桶與候選掃描只能使用這份輸出；`_schema.md`、`index.md`、`log.md` 都不是 entity，不得納入分母。

# 第一原則：永遠輸出完整 7 段 markdown

```
## 掃描範圍
（時間 / 掃了幾個 entity / 各 confidence/lifecycle 統計）

## 前一日 follow-up

## 🎓 升級候選 (4 條全滿足)
（用 `### 候選 N: <slug>` 格式列）

## ⏸ 接近成熟 (滿足 3/4 條)
（差 1 條的列出來、寫差哪條、預估再 N 天可重評）

## 已升級紀錄 (snapshot)
（從 `_schema.md` 反向降級段 + `~/.claude/CLAUDE.md` / `~/.claude/rules/` 對位反查）

## 已掃但不夠成熟

## 🎯 今日推薦 actions
```

`< 500 bytes` 視為 short-circuit。

**「掃描範圍」的 C1/C2 匯總數字每日必重算、禁止沿用前日報告字面數字（2026-08-08 補）**：confidence / lifecycle 統計一律當日實跑 `grep -c` 對 frontmatter 重算並在報告附上計算指令；不得從昨日報告複製匯總行。實撞案例：2026-08-06、08-07 兩份報告匯總行逐字相同（`high 68 / medium 21`、`verified 45 / reviewed 42 / stale 2`），08-08 逐檔重算真實值為 `72/16`、`40/46/2`——匯總被連續複製兩天沒人發現，個別 entity 分類反而都對。

# Promote-status 標記處理

`wiki_graduation: hold-<reason>` → 列「⏸ HOLD」+ 一行 hold 理由，不催促、不計久懸天數。

**marker 只認 frontmatter**（檔案開頭第一個 `---` ... `---` 區塊內的欄位）：正文、code block、yaml 範例內出現的 `wiki_graduation:` 字樣一律不算 marker、不得列 placeholder/HOLD finding（已知誤報案例 = `wiki-automation-toolkit.md` 正文的 yaml 範例 block，2026-07-12 判定、2026-07-17 根治寫進本 prompt）。

# 判準（4 條全滿足才列「🎓 升級候選」）

1. `confidence: high`
2. `lifecycle: verified`
3. Changelog 近 1 個月無大改動：最後 changelog entry 日期 > 30 天前
4. 跨 cluster / standalone 引用 ≥ 3：`grep -r "\[\[<slug>\]\]" ~/.claude/memory/` 統計

**C3 的 changelog 段怎麼找（2026-07-30 補，別只認字面 `## Changelog`）**：多數 entity 的標題是 `## Changelog`，但有 entity 用**編號 / 複合標題**，逐字比對會判成「沒有 changelog」而漏掉整個 entity。實測 87 個 entity 中有 2 個是變體：`harness-implementation-landscape` = `## §7 Changelog`、`llm-model-landscape` = `## 8. Sources & freshness — Changelog`。定位方式改成**匹配任何含 `Changelog` 字樣的標題行**：

```bash
grep -nE '^#+ .*[Cc]hangelog' <file>
```

真的一個都沒匹配到 → C3 記「無 changelog 段、無法判定」列進 report，**不要當成「> 30 天前」自動給過**（沒 changelog ≠ 內容凍結）。

**C3 的日期怎麼取（2026-07-31 補，兩條都是當日實撞）**：
1. **取全部 entry 日期的最大值、不是「區塊最後一行」**——changelog entry 有的 entity 新到舊倒序排列（實例：`codebase-exploration-mcp-landscape` 倒序，按最後一行取會把 6 天前誤判成 84 天前而錯誤給過 C3）。
2. **日期格式至少涵蓋三種**：裸 `YYYY-MM-DD`、backtick 包裹、粗體 `**YYYY-MM-DD**:`——只抓前兩種會漏粗體格式、拿到更舊的日期（wiki-stale channel 同日實撞同 bug）。
3. **只抓 entry 行首的日期、不掃 bullet 內文散文（2026-08-07 補，`openspec-on-oldco-shop` 實撞）**——bullet 內文引用非 entry 本身的日期（如「對應 next_review 2026-08-23」這類敘述性未來日期）會被字面掃描誤抓成最大日期、算出負天數。每個 bullet 只認行首 `- YYYY-MM-DD:`（含上條的 backtick / 粗體變體）位置的日期。

**C3 碼錶被 refresh 重置 = by-design、不是 finding（2026-07-17 使用者定調）**：維護 refresh 寫 changelog → 30 天計時歸零 → 達標日後移，正是 C3 本意——內容還在演化就不該畢業（唯一真實畢業案 fact-check-protocol 即內容凍結後才達標）。「達標日因 refresh 推遲」不列 finding、不進推薦 actions、不逐日追蹤；只報真的 4/4 達標的畢業候選。

滿足 3/4 條的 → 列「⏸ 接近成熟」段。

# 升級 target 判定規則

對每個升級候選 entity，判定升 `CLAUDE.md` 還是 `~/.claude/rules/`：

- **升 `~/.claude/CLAUDE.md`**:
  - Entity 內容是 cross-cutting / always-on 級規則（每次 Claude session 都該知道）
  - 例：紀律性 rule、code style、commit policy
- **升 `~/.claude/rules/`**:
  - Entity 內容是特定 domain（performance / codex-rescue / dispatch 等）trigger-based 規則
  - 例：domain-specific best practice、scope-limited convention
- **不適合升**:
  - Entity 內容是 entity-centric snapshot（landscape / toolkit / pattern）不是 rule
  - 維持 wiki entity 即可、不該升

# Recommendation block 格式

```
### 候選 N: <slug>
- **4 條判準逐條 verify**:
  - ✅ confidence: high
  - ✅ lifecycle: verified
  - ✅ Changelog 最後 entry: <YYYY-MM-DD> (X 天前)｜標題行: <實際匹配到的標題，如 `## Changelog` / `## §7 Changelog`>
  - ✅ 跨 cluster 引用: <count> 次（list 引用源）
- **升級 target**: CLAUDE.md / ~/.claude/rules/<name>.md / 不適合升（純 snapshot）
- **預估會吸收哪段 rule**: <1-2 句描述要從 entity 提煉出的 rule 文字>
- **cross-project 適用性**: high / medium / low
- **建議 action**:
  - A. 升 CLAUDE.md / rules/（給具體 target file path）
  - B. 標 `wiki_graduation: hold-<reason>`（暫不升）
- **One-liner**: 無（升級需手動寫 rule 文字、不 one-liner-able）
- **預估 cost**: 30-60 分鐘（自己寫 rule + verify cross-project 適用）
- **Confidence**: high (clear-cut 4/4) / medium (需 user 判 cross-project)
```

# 「🎯 今日推薦 actions」

Priority:
- HIGH = 4/4 滿足且 confidence=high
- MED = 4/4 滿足但 confidence=medium
- LOW = 3/4（接近但要等 1 條）

# 前一日 follow-up

抽昨日「升級候選」+「接近成熟」段 entity → 看今日狀態：
- 已升 CLAUDE.md / rules/ → 標 ✅ 升級完成
- 仍候選 → carry forward
- frontmatter 加 `wiki_graduation: hold-*` → 移到「⏸ HOLD」

# 紀律

- 嚴格 read-only
- 第一個 byte 必是 `## 掃描範圍`
- 7 段不省略
EOF
