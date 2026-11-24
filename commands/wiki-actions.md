---
description: 讀今日 wiki-* report（lint / cross-link / graduation / stale 4 個 action 類合併 + candidates 候選 FYI）；/daily-local 自動入口僅直接派 wiki-refresher 刷新內容並留其餘清單待決，手動入口等 user 拍板後執行 one-liner / 寫 frontmatter
---

# Wiki Actions

讀今日 5 個 wiki-* report：lint / cross-link / graduation / stale 四個 action 類 report 合併「今日推薦 actions」段（相容有無 `🎯` 前綴）、按 priority + entity group 排序；candidates report 沒有該 heading、獨立處理成報告末尾的「候選 FYI」段（Step 4）。

**唯一寫入端**（4 sibling + wiki-candidates 全 read-only）。入口分兩條且授權邊界不同：
- **`/daily-local` 自動接跑入口**（無人值守）：僅自動派 `wiki-refresher` 執行 `stale／memory delta 刷新型` 並直接 commit；其餘帶 `one-liner` 或需寫 frontmatter 的項目**一律不自動改檔**，合併成待辦清單附於報告末尾留待使用者後續拍板。
- **手動 `/wiki-actions` 入口**：呈現合併清單後等 user 拍板，再經 Guard 1–4 與 show diff 確認後執行批准的 one-liner 與 frontmatter 標記。

## 1. 讀今日 5 個 report

```bash
DATE=$(date +%Y-%m-%d)
for aspect in candidates lint cross-link graduation stale; do
  echo "=== $aspect ==="
  cat ~/code/social-info/reports/local-analysis/$DATE-wiki-$aspect.md 2>/dev/null || echo "(report missing)"
done
```

如果某個 report missing：手動入口跟 user 確認是 sibling 短路 (< 500 bytes) 還是當日跑失敗、要不要重跑該 sibling；`/daily-local` 自動入口不阻塞等待，在摘要標記 missing 並繼續處理其餘已存在的報告。

candidates report 讀進來後**不進 Step 2-3 的機械合併**、只走 Step 4 的候選 FYI 處理。

## 2. 抽四個 action 類 report 「今日推薦 actions」段

**只對 lint / cross-link / graduation / stale 四個 action 類 report** 抽出 `## 🎯 今日推薦 actions` 或無圖示的 `## 今日推薦 actions`（正則 `^## (?:🎯\s*)?今日推薦 actions\b`）之後到 next `##` 之前的內容。candidates report 從來沒有這個 heading（它的段落是 掃描範圍 / 升級候選 / 不確定待決 等）、不在本步驟範圍。

Parse 成 actions list，每個 action 含：
- `sibling` (lint / cross-link / graduation / stale)
- `priority` (HIGH / MED / LOW)
- `entity` (slug，從 `[[<slug>]]` 或 `<slug>:` 抽出，**normalize 去 `[[]]` 後純 slug**)
- `action_desc` (action 文字描述)
- `one_liner` (`→ \`...\`` 後的 command；無 one-liner 標 `(無 one-liner)`)
- `cost` (`~30 秒` / `~15 分鐘` 等)
- `confidence` (high / medium / low)

## 3. 合併演算法（明確規格）

### 3.1 Group by entity

- Group key: entity slug（normalize 後）
- 若 entity 出現在 ≥ 2 個 sibling 的 actions：合併成 entity-level entry
  顯示時列「⚠️ <entity> 被 N 個 sibling 同時 surface」+ 列各 individual action

### 3.2 Priority 排序

- Entity-level priority = MAX(各 sibling 對該 entity 的 priority)
  即：lint 標 HIGH + stale 標 LOW → entity-level 為 HIGH
  ⚠️ **告知 user 這個 MAX 規則可能誤導**（lint HIGH 跟 stale LOW 性質不同但合併成 HIGH）
- 同 priority 內按 confidence 排（high > medium > low）
- 同 confidence 內按 cost 升序（30 秒先於 15 分鐘）

### 3.3 輸出格式給 user

按 entity-level priority 順序列、每 entity 展開列各 sibling 的 individual action：

```
═══ 合併 Action Queue (今日 N 項) ═══

[1] [HIGH ⚠️ MAX-elevated from lint] [[entity-X]]
    被 2 個 sibling surface (lint + stale)：
    1a. [HIGH] lint: 修 broken link [[xxx]] → [[yyy]] (~30s, conf:high)
        → sed -i '' '...' ~/.claude/wiki/entity-X.md
    1b. [LOW] stale: lifecycle:stale 已 45 天 (~15m, conf:medium)
        → 重驗 confidence 或 archive

[2] [HIGH] [[entity-Y]]
    被 1 個 sibling surface (cross-link)
    2a. [HIGH] cross-link: 補 [[xxx]] mention in entity-Y.md:23 (~30s, conf:high)
        → sed -i '' '...'

[3] [MED] ...

[4] [LOW] ...
```

## 4. 候選 FYI（candidates report 獨立處理）

candidates report 不進 Step 2-3 的機械 one-liner 合併，照以下步驟處理：

1. 從 candidates report 摘「升級候選」段：entity slug + 一行升級理由；「不確定待決」有內容也一併摘（標明待決）
2. 在 Step 3.3 合併 queue 輸出的**末尾**單獨列「候選 FYI」段：

   ```
   ═══ 候選 FYI（不進 action queue、不產 one-liner）═══
   - [[entity-A]]: <一行升級理由>
   - [[entity-B]]: <一行升級理由>（待決）
   → 升級走 /wiki-promote 人工路徑（user 另行 trigger）
   ```

3. 候選 FYI 只提示、不執行：不進 Step 5 拍板 queue、不進 Step 6 執行流程（呼應 wiki-candidates-daily.sh 自身「絕不執行 /wiki-promote」的設計意圖）
4. candidates report missing 或「升級候選」為空 → 候選 FYI 段整段省略、不出聲

## 5. 依入口分流（自動接跑 vs 等 user 拍板）

- **若目前由 `/daily-local` 自動接跑進入（無人值守）**：**不等待 user 回應**，僅將合併清單中屬於 `stale／memory delta 刷新型`（無 one-liner、由 `wiki-refresher` 吸收記憶結論）的項目視為已預先授權，直接進入 Step 6.2 派 `wiki-refresher` 執行並 commit；其餘所有 `one-liner` 修改與 frontmatter 標記項目**一律禁止自動執行**，原樣保留於合併清單作為待決提醒後直接跳至 Step 8 輸出 summary。
- **若目前由使用者手動輸入 `/wiki-actions` 進入**：報告完 surface 後等 user 自然語言回應，按以下 pattern 彈性匹配自然語言，不限下列措辭：

- **Approve all**: 「全部做」/「all」/「都做」/「approve all」
- **Approve specific entity**: 「做 entity-X」/「entity-X, entity-Y」/「除了 X 都做」
- **Approve specific number**: 「做 1, 3, 5」/「1-3」/「1 到 5」
- **Decline specific**: 「跳過 X」/「不要 X」/「decline X」
- **Hold specific**: 「hold X 到 2026-09-01」/「X 月底再說」
- **Mixed**: 「做 1, 2, 跳過 3, hold 4」
- **All hold**: 「全部 hold」/「下次再說」/「明天再決定」
- **All skip**: 「跳過」/「都不做」/「skip」

如果回應**模糊**（如「重要的做」/「能做的做」）→ **不要猜、跟 user 確認哪個算重要、哪個算能做**。

## 6. 執行批准的 action

### 6.1 One-liner 安全 guards（必做）

對每個批准的 one-liner，跑前過 4 道 guard：

**Guard 1 — Destructive pattern 黑名單**：grep one-liner 字串、命中以下任一 → 標「⚠️ DESTRUCTIVE: 拒跑、要 user 手動」：

```
rm -rf
rm -r
rm \(no -i flag\)
find .* -delete
xargs rm
> \(no append &>>\)
truncate
dd of=
chmod 7[0-9][0-9]
chmod -R
git reset --hard
git push --force
git push -f
git clean -fd
```

**Guard 2 — Path scope check**：one-liner 操作的檔案路徑必須 fall in：
- `~/.claude/wiki/*.md`
- `~/code/social-info/scripts/local-analysis/*.sh`
- `~/code/social-info/reports/local-analysis/*.md`

超出範圍 → 拒跑 + 列「⚠️ Path 超出 scope, 拒跑」

**Guard 3 — Dry-run 預設**（核心 guard）：對 sed/awk 類 in-place 改動，先 dry-run print diff 給 user 確認才 apply：

```bash
# Dry-run: print 改之後的 content（不寫檔）
sed 's/...//' <file>     # 不加 -i
# 用 git diff 比（wiki entity 是 git tracked）
sed -i.wikiactions.bak 's/...//' <file>
diff <file>.wikiactions.bak <file>
```

User 看 diff 後決定：confirm → 刪 `.wikiactions.bak`；reject → `mv <file>.wikiactions.bak <file>`（restore）。

**Guard 4 — Backup（補保險）**：執行寫入前 `cp <file> <file>.wikiactions.bak.<timestamp>`，跑完 user 確認沒問題後 `rm` backup。

**Cleanup 機制**：本 session 結束時主動跑：

```bash
find ~/.claude/wiki/ -name "*.wikiactions.bak.*" -mtime +1 -delete
```

清理 1 天前的 backup（避免堆積）。

### 6.2 執行流程

對每個批准的 action：

1. 過 4 guards
2. Guard 任一失敗 → 標「⚠️ Guard X 觸發、改成手動指引」+ 給 user 文字步驟
3. 全過 → 跑 dry-run、show diff、user 確認 → 跑 in-place + backup
4. 跑後 verify：再 cat 目標 file 確認改動生效
5. 跑成功 → 刪 backup；失敗 → restore backup + 列 error

對沒 one-liner 的 action 分兩類：

- **stale／memory delta 刷新型**（entity 需吸收 memory cluster 新結論、`last_updated` 落後）→ 派 `wiki-refresher`（Agent tool、`subagent_type: wiki-refresher`），prompt 固定三參數：target entity path、delta source（對應 `~/.claude/memory/_index_*.md` 或明列 memory 檔）、cutoff = entity 現在的 `last_updated`；授權路徑明寫（預設 entity + `index.md` 該行，要動別的檔就列進去）。跑完檢查回報的計數核對與授權路徑無越界，`git diff --stat` 只含授權檔即直接 commit（`docs: refresh <entity> from memory delta`），不等使用者確認；摘要一行進 daily digest 的 Wiki health 段。不要用 routed-judge 或 main 直改代做（2026-08-21 實例：同樣三參數的工作被派給 opus+xhigh）。
- 其他 → 列 user 手動步驟、不嘗試自動執行。

## 7. 寫 decline / hold / override frontmatter

對 user 拍板「跳過」「hold」的 action，寫進對應 wiki entity frontmatter：

```yaml
# decline 例：
wiki_lint:
  orphan: declined
  broken_link_xxx: declined

# hold 例：
wiki_graduation: hold-until-cluster-stable

# override 例：
wiki_stale:
  override_until: 2026-09-01
```

寫入前 show diff（git diff）、user 確認才 commit。

## 8. 完成後 summary

```
═══ /wiki-actions Summary ═══
✅ 執行: X 個 (entity list)
⏸ Hold: Y 個 (entity + override 日期)
🚫 Decline: Z 個 (entity + finding key)
⚠️ Manual 待 user: W 個 (列出哪些需要手動)
🧹 Cleanup: 刪 N 個 backup file
```

## 紀律

- **不放 hook、不放 cron**；自動入口只有 `/daily-local` 收尾那一條（見檔頭）
- **dry-run 預設**（手動入口執行 one-liner 時 Guard 3 是核心紅線；自動入口完全不執行 one-liner）
- **寫入邊界明確**：手動入口寫入 one-liner 或 frontmatter 前必 show diff 等 user 確認；`/daily-local` 自動入口僅授權 `wiki-refresher` 在核對授權路徑無越界後直接 commit，其餘改動一律只列清單等使用者拍板
- 4 sibling + wiki-candidates 全 read-only，本 command 是唯一寫入端
