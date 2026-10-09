---
description: Memory 系統健康度 read-only 診斷（不動 file，輸出 structured health report）
---

<!-- 本檔在契約測試底下：commands/tests/memory-audit-contract.test.sh — 改動後跑 `bash ~/.claude/commands/tests/memory-audit-contract.test.sh` -->

# Memory Audit

跑 read-only 健康度檢查。**不動任何 file**，輸出結構化 health report。

⚠️ **Multi-session safety**: 跨 session 平行編輯 memory 是常態。本 command 永遠讀**當下 file 系統實際狀態**（Bash / Read tool），**不依賴** CC inject 的 MEMORY.md snapshot（那是 session start 時的，不會即時 update）。看到 mismatch 先確認是當下狀態還是某個 session 的 mid-process。

## 1. 抓基本資訊

```bash
# consolidated 大腦優先：autoMemoryDirectory（settings.local.json > settings.json）；否則退回 per-project scope
MEMORY_DIR=$(jq -r '.autoMemoryDirectory // empty' "$HOME/.claude/settings.json" "$HOME/.claude/settings.local.json" 2>/dev/null | grep . | tail -1)
MEMORY_DIR="${MEMORY_DIR/#\~/$HOME}"
if [[ -z "$MEMORY_DIR" ]]; then
  PROJECT_HASH=$(pwd | sed 's|^/|-|; s|/|-|g')
  MEMORY_DIR="$HOME/.claude/projects/$PROJECT_HASH/memory"
fi
[[ -d "$MEMORY_DIR" ]] || { echo "no memory dir ($MEMORY_DIR)"; exit 0; }
ls "$MEMORY_DIR"/_index_*.md 2>/dev/null   # 動態 audit cluster 結構（不要記固定 list）
```

## 2. Audit 13 個維度

> 掃描範圍：root + `general/` + `work/` + `projects/`；archive/ 與備份目錄一律不掃。

**每輪先讀修復紀律（2026-09-25 加入）**：任何維度提「建議修法」之前，先執行下面這段把規則檔的「當場修邊界與修復紀律」原文讀進 context，提修法時逐條遵守（歷史快照保留日期不改寫、現在式狀態改「日期＋觀察」或「去哪查」、索引只指路不寫現況值）。規則正本在該檔，本 command 不抄一份，改動只改那裡。

```bash
R=$(sed -n '/^## 當場修邊界與修復紀律/,/^## Tier 3:/p' "$MEMORY_DIR/feedback_memory_cluster_maintenance.md" | sed '$d')
[ -n "$R" ] && printf '%s
' "$R" || echo "REPAIR-RULES-UNAVAILABLE（規則段標題改名或檔案缺失；仍照常提修法，報告標記本輪未讀到規則段）"
```


**`[[slug]]` 四路解析規則（2026-07-26 加，全維度適用、含 I 維度抽驗）** — 判定任何 `[[slug]]` 是「格式打錯 / 指向不存在 / broken」之前，**必須依序試完四條路徑，任一命中即為有效引用、不得列為問題**：

1. `~/.claude/wiki/<slug>.md` 存在 → wiki entity 引用
2. memory 樹任一檔 frontmatter `name: <slug>` → memory 檔互引（例：`[[bitbucket-api]]` → `memory/work/oldco-shop/reference_bitbucket_api.md`）
3. memory 樹存在檔名 `<slug>.md`（含 general/ work/ projects/ 子目錄）→ 檔名引用（例：`[[_index_cc_internals]]`，它的 frontmatter name 是 `CC internals cluster index (38 entries)`、對不上路徑 2）
4. slug 帶 `#anchor` → strip anchor 後重跑 1-3

```bash
# 一條龍判定（$s = slug）
s="${s%%#*}"
[ -f ~/.claude/wiki/"$s".md ] \
  || grep -rql "^name: $s\$" ~/.claude/memory/ \
  || [ -n "$(find ~/.claude/memory -name "$s.md" -print -quit)" ] \
  && echo VALID || echo BROKEN
```

**實測分佈（2026-07-26 全樹 617 個 slug）**：路徑 1 命中 87 / 路徑 2 命中 84 / 路徑 3 命中 404 / 四條皆不中 42。**只查路徑 1 會把 488 個有效引用誤判成 broken** —— 這正是 07-25 `[[bitbucket-api]]`、07-26 `[[awesome-harness-engineering-eval-2026-05-30]]` 連兩天被誤報成待辦的根因（兩者都走路徑 2）。

**四條皆不中也未必是 broken，下列一律不報**：

- **inline code / fenced code block 內的 `[[...]]`**不是 wikilink：Markdown 不會解析程式碼範圍內的連結語法，先剝除這兩類範圍再掃描
- **bash `[[ ]]` 測試語法**不是 wikilink：slug 含空白 / `$` / `==` 或以 `-` 開頭 → 跳過（全樹 22 處，如 `[[ -f "$cache" ]]`、`[[ "$event" == "PreToolUse" ]]`）
- **schema 範本佔位符**：`another-entity` / `other-entity` / `wiki-entity` / `wiki-link` / `entry` / `link` / `name` / `X` / 含 `<>` 尖括號者（如 `reference_<harness>_eval_<date>`）
- **skill 名與 rules 檔名**：指向 `~/.claude/skills/` 或 `~/.claude/rules/`、本來就不在 memory/wiki 樹內（如 `[[brainstorm]]` / `[[to-spec]]` / `[[to-tickets]]` / `[[implement]]` / `[[dispatch-and-verify]]`）

### A. Size + lines vs CC 25 KB / 200 lines hard limit

```bash
size=$(wc -c < "$MEMORY_DIR/MEMORY.md")
lines=$(wc -l < "$MEMORY_DIR/MEMORY.md")
entries=$(grep -c '^- \[' "$MEMORY_DIR/MEMORY.md")
```

判定：
- ❌ `size >= 25000` 或 `lines >= 200` → over limit，需 trim
- ⚠️ `size >= 22500` (90%) → 接近 limit
- ✅ otherwise

分域 `_INDEX.md` 順帶列示（2026-07-10 擴充）：hard limit 只作用於 auto-inject 的 MEMORY.md，分域 drill 檔無 hard limit——純資訊列出、供肥大觀察，不進 ❌/⚠️：

```bash
cd "$MEMORY_DIR"
for idx in general/_INDEX.md work/_INDEX.md projects/_INDEX.md; do
  printf '%s\t%s bytes / %s lines\n' "$idx" "$(wc -c < "$idx")" "$(wc -l < "$idx")"
done
```

### B. 結構 check

驗證（2026-07-10 對齊分域架構：`## Project` 段已由 `## 分域路由` 取代，不再檢查）：
- MEMORY.md 含 4 sections: `## 分域路由`（prefix match，heading 後帶括號說明）, `## User`, `## Feedback`, `## Reference`
- Reference 段含 `### Cluster indexes` + `### Standalone reference` sub-sections
- 分域路由段的 4 個 drill 目標實際存在：`_index_personal_projects.md`、`general/_INDEX.md`、`work/_INDEX.md`、`projects/_INDEX.md`

```bash
cd "$MEMORY_DIR"
for h in '## 分域路由' '## User' '## Feedback' '## Reference' '### Cluster indexes' '### Standalone reference'; do
  grep -q "^$h" MEMORY.md || echo "MISSING SECTION: $h"
done
for t in _index_personal_projects.md general/_INDEX.md work/_INDEX.md projects/_INDEX.md; do
  [ -e "$t" ] || echo "MISSING DRILL TARGET: $t"
done
```

判定：❌ section 缺或 drill 目標缺（有輸出）/ ✅ 完整（兩段皆無輸出）

### C. Cluster integrity

僅 root `_index_*.md`（cluster 語意綁 root）；分域目錄的 `_INDEX.md` 完整性由 L 維度對帳覆蓋。對每個 `_index_*.md`:
1. Frontmatter `(N entries)` 跟 `## Entries` 段內實際 `- [` 行數對齊？
2. Cluster 內每個 entry 指向的 source file 存在嗎？

判定：❌ count mismatch → 修 frontmatter；❌ broken link → 處理孤兒指向；✅ otherwise

**Ground-truth 算法（強制跑 bash，不要 LLM 目測）** — 2026-06-22 補：之前 LLM 目測會把 `## Cross-reference` 段的 `- [[name]]` wiki link 跟 `## Deep research 報告` 段的 `- **name** ...` 條目也算進 entries（實例：`_index_search_api_landscape.md` Entries 段真實 4 條 + Cross-reference 段 8 條 → audit 誤報「標 4 實際 12」）。**只算 `## Entries` heading 到下一個 `##` heading 之間、且 `^- \[name\](file.md)` markdown link 形式的行**：

```bash
cd "$MEMORY_DIR"
for idx in _index_*.md; do
  # frontmatter declared count（吃兩種格式：正文 `(N entries)` / frontmatter `name: <slug>-N-entries`）
  declared=$(grep -oE '\([0-9]+ entries\)' "$idx" | head -1 | grep -oE '[0-9]+')
  [ -z "$declared" ] && declared=$(grep -oE '^name: .*-[0-9]+-entries$' "$idx" | head -1 | grep -oE '[0-9]+-entries' | grep -oE '^[0-9]+')
  # frontmatter 與正文都沒宣告筆數 → 只能靠 MEMORY.md pointer 文字人工核對，跳過機械比對
  [ -z "$declared" ] && continue
  # actual entries: 只掃 ## Entries section（到下一個 ## 為止），只算 `- [name](file.md)` markdown link 開頭行
  actual=$(awk '
    /^## Entries/ {in_e=1; next}
    /^## / && in_e {in_e=0}
    in_e && /^- (❌ |⏸ |✅ )?\[.+\]\([^)]+\.md(#[^)]*)?\)/ {n++}
    END {print n+0}
  ' "$idx")
  if [ "$declared" != "$actual" ]; then
    echo "COUNT MISMATCH: $idx declared=$declared actual=$actual"
  fi
done
```

**斷然規則**：`## Cross-reference` / `## Deep research 報告` / `## Background` / 任何 `## Maintenance` 等非 `## Entries` 段內的 `- [...](file.md)` 或 `- [[name]]` link **一律不算 entry**。前者是延伸閱讀指標、後者是 cross-link，跟 cluster entries 計數無關。**anchor link `(file.md#anchor)` 算合法 entry**（與 D 維度口徑一致）——2026-07-12 修：舊 regex `\(.+\.md\)` 不吃 anchor，把 `_index_auto_memory` 的 mempalace entry（`#^anc-` anchor link）誤報成 count mismatch 連續兩天。**marker 前綴（`- ❌ [` / `- ⏸ [` / `- ✅ [`）算合法 entry 行**、declared 抽取同時吃 `name: <slug>-N-entries` frontmatter 格式且抽不到宣告數就 skip——2026-07-13 修：舊 regex 對新 frontmatter 格式誤報 14 個假 mismatch（declared 全空白）+ `_index_active_trials` 的 2 條 `- ❌ [` 收案 marker 行漏數。⚠️ 同日教訓：agent 跑 C 維度時「actual 條數」也必須貼 bash 輸出、不得目測——07-13 audit 對 `_index_tool_eval_outcomes` 目測 46 條、bash 實數 50 條，❌ 判定整個是誤報。

### D. Orphan + double-ref

僅 root（cluster 語意綁 root）；分域子目錄檔案的孤兒 / 漏列由 L 維度 `_INDEX` 雙向對帳覆蓋。

- `all_topics` = `*.md` 排除 `MEMORY.md` + `_index_*` + `_orphan_registry.md`
- `ref_in_memory` = MEMORY.md 內 link target（排除 cluster pointer，即 `_index_*` 開頭）
- `ref_in_cluster` = 各 cluster file 內 link target
- `intentional_orphans` = `_orphan_registry.md` 內列出的 file（grep `^| \`(.+\.md)\`` 抓 filename）
- **link target 解析規則**：抓 `(filename.md)` 或 `(filename.md#anchor)` 皆視為 reference filename — strip `#anchor` 後再跟 `all_topics` 比對。漏抓 anchor link = mempalace-style false positive。
- **Orphan** = topic file 在 dir 但無 reference
- **Intentional orphan** = orphan 命中 `intentional_orphans` set（E pass / 25KB cap 時 prune 但不刪檔）
- **Unregistered orphan** = orphan 且不在 registry 內 — 真的「忘記補 index」case
- **Double-ref** = 同時在 MEMORY.md standalone + 某 cluster file（違反 cluster maintenance rule）

判定：
- ❌ `Unregistered orphan` 非 0 → 立刻修（加進 cluster / MEMORY.md / 刪檔 / 確定故意 prune → append 到 `_orphan_registry.md`）
- ❌ `Double-ref` 非 0 → 立刻修
- ⚠️ `Intentional orphan` 非 0 → suggestion 區列出（標 registry hit、可審視是否仍合理）
- ✅ `Unregistered orphan` + `Double-ref` 皆 0

**Ground-truth 算法（直接跑，不要靠 LLM 目測掃 link）** — 2026-06-04 補：之前 LLM 目測會漏算 `ref_in_cluster`，把已登錄在 `_index_*.md` 內的檔誤判成孤兒（實例：`feedback_brainstorm_skills_偏收斂.md` 被 `_index_tool_adoption_discipline` link、`project_video_research_skill_固化.md` 被 `_index_video_research` link，兩者皆非孤兒卻被誤報）。**link target regex 必須用 `[^() ]` 而非 `[A-Za-z0-9._-]`，否則漏抓中文檔名**。2026-06-16 再補：cluster index 內混用兩種 link 風格（`[name](file.md)` markdown 形式 + `[[name]]` wiki 形式），原演算法只抓 markdown 形式 → 在 cluster index 內用 `[[]]` 引用的條目仍被誤判成 orphan（實例：`feedback_verify_jd_before_judging` 被 `_index_career_finance:25` + `_index_ai_career_landscape:3` 兩處 `[[]]` link，原演算法抓不到）。**ref 要同時抓兩種 link 形式**：

```bash
cd "$MEMORY_DIR"
# referenced = MEMORY.md + 各 cluster index 內 link target（markdown `(file.md)` ∪ wiki `[[name]]`，含 #anchor strip）∪ registry intentional
ref=$( {
        # markdown link 形式：(file.md)
        grep -hoE '\([^() ]+\.md(#[^)]*)?\)' MEMORY.md _index_*.md 2>/dev/null \
          | sed -E 's/^\(//; s/\)$//; s/#.*$//';
        # wiki-style link 形式：[[name]] → normalize 成 name.md（不帶 ext 慣例）
        grep -hoE '\[\[[^][]+\]\]' MEMORY.md _index_*.md 2>/dev/null \
          | sed -E 's/^\[\[//; s/\]\]$//' | sed 's/$/.md/';
        # registry intentional orphan
        grep -hoE '^\| `[^`]+\.md`' _orphan_registry.md 2>/dev/null \
          | sed -E 's/^\| `//; s/`$//';
      } | sort -u )
echo "--- Unregistered orphan ---"
ls *.md | grep -vE '^(MEMORY|_index_.*|_orphan_registry)\.md$' | sort -u | while read -r f; do
  printf '%s\n' "$ref" | grep -qxF "$f" || echo "UNREGISTERED ORPHAN: $f"
done
echo "--- Double-ref（同時在 MEMORY.md standalone + cluster index）---"
memref=$(grep -hoE '\([^() ]+\.md(#[^)]*)?\)' MEMORY.md | sed -E 's/^\(//; s/\)$//; s/#.*$//' | grep -vE '^_index_' | sort -u)
cluref=$(grep -hoE '\([^() ]+\.md(#[^)]*)?\)' _index_*.md | sed -E 's/^\(//; s/\)$//; s/#.*$//' | sort -u)
printf '%s\n' "$memref" | while read -r f; do
  [ -n "$f" ] && printf '%s\n' "$cluref" | grep -qxF "$f" && echo "DOUBLE-REF: $f"
done
```

兩段都印空 = `Unregistered orphan` / `Double-ref` 皆 0。**有輸出才進 ❌；不要從 LLM 對 link 的印象判孤兒。**

**斷然規則 — 死 link 偵測絕不從散文純文字抓 `.md` 字串**（2026-06-22 補）：之前 LLM 目測會把段落純文字提到的 `CLAUDE.md` / `SKILL.md` 當成死 link（實例：`_index_config_authoring_discipline.md` 散文 6 處出現 `CLAUDE.md` 純文字描述、唯一真正的 markdown link 是 `feedback_cross_cutting_workflow_trigger_to_claude_md.md` 該檔存在 → audit 誤報「死 link 指向不存在的 CLAUDE.md」）。**Link 必須是 markdown `(file.md)` 或 wiki `[[name]]` 兩種形式之一才算 link**；散文內的 `CLAUDE.md` / `SKILL.md` / `MEMORY.md` 字串一律不算。Regex 已限定 `\([^() ]+\.md\)` / `\[\[...\]\]`、嚴格照跑就不會誤判。

### E. Cluster pointer alignment

- Dir 內 `_index_*.md` 數量 vs MEMORY.md cluster pointer 數量
- **Pointer 集合 = `### Cluster indexes` 段 ∪ `## 分域路由` 段內的 `_index_*` link**（2026-07-10 補：分域改版後 `_index_personal_projects` 的 pointer 在分域路由段而非 Cluster indexes 段，只算後者會偽陽性「dir 30 vs pointer 29」）
- 兩集合元素對齊？
- 分域目錄 `_INDEX.md` ↔ router 的對帳走 L 維度，不在本維度

判定：❌ dir 有 cluster file 但 MEMORY.md 沒 pointer / ❌ MEMORY.md 有 pointer 但 dir 沒 file / ✅ 完全對齊

### F. Cluster maturity（read-only suggestion only）

僅 root cluster（成熟度 / wiki-promote 判準只對 root `_index_*` 有意義）；分域子目錄的結構健康由 L 維度 `_INDEX` 對帳覆蓋。對每個 cluster:
- Entry count
- Working tree mtime（最舊 / 最新；用 `stat -f %Sm -t %F` 拿 entries 的 mtime）
- Git log 最近 commit（若 git 可用）
- **Wiki coverage cross-check**（2026-05-22 加入，see [[feedback_local_analysis_audit_cross_check]]）：
  1. 以 cluster link target（例 `(_index_ai_career_landscape.md)`）抓出 MEMORY.md 的完整 pointer 行，只看第一個 `→` 後方的文字。
  2. 從該段抽出**每一個** `[[slug]]`，逐一檢查 `~/.claude/wiki/<slug>.md` 是否存在。不要要求固定尾詞 `wiki`，也不要假設只有一個 link；`→ [[a]] + [[b]] wiki` 與 `→ 已併入 [[c]]` 都是合法 coverage 形狀。
  3. 任一 wiki file 存在 → **cluster 已 wiki 化**，即使 mature 也**不列為 `/wiki-promote` 候選**；報告列出所有命中的 slug。
  4. pointer 沒有可用 wiki file 時，才以 cluster 主題的 2–3 個 canonical term 搜 wiki；有 plausible entity 就讀內容判 coverage，不得因 pointer 格式不同直接判 promotable。
  - pointer 有 wiki slug 但 file 不存在 → ⚠️ stale pointer，建議補建或更新 pointer
  - pointer 與內容搜尋都無 coverage → 才是真正的 promote 候選

完成判準：每個 `mature & promotable` 項目都附 `pointer wiki hits=0` 與內容搜尋結果；任一現存 wiki hit 都必須改列 `mature & wiki-covered`。

標籤：
- **mature & promotable**: `>= 3 entries` + 最新 mtime `> 7 天前` + 偏 entity-centric + **無對應 wiki entity** → 提示「考慮 `/wiki-promote`」
- **mature & wiki-covered**: 同上但**已有 wiki entity** → 純資訊列出（wiki slug + last_updated），不提示 promote；如 cluster 新增 entry mtime > wiki `last_updated` → **先查凍結標記再提示**（2026-07-17 加）：
  - **cluster 端 frontmatter 有 `wiki_correspondence: none-*`（如 `none-trial-ledger-convention`）→ 不列 refresh 落差戶、不計天數，一行資訊註明「wiki_correspondence marker 標記為無對應 wiki（原因見 marker 值 + cluster 檔首註記）」**（2026-07-22 加，取代原 wiki-candidates prompt 硬編 `_index_active_trials` skip；trial ledger 類 cluster 或已 SUPERSEDED 對應但仍活躍的 cluster 用此）
  - wiki frontmatter 有 `graduated_to:` → 已畢業凍結、不提示 refresh；改核對 graduated_to 指向的 rule 檔是否落後 cluster，落後才提示「考慮 rule 檔同步」
  - wiki 內文帶 SUPERSEDED / tombstone / Archived 標記 → 不提示 refresh，一行資訊註明「superseded，素材去處見接替 entity 或收案 memory」
  - **上面三個凍結標記皆無時，還要再過一道內容閘才提示（2026-07-30 加，強制）**：`_index_*.md` 自己的 mtime **不是實質變動訊號**——每次新增一行 pointer + 改 frontmatter 計數都會更新它，而那次改動的內容可能早就在 wiki 裡了。提示前必做兩步：(1) 找出 wiki `last_updated` 之後真正有變動的**成員檔**（不是 index 本身）；(2) 抽該成員檔的核心主張，`grep` 對應 wiki entity 確認搜不到。搜得到 → **不提示、不列落差戶**，一行資訊註明「index mtime 較新但內容已吸收（成員 X 的 Y 已在 entity §Z）」。查不動（成員檔太多 / 主張難抽）→ 照提示但標「未驗內容」。
    - 為什麼：2026-07-30 實證，`_index_video_research`（mtime 07-22）比 `video-research-toolchain-2026`（07-11）新，F 維度**連日續報**refresh 落差；逐一比對 cluster 9 個成員後發現唯一實質新增（claude-video `/watch`，07-08）早在 07-11 refresh 就完整吸收（§路由 + 專段 + 光譜表 + cross-link 都在），index 那次改動只是補 pointer 行 + 計數 8→9。沒有這道閘，任何「wiki 已吸收但事後才補 index pointer」的正常維護順序都會製造永久幽靈待辦。
  - 皆無且過了內容閘 → 才提示「考慮 wiki refresh」。為什麼要那三個凍結標記：凍結檔的 last_updated 永遠停格，落差比對會永久誤報（fact-check-protocol 07-16/07-17 連日被提示 refresh 實證）
- **活躍**: 最新 mtime `< 7 天` → 內容還在演進，wait until stable
- **太薄**: `< 3 entries` → 觀察是否該 dissolve 或等累積

判定：純 ⚠️ suggestion，不算 ❌

### G. Standalone clustering opportunities

掃 `### Standalone reference` 段 entry filename + description（2026-07-10 補：原本還掃 `## Project` 段，該段已在分域改版移除；分域子目錄 entry 的 clustering 不在本維度語意內），找：
- 同 keyword / 同 topic 累積 ≥3 條（且不在現有 cluster 內）→ 提示「考慮建新 cluster」

判定：純 ⚠️ suggestion

### H. 死路徑引用偵測（verify-on-schedule，2026-05-30 加入）

memory 條目常引用自有 code/config 路徑（`~/.claude/scripts/...`、`~/Desktop/projects/...`），這些會因改名/搬檔 drift（實例：cc-skill-cleaner→cc-skill-doctor）。本維度做 verify-on-schedule：抽路徑 → `test -e` → flag 死連結。源 `reference_awesome_harness_engineering_eval_2026_05_30.md` D 面向（GitHub Copilot「記憶是新鮮度問題、citation 是 source of truth」）。

**只掃「活工具」路徑前綴**（naive 全路徑掃描實測 over-flag ~120 條噪音：含空格被截斷的 `~/Library/Application`、placeholder、退役工具正確死掉的路徑；收斂到自有活工具才 triage-able、22 條）。掃描範圍含分域子目錄（2026-07-10 擴充；archive/ 不掃）：

```bash
/bin/bash -s -- "$MEMORY_DIR" <<'BASH'
MEMORY_DIR="$1"
PATH_RE='~/(\.claude/(scripts|hooks|workflows|commands|skills|rules)|Desktop/projects|code/social-info)/[A-Za-z0-9._/+*?-]+'
cd "$MEMORY_DIR"
{ find . -maxdepth 1 -name '*.md' -print0; find general work projects -name '*.md' -print0; } \
| xargs -0 grep -HnoE "$PATH_RE" 2>/dev/null \
| awk -F: '{f=$1; n=$2; p=$0; sub(/^[^:]+:[0-9]+:/, "", p); print f"\t"n"\t"p}' \
| grep -vE 'YYYY|MM-DD|/[XY]\.|/[XY]/|\.\.\.|\.bak|-$|/-' \
| sort -u \
| while IFS=$'\t' read -r f n p; do
    raw_p="$p"
    p="${p%[.,)）。、:/]}"; exp="${p/#\~/$HOME}"
    if [[ "$exp" == *[\*\?]* ]]; then
      compgen -G "$exp" >/dev/null && continue
    else
      [ -e "$exp" ] && continue
    fi
    source_line=$(/usr/bin/sed -n "${n}p" "$f")
    source_segment=$(printf '%s\n' "$source_line" | /usr/bin/python3 -c 'import re, sys; p, pattern=sys.argv[1:]; line=sys.stdin.read(); matches=list(re.finditer(pattern, line)); current=next((m for m in matches if m.group(0) == p), None); start=max((line.rfind(sep, 0, current.start()) for sep in ",，;；:：。！？"), default=-1)+1 if current else 0; following=next((m.start() for m in matches if current and m.start() > current.start()), len(line)); print(line[start:following] if current else "")' "$raw_p" "$PATH_RE")
    if printf '%s\n' "$source_line" | /usr/bin/grep -q '^[[:space:]]*>[[:space:]]*更正行 ' || printf '%s\n' "$source_segment" | /usr/bin/grep -qE '已.{0,40}(刪除|移除|退役|結案)|現已不存在|歷史(記錄|紀錄|實例)|示意|若存在'; then
      printf "SELF_NOTE  %-51s ← %s:%s\n" "$p" "$f" "$n"
      continue
    fi
    printf "DEAD       %-51s ← %s:%s\n" "$p" "$f" "$n"
  done | sort -u
BASH
```

**候選來源約束**：H 維度只認上方 pipeline stdout 的 `DEAD` 行為原始 candidate；`SELF_NOTE` 是 pipeline 已從該 path 所在 clause 起點到下一個 path 前的範圍檢出 disposition marker、確定性 suppress 的項目，不得進 ledger cross-check 或人工 suggestion。不得另寫 regex 重建清單、不得把 pipeline 已排除的 `/X.`、`.bak`、行尾 `-` 或 glob 截斷字串加回來。含 `*` / `?` 的 token 必須保留完整 pattern；整段固定交 `/bin/bash` 執行，`compgen -G` 命中至少一個現存路徑就算有效引用，不得列 DEAD。完成判準：報告分列 `SELF_NOTE` 與 `DEAD` 數量，兩者都能逐條對回 pipeline stdout。

對 `DEAD` 行先跑 **ledger cross-check**（2026-07-19 加，根因 = 07-13/07-17/07-18 三輪 triage 均判結案的死路徑連日重報 22 條）：以 stdout 完整一行（`DEAD path ← source file:line`）為候選鍵，逐條 grep `~/code/social-info/reports/local-analysis/pending-actions.jsonl` 找「死路徑 triage」類 status=done 條目的 note——note 已記該路徑（或其所屬批次）triage 結論（修 / 留・已註記）→ **ledger suppress**：不列 ⚠️ suggestion、只在報告記一行「H：N 條死路徑屬已 triage 結案（ledger <date> 條）、suppress」。`SELF_NOTE` 已在 executable pipeline 內完成 disposition 判定，不得再進 ledger 或重複扣除。完成判準：`新死路徑數 = DEAD 行數 - ledger suppress 數`，報告必須列出 `SELF_NOTE`、`DEAD`、ledger suppress、新死路徑四個數字並相等；對不上就標 H 維度執行失敗，不得輸出人工 triage 建議。

剩餘新死路徑判定：**純 ⚠️ suggestion（不是 ❌、不自動改）**。殘留噪音三類，人工 triage 對照：
- 真·活工具搬家/改名 → **修** memory 路徑
- 已自我註記的歷史快照 / 過往專案·試用紀錄 → **留**（死路徑＝事件結束，正確）
- 機制解說的示意路徑（如 rules/shopify.md 舉例）→ **留**（範例非宣稱）

（可折進第 6 點的 Python monolith；上面 bash 是 2026-05-30 實測驗過的收斂邏輯。）

**H-2 接線檢查（wired-but-missing／present-but-unwired，2026-09-25 加入）**：路徑存在不等於還在用——dcg 事故（binary 仍在 `~/.local/bin`、wrapper 已從 settings 拆線 15 天、16 個記憶檔仍當它是現行閘門）就是 `test -e` 抓不到的那類。固定跑這支 deterministic helper，只認它的 stdout：

```bash
W_CHECK="$HOME/.claude/scripts/memory-wired-audit.sh"
[ -x "$W_CHECK" ] || { echo "WIRED-CHECK-UNAVAILABLE"; exit 1; }
OUT=$(mktemp -t wired); "$W_CHECK" > "$OUT"; RC=$?
[ "$RC" -eq 0 ] && { awk '{print $1}' "$OUT" | sort | uniq -c; grep -v '^OK ' "$OUT"; } || echo "WIRED-CHECK-UNAVAILABLE"
```

- stdout 三態每行 `<STATE> <ref> ← <file>:<line>`：`MISSING`（引用的 hook／script／local-bin 工具不在磁碟）、`UNWIRED`（在磁碟，但 settings 兩檔、hooks 目錄內其他腳本、commands／skills 定義都沒提到它）、`OK`。test 檔、placeholder、helper 自己判為歷史敘述的行不會出現。
- 第一行計數表是三態總數（真實樹 2026-09-25：OK 約 1400 行、UNWIRED 約 160、MISSING 約 14），`OK` 行不進 context。**只把 `UNWIRED` 行當候選**，先按 `<ref>` 去重（同一 ref 多處引用算一條、附全部出處），**每輪最多讀 10 條的上下文**，其餘下輪；`MISSING` 與上方 H 的 `DEAD` 重疊，計數列出但不重複列條目。候選先過與 DEAD 相同的 ledger cross-check（以整行為鍵 grep `pending-actions.jsonl` 已結案 note），命中即 suppress。
- `UNWIRED` 是候選不是結論：對剩下的每條，讀該記憶行的上下文，判「這句把它當現行機制」才列 ⚠️（附建議修法），「只是歷史敘述」只在報告記一行、**不寫 ledger**（ledger 以檔為單位，行級判定寫進去會讓 I／K 對整檔停驗）。
- **stdout 含 `WIRED-CHECK-UNAVAILABLE` 或 helper 非零退出** → 報告 H 段寫一行「接線檢查：本輪未查（helper 不可用）」，**不得寫成 0 條**。
- 完成判準：報告列 `UNWIRED` 去重後條數、ledger suppress 數、判歷史數、本輪讀過數、新候選數，數字直接取自上面的計數輸出與去重清單，不靠目測。

### I. 被讀取記憶驗證（demand-driven verify，2026-06-12 加入）

錯誤記憶的成本集中在**被消費的條目**上：從沒被讀的錯記憶行為影響是零，天天被 inject 的錯記憶天天毒化判斷。本維度只驗「最近實際被讀取」的條目（revealed-consumption，源自 MiMoCode dream Phase 3 verify-against-trajectory 的借鑑，2026-06-12）。

**Step 1 — 抽過去 24h 被讀取的 memory 條目**（確定性，零 LLM）：

```bash
cd "$HOME/.claude/projects"
find . -name '*.jsonl' -not -path '*/subagents/*' -newermt "$(date -v-24H '+%Y-%m-%d %H:%M:%S')" -print0 \
| xargs -0 grep -hoE '[A-Za-z0-9_/.-]*\.claude/memory/[A-Za-z0-9_./-]+\.md' 2>/dev/null \
| sed 's|.*\.claude/memory/||' \
| grep -vE '^(MEMORY\.md|_index_|_orphan_registry)' \
| sort | uniq -c | sort -rn \
| while read -r n f; do [ -e "$HOME/.claude/memory/$f" ] && printf '%7d %s\n' "$n" "$f"; done
```

（排除 MEMORY.md / `_index_*` / registry——結構檔由 A-E 維度顧，這裡只驗 topic file。）

⚠️ **最後那道存在性過濾是必要的、不要拿掉**（2026-07-30 加）。上面的 grep 抓的是 jsonl 裡**任何**形如 `.claude/memory/<name>.md` 的字串，不分那是真的 Read 還是散文裡提到的檔名——不存在的檔名一樣會被算成讀取次數。實例：`reference_zzz_test.md` / `reference_statusline_zzz.md` 在 24h 內合計「被讀取」30 次，但兩個檔根本不存在，來源是另一份 hook trial 筆記正文提到的 fixture 檔名。幽靈條目會排到候選清單前面、把每輪只有 3 條的驗證額度整個吃掉。

**殘留限制（已知、暫不處理）**：如果被提到的是**真實存在**的檔案，散文 mention 仍會被算成一次讀取，計數會偏高。要根治得改成只認 `"file_path":"…"`（Read/Edit 的 tool_use input），但那會漏掉 recall 注入、Grep 命中、subagent 代讀等其他真實消費路徑——寧可計數略高也不要漏算消費。排序用得到的是相對高低，絕對值本來就不精確。

**Step 2 — 對照 verification ledger 選驗證對象**：

- Ledger：`$MEMORY_DIR/.verification-ledger.jsonl`（隱藏檔，不會被 D/H 的 `*.md` 掃描掃到），每行 schema：
  ```json
  {
    "file": "<name>.md",
    "entry_type": "leaf | index",
    "verified_at": "YYYY-MM-DD",
    "verdict": "ok | stale",
    "rechecked_at": "YYYY-MM-DD (optional, 後續 recheck)",
    "note": "<一句話>"
  }
  ```
  - `entry_type`：`leaf` = topic file（reference_*.md / feedback_*.md / project_*.md / user_*.md）；`index` = cluster pointer（`_index_*.md`）。router 層走不同覆蓋率分母——audit 報告分開算 leaf vs index 的 verify rate，避免 router 撐大分母造成假低覆蓋焦慮（2026-06-15 D6-F5 driven）。新 entry **必填**；舊 entry 缺欄 audit 時當 leaf 處理（保守 default）。
  - `rechecked_at`：optional。verdict 由 stale 轉 ok（或反向）時記 recheck 日期，方便追蹤「stale 是真實過期還是已自我修復」。
- 每個被讀取的 file 取 ledger 內**最新一筆** `verified_at`（或 `rechecked_at` 若較新）；**從未驗過、或距今 >7 天** → 進候選
- **`skip` 不重驗（2026-09-25 加入，I／K 共用同一語意）**：最新一筆 `verdict` 是 `skip` 且 `verified_at` ≥ 2026-09-25 的 file，只要**檔案 mtime 不晚於那筆 `verified_at`** 就不進候選、不受 7 天／30 天期限影響；檔案之後被改過（例如當場修加了更正行與新現況句）就重新有資格。2026-09-25 以前的 `skip` 是舊語意（anchor 不存在等），不當永久排除。只有 I／K 自己驗到整檔都是歷史或規範時才記 `skip`；H-2／M 的行級判定不寫 ledger。`skip` 給「有日期的歷史快照」或「規範／規則類條目」——它們沒有可對照的現況，重驗只會重複燒額度。記 `skip` 時 `note` 必寫原因（例：`歷史快照 2026-07-05 MiMo 退訂紀錄`）。schema 不變，`verdict` 值集合是 `ok | stale | skip`
- 候選按被讀取次數排序，**每次 run 最多驗 3 條**（bound token 成本，其餘下次輪到）

**Step 3 — 驗證內容**（對每條候選，讀 file 本體後查可便宜驗證的宣稱）：

- 引用的路徑 / 工具 / script 仍存在？（`test -e`，比 H 維度深一層：H 只掃前綴，這裡驗該條目的全部路徑宣稱）
- 宣稱的設定 / 機制仍如描述？（grep 對應 config / settings.json 比對）
- 宣稱的工具版本 / 狀態與當下實況矛盾？（能便宜查就查，不能就標「無法驗證」不要猜）

**Step 4 — append ledger**（本 command read-only 的唯一例外；只 append 不改舊行）。verdict=stale 的條目進 report ⚠️ 區，附矛盾證據，**不自動改 memory file**——修不修由使用者決定。

判定：⚠️ suggestion（stale 條目列出待人工處理）；驗證全 ok 或無候選 → ✅ 一行帶過。

### J. Cold entry 偵測（neglect-driven，2026-06-29 加入）

跟 I 維度方向相反：I 看「最近讀過、要不要重驗」（demand-driven）、J 看「**最近沒讀過、要不要整理**」（neglect-driven）。源 2026-06-29 agent-memory-bench (Kausha3) 四 failure mode 借鑑——cold = recall 反向證據（寫了但 30 天沒被撈到 = recall 在實戰中失敗）。

**Step 1 — 抽過去 30 天 hit=0 的 leaf file**（純確定性、零 LLM）：

```bash
cd "$MEMORY_DIR"
# 2026-07-10 擴充：leaf 集合含分域子目錄（排除各層 _INDEX.md 結構檔；archive/ 不掃）
{ ls *.md; find general work projects -name '*.md'; } \
| grep -vE '(^|/)(MEMORY|_index_.*|_orphan_registry|_INDEX)\.md$' > /tmp/memory-leaf-files.txt

CUTOFF=$(date -v-30d '+%Y-%m-%d %H:%M:%S')
find ~/.claude/projects -name '*.jsonl' -not -path '*/subagents/*' -newermt "$CUTOFF" -print0 2>/dev/null \
| xargs -0 grep -hoE '\.claude/memory/[A-Za-z0-9_./-]+\.md' 2>/dev/null \
| sed 's|.*\.claude/memory/||' \
| grep -vE '^(MEMORY\.md|_index_|_orphan_registry)' \
| sort | uniq -c | sort -rn > /tmp/memory-hits-30d.txt

# hit=0 的 file = leaf file 集合 ∖ 被引用過的 file 集合
comm -23 \
  <(sort /tmp/memory-leaf-files.txt) \
  <(awk '{print $2}' /tmp/memory-hits-30d.txt | sort) > /tmp/memory-cold.txt
```

**Step 2 — 三層分類（結合 mtime 避免把剛寫的新條目當冷）**：

| 分層 | 條件 | 動作 |
|---|---|---|
| **可疑** | 30 天 hit=0 + mtime > 30 天 | 列出、不 actionable（觀察用）|
| **冷死** | 30 天 hit=0 + mtime > 60 天 | 標 review 候選 |
| **化石** | 30 天 hit=0 + mtime > 180 天 | 強烈建議 demote/砍/promote 到 wiki |

mtime < 30 天的新條目跳過（才剛寫，本來就還沒到 recall 時機）。

```bash
NOW=$(date +%s)
while read -r f; do
  mtime=$(stat -f %m "$MEMORY_DIR/$f" 2>/dev/null)
  [ -z "$mtime" ] && continue
  age_d=$(( (NOW - mtime) / 86400 ))
  if [ $age_d -gt 180 ]; then tier="化石"
  elif [ $age_d -gt 60 ]; then tier="冷死"
  elif [ $age_d -gt 30 ]; then tier="可疑"
  else continue
  fi
  printf "%s\t%d天\t%s\n" "$tier" "$age_d" "$f"
done < /tmp/memory-cold.txt | sort
```

**Step 3 — 命名 pattern 自動標 review 候選**（縮窄人工 triage 範圍）：

標題含下列 pattern 直接歸「真該整理」分類、不論 mtime：
- `deprecated` / `retired` / `removed` / `obsolete`
- `pivot` / `pending` / `in_progress`
- `_incident_` / 過去日期 stamp（`YYYY_MM_DD` 兩個月以上）

```bash
grep -iE '(deprecated|retired|removed|obsolete|pivot|pending|in_progress|_incident_)' /tmp/memory-cold.txt
```

**結合 cluster 對位（避免重複建議）**：標出來的候選若同時是 D 維度「unregistered orphan」→ 走 D 流程；若是 F 維度「mature wiki-promotable」→ 走 promote 流程；只有單純「冷死+無對應流程」才在 J 區列為 demote 候選。

判定（**報告門檻，2026-07-17 使用者拍板**）：僅當「**化石層 ≥1 條**」或「**命名 pattern 命中且非結案敘事**」（結案敘事 = 標題／內文自述事件已結束——trial 收案、否決結論、已移除紀錄——冷是正確狀態）才列 ⚠️ suggestion 附候選清單；兩者皆無 → 只輸出一行資訊統計「冷 X/Y（Z%）、化石 0、pattern 命中 N 條皆結案敘事」，不列 triage 建議、不進推薦 actions。為什麼：冷率約三成是 reference 庫常態（~78% 情境式低觸發、「否決結論也要留檔」是既定紀律），逐日把常態當 finding 報 = nag 淹沒真訊號（07-15～07-17 連三日實證後拍板）；且 2026-07-10 擴分域後分母已變、與 root-only baseline 8.5% 不可比。掃描與三層分類照跑（統計要持續累積），變的只是報告門檻。

J 完成後接 K 維度（K 有自己的週二 gate，非週二直接跳過）。

### K. 易腐宣稱驗證（perishable-claim weekly sweep，2026-07-05 加入）

I 維度只驗「最近被讀」的條目、驗不到外部狀態；J 只看冷熱。K 補的是第三類：**現在式陳述外部狀態的宣稱**（訂閱 / 排程 / trial / PR 狀態 / 限額數字），寫入當下為真、現實變了不自知——MiMo 退訂事故（2026-07-05）的病理。write-time 對偶是 `~/.claude/hooks/memory-ripple.sh`（狀態反轉寫入提醒）；K 兼任它的漏網偵測器（K 抓到的 stale 反查 `~/.claude/logs/memory-ripple-audit.jsonl` 當初寫入時 hook 有沒有 fire = miss 計數）。

**Step 0 — 週二 gate**：`[ "$(date +%u)" = "2" ]` 不成立 → 報告寫一行「K: skipped（非週二）」直接接 L 維度（2026-07-10 前是跳到第 3 點；L 加入後改）。使用者手動點名跑 K → 忽略 gate。

**Step 1 — 確定性 shortlist**（零 LLM）：

```bash
cd "$MEMORY_DIR"
grep -rln -iE "訂閱|退訂|付費|包月|flat-rate|free tier|quota|額度|限額|trial|試用|觀察期|OPEN|未 ship|未 merge|pending|每月|monthly|已 deploy|已裝|launchd|排程|還在|仍在" \
  *.md general/*.md work/**/*.md projects/**/*.md 2>/dev/null | grep -vE '(^|/)(_index_|_INDEX)'
```

**Step 2 — 兩段挑選，每輪最多驗 5 條**（bound 成本，比照 I 維度；2026-09-25 改為兩段）：

1. **資格**：shortlist 內、ledger 從未驗過或最新 `verified_at` > 30 天；最新一筆 `verdict` 是 `skip` 的排除，條件與 I 維度完全相同（`verified_at` ≥ 2026-09-25 且檔案 mtime 不晚於它）。
2. **排序只看 frontmatter 的 `description` 與檔名，不開內文**（`grep -m1 "^description:"`；真實 shortlist 2026-09-25 有 712 檔、30 天內未驗 619 檔，逐檔讀內文排序本身就沒有成本上限）：對每個候選從 description 抽它最主要的一句現在式宣稱，問「這句如果相反，會不會改變某個操作」——會的叫**操作型**（例：「刪檔要過某閘門」「某 hook 會擋 X」「要先跑 Y 才能 Z」「排程還在跑」），不會的叫**描述型**（例：「某 repo 幾顆星」「某版本號」「某工具是 Rust 寫的」）。操作型排前、描述型排後；同型內再以 MEMORY.md／`_index_*.md` 有 pointer（高消費）優先。只驗排序後的前 5 條，其餘下輪輪到。
3. 為什麼排序：shortlist 712 檔、每輪 5 條，不排序時一條會改變操作的舊宣稱最久要等約 142 輪；排序把最傷的先驗。

**Step 3 — 驗證階梯**（由便宜到貴，能驗就驗、驗到哪層記到哪層）：
1. 路徑 / script 存在：`test -e`
2. CLI / plugin 安裝：`command -v`、`ls ~/.claude/plugins/cache/`
3. 排程宣稱：`launchctl list | grep -i`
4. 設定宣稱：grep `~/.claude/settings.json` / 對應 config
5. trial 狀態：先 grep `~/Desktop/projects/.claude/trials/active.md` 的 H2；完整新格式再讀 `started`／`status`／`detail` 索引並按需檢查 `trials/active/` detail 長段及前兩行 `detail-key`／`detail-title`，沒有索引欄位的 legacy H2 直接讀原段；索引不完整、detail 指針無檔或身分不符要列 `detail-missing`／`detail-mismatch`，最後對 `archived.md`
6. work repo ship 狀態：先 `git -C <repo> fetch origin`（remote = ground truth）再 `git log origin/<default> | grep`
7. 以上都搆不到（外部訂閱 / 遠端服務 / 他人決策）→ 不猜，擬一句給使用者的問題

**Step 4 — append `.verification-ledger.jsonl`**（每條驗過的都記、全 ok 也記，schema 同 I 維度；漏記 = 下輪重驗同條目）。驗到一半發現該條是有日期的歷史快照或規範類 → 記 `skip` 附原因，之後不再抽到。

**Step 5 — 輸出**：stale 條目附矛盾證據進 ⚠️ 區、**不自動改 memory**；「需問使用者」的收斂成一張問題表（條目 / 宣稱 / 擬問句）放進報告，跑在 local-analysis memory channel 裡時這張表要進 channel summary 讓 digest 帶出來。另固定報一行**排序指標**：`K 操作型比例：<操作型條數>/<本輪實驗條數>，其中 contradicted <n>`——這是 2026-09-25 改兩段挑選後首月重估用的數字，量的是排序有沒有把會改變操作的宣稱推到前面，不是命中率。

判定：⚠️ suggestion。**Baseline（2026-07-05 首輪全庫掃）**：root+general shortlist 303 檔、實讀高訊號 23 檔、判 stale 11（已修）+ 需問使用者 6 → yield ~3.5%；週驗 5 條的節奏對齊 MiMo-class 事件頻率（約每月 1-2 次），加大無益。

### L. 分域 `_INDEX` 對帳（2026-07-10 加入，對齊分域架構）

C / D / E 的 cluster 語意綁 root，分域子目錄（general/ + work/<proj>/ + projects/<proj>/）的結構健康由本維度覆蓋：

1. 每個分域 leaf 目錄的 `_INDEX.md` 存在
2. `_INDEX` 列出的 entry 與該目錄實際檔案雙向對帳（列了但檔不存在 / 檔存在但沒列）
3. 頂層 router（`work/_INDEX.md`、`projects/_INDEX.md`）與子目錄對帳（子目錄沒被 router 列 / router link 指向不存在的 `_INDEX`）

```bash
L_CHECK="$HOME/.claude/scripts/memory-index-audit.sh"
[ -x "$L_CHECK" ] || { echo "L EXECUTION FAILED: missing $L_CHECK"; exit 1; }
"$L_CHECK" "$MEMORY_DIR"
```

L 維度只接受這支 deterministic helper 的 stdout。不得改寫成 Python、另組 regex，或把 `[[slug]]` 正規化成同目錄 `<slug>.md` 後做存在性檢查；這會違反本檔第 31–45 行的四路解析規則，把 wiki entity／frontmatter route 誤報為 local missing。helper 缺失或執行失敗時，標記 L 維度執行失敗，不得輸出人工修檔建議。完成判準：stdout 中的 `LISTED-BUT-MISSING` 只可能來自同目錄相對 Markdown target；跨目錄 target 與 `[[...]]` 均不進這個集合。

判定：❌ `MISSING _INDEX` / `UNLISTED`（分域版 unregistered orphan，分域無 `_orphan_registry` 機制、一律 must-fix）/ `LISTED-BUT-MISSING` / `ROUTER MISSING` / `ROUTER DEAD LINK` 任一有輸出 → 修對應 `_INDEX` 或檔案；✅ 全部無輸出。

### M. 隔日 triage 候選（ripple audit log ＋ settings hooks 段 diff，2026-09-25 加入）

前 12 個維度都是「從記憶這邊往外驗」。M 反過來吃兩個「世界那邊剛變了」的訊號，把該回頭看的記憶檔列成候選；**只列候選與建議修法，不改任何檔**。動機：memory-ripple hook 原本命中就叫寫入的 session 當場 triage 幾十到上百個同主題檔，工作 session 被拖去修記憶；2026-09-25 起 hook 只記 log，triage 歸這裡。

**狀態檔（兩個，都在 gitignored 的 `~/.claude/logs/`，只在本輪報告成功寫出後才更新，用 Write 工具；內容都是小清單，不抄整段 hooks JSON）**：

- `~/.claude/logs/memory-channel-state.json`：`{"last_ripple_ts": "<本輪處理到的最後一個 ripple 事件 ts>"}`
- `~/.claude/logs/memory-channel-settings-hooks.json`：`{"identifiers": [<排序後的識別字清單，由下方同一段抽取產生>]}`

兩檔任一不存在 = 首輪：不當錯誤，照下面規則跑完後建立。**首輪的 ripple 起點固定是 `2026-09-25T00:00:00+0800`**（hook 停止當場注入的上線日）；之前的事件當時都已在寫入 session 被舊版 hook 提示過，不重讀。

**M-1 ripple log 候選**（來源 `~/.claude/logs/memory-ripple-audit.jsonl`；每筆有 `ts`／`file`（只有檔名）／`siblings`（只有計數）／`fired`）：

```bash
STATE="$HOME/.claude/logs/memory-channel-state.json"
LOG="$HOME/.claude/logs/memory-ripple-audit.jsonl"
SINCE=$(jq -r '.last_ripple_ts // "2026-09-25T00:00:00+0800"' "$STATE" 2>/dev/null); SINCE=${SINCE:-2026-09-25T00:00:00+0800}
PENDING=$(mktemp -t ripple-pending)
jq -cR --arg since "$SINCE" 'fromjson? | select(.fired == true and (.ts // "") > $since) | [.ts, .file] | @tsv' -r "$LOG" 2>/dev/null | sort > "$PENDING"; echo "M-1 待處理清單: $PENDING"
```

- `$PENDING`（路徑會印出）是**待處理清單**（依 ts 排序）。報告固定先列三個數字：待處理事件數、待處理不同檔數、最舊待處理 ts；**最舊待處理超過 7 天就列 ⚠️ 積壓**，讓使用者看得到消化不完。
- `fromjson?` 讓壞行被跳過而不是讓整條 pipe 中斷。log 不存在或清單為空 → 一行「M-1：無新 ripple 事件」，不當錯誤。
- **每輪處理上限 10 個不同檔**：由舊到新掃清單、同一檔只算最新一筆，湊滿 10 個檔後，**把最後那個 ts 相同的事件全部一起納入**（ts 只到秒，不把同秒事件切開）；`last_ripple_ts` = 本輪納入的最後一個事件的 ts。沒納入的下輪接著來，不能跳到「現在」。
- 每個事件的兄弟檔清單不在 log 裡，用 hook 自己的規則取回（同一份程式，不另寫 grep）：

```bash
F=$(find "$MEMORY_DIR" -name "<file 欄的檔名>" -not -path '*/archive/*' | head -1)
bash "$HOME/.claude/hooks/memory-ripple.sh" --siblings "$F"
```

- 對每個事件：讀 `F` 找那次寫入反轉了什麼前提；兄弟檔先看葉檔、再看索引，**每個事件最多讀 8 檔**（比照 hook 原本 6＋2 的顯示配額），逐檔判「仍把舊前提當現行」→ 列 ⚠️ 候選（條目／矛盾證據／建議修法，修法照修復紀律）；「歷史敘述」不列、也不寫 ledger。

**M-2 settings hooks 段 diff**（識別字 = command 字串裡出現的每個腳本檔名；包裝型 hook 如 `fable-gate.sh X.sh` 會抽出兩個；直接呼叫二進位檔的 hook 不在偵測範圍）：

```bash
SNAP="$HOME/.claude/logs/memory-channel-settings-hooks.json"
NOW=$(mktemp -t hooks-now); PREV=$(mktemp -t hooks-prev)
ids() {  # $1 = settings 檔；JSON 壞掉就回非零，呼叫端要標「本輪未查」。只認腳本檔名：inline shell 型 hook 抽不出穩定識別字（2026-09-25 實測 fallback 只抽到 `if`）
  jq -e . "$1" > /dev/null 2>&1 || return 1
  jq -r '[.hooks // {} | .. | .command? // empty | strings] | .[]' "$1" \
    | grep -oE '[A-Za-z0-9._-]+\.(sh|py|mjs|js)([^A-Za-z0-9._-]|$)' | sed -E 's/[^A-Za-z0-9._-]$//' | sort -u
}
{ ids "$HOME/.claude/settings.json" || echo "M-2 UNAVAILABLE settings.json"; [ -f "$HOME/.claude/settings.local.json" ] && { ids "$HOME/.claude/settings.local.json" || echo "M-2 UNAVAILABLE settings.local.json"; }; } | sort -u > "$NOW"
if grep -q '^M-2 UNAVAILABLE' "$NOW"; then echo "M-2：本輪未查（settings 讀取失敗）"
elif [ -f "$SNAP" ]; then
  jq -r '.identifiers[]' "$SNAP" | sort -u > "$PREV"
  comm -23 "$PREV" "$NOW"   # 上次有、這次沒有 = 被拆線的識別字
else
  echo "M-2: 首輪，建立快照、無 diff"
fi
```

- settings 讀取失敗（JSON 壞掉、寫到一半）→ 這一段固定寫「本輪未查」，**不得**把識別字全數當拆線；快照也不更新。
- 被拆線的每個識別字用**兩個字串**各 grep 一次：完整檔名，以及去副檔名、再去 `-wrapper`／`-gate`／`-nudge`／`-judge`／`-hook` 尾綴後的主幹（`dcg-wrapper.sh` → `dcg`；記憶通常寫工具名不寫 wrapper 檔名，2026-09-25 重放實測：完整檔名只命中 1 檔、主幹命中 20 檔）。**主幹短於 3 個字元只用完整檔名**（`dcg` 剛好 3 字要進；`if` 這類 2 字主幹會命中幾百檔）。`command grep -rl -F --include='*.md' "<字串>" "$MEMORY_DIR" | grep -v '/archive/'`；**命中超過 30 檔只報計數**、不逐檔判。命中的逐檔判「當現行機制」才列 ⚠️ 候選、「已寫明退役」不列；只有識別字消失但沒有記憶檔提到 → 報告一行計數即可。
- 快照只存識別字清單（由上面同一個 `ids` 產生），不抄 hooks JSON；settings 沒有 `hooks` 段、或 `settings.local.json` 不存在 → 該側視為空集合，不當錯誤。
- **不自動改寫任何記憶檔**；不擴到 hooks 目錄、launchd、commit 觸發（第二版候選，回歸條件在 openspec change `memory-rot-daily-repair` 的 proposal）。

判定：⚠️ suggestion（候選＋建議修法）；兩路都無候選 → ✅ 一行帶過。**dcg 重放驗收**：在 dcg wrapper 從 settings 拆線後的狀態下跑，H-2 或 M-2 至少一路要列出提到 dcg 的記憶檔；兩路都抓不到 = 本維度失效，報告要明寫。

## 3. Output 格式

固定結構，分 ✅ / ⚠️ / ❌ 三層：

```
=== Memory Audit Report ===
Memory dir: <MEMORY_DIR>
Audit time: <UTC timestamp>

✅ Healthy
  - Size: X.X KB / N lines (X% of limit)
  - Cluster integrity: N/N OK
  - Unregistered orphan: 0 / Double-ref: 0
  - Cluster pointer alignment: N/N OK
  - 分域 _INDEX 對帳 (L): general + work/N + projects/N 全對齊

⚠️ Suggestions
  - Intentional orphans (registry hit, N 條): <列出 filename + reason 摘要>
  - Cluster `<name>`: mature（≥7 天 stable, N entries）→ consider `/wiki-promote`
  - Standalone reference 主題分布: keyword `<x>` 累積 N → consider new cluster
  - 死路徑引用 (H, N 條): <DEAD path ← memory file>；人工 triage（活工具搬家→修 / 歷史快照·示意路徑→留）；已 triage 結案的（ledger cross-check 命中）不列條目、只記一行 suppress 計數
  - 接線檢查 (H-2): UNWIRED 原始 N / ledger suppress N / 歷史 skip N / 新候選 N；候選列 <UNWIRED ref ← file:line + 建議修法>；helper 不可用時這行固定寫「本輪未查（helper 不可用）」、不得寫 0
  - 被讀取記憶驗證 (I): 驗 N 條（24h 被讀 M 條中 ledger 過期者）；stale: <file + 矛盾證據>；全 ok 就一行帶過。**報告前必先 append `.verification-ledger.jsonl`（每條驗過的都記，全 ok 也要記）——漏記 = 下週重驗同條目**
  - Cold entry (J, N 條): 30 天 hit=0；分層摘要「可疑 X / 冷死 Y / 化石 Z」+ 命名 pattern 自動標 review 候選列出；化石 + 命名 pattern hit 同時的條目強訊號（demote/砍）；其餘人工 triage。**雜訊提醒**：~78% 冷條目是合理低觸發（情境式 reference）、不要全砍
  - 易腐宣稱驗證 (K, 週二限定): 驗 N 條；stale: <file + 矛盾證據>；需問使用者的以問題表列出（條目 / 宣稱 / 擬問句）；非週二一行「skipped」；固定附「K 操作型比例：n/5，其中 contradicted m」。**報告前必先 append ledger（同 I）**
  - 隔日 triage 候選 (M): M-1 ripple 事件處理 N（候選 N 檔）、M-2 settings 拆線識別字 N（候選 N 檔）；每條 <file + 矛盾證據 + 建議修法>；首輪寫「建立狀態檔／快照」；無候選一行帶過
  - ...
  (若無 suggestion 就 list "(none)")

❌ Must fix
  - Unregistered orphan (N) → 加進 cluster / MEMORY.md / 刪檔 / 確定故意 prune → append 到 `_orphan_registry.md`
  - 分域 _INDEX 對帳 (L, N 條): MISSING _INDEX / UNLISTED / LISTED-BUT-MISSING / ROUTER 缺列·死 link → 修對應 `_INDEX` 或檔案
  - ...
  (若無 must-fix 就完全跳過 ❌ 段，不要列 "(none)")
```

## 4. 不要做的事

- **不動任何 file** — read-only diagnostic（唯一例外：I / K 維度 append `.verification-ledger.jsonl`，只 append 不改舊行、不動任何 `.md`；M 維度在報告成功寫出後更新 `~/.claude/logs/` 下的兩個狀態檔）
- **不改記憶檔、不替使用者拍板** — 所有 stale／UNWIRED／M 候選都只列「條目＋證據＋建議修法」；使用者在 digest 拍板後由 main session 修並記 ledger
- **不 ls scan 把 cluster file 當「孤兒」索引進 MEMORY.md** — `_index_*` 開頭永遠排除
- **不依賴 CC inject 的 MEMORY.md snapshot** — 用 Bash / Read tool 拿當下狀態
- **不釘死 cluster 數量 / 名單** — 每次跑 `ls _index_*.md` 動態抓

## 5. 完成後

簡短 summary：`✅ N / ⚠️ N / ❌ N`。

如果有 ❌：提示「手動修對應 file」。
如果只有 ⚠️：使用者自行決定要不要動。
全 ✅：簡短報「memory 健康」即可。

## 6. Implementation hint

A–G／I–K 可用 Python 整合 unicode 與 frontmatter parsing；H 必須逐字跑其固定 `/bin/bash` pipeline，H-2 必須呼叫 `memory-wired-audit.sh`，L 必須呼叫 `memory-index-audit.sh`，M 的兩段 bash 逐字跑。不得用 monolithic script 重寫 H／H-2／L／M 的判定口徑。

## 7. 設計 cross-reference

- `feedback_memory_cluster_maintenance.md` — cluster 維護規則 + E pass / intentional orphan 規則（audit 是它的 health check 配套）
- `_orphan_registry.md` — intentional orphan 白名單（E pass prune 後仍留檔的 entry）；audit 對照本檔 demote intentional orphan 為 Suggestions 不是 Must-fix
- `feedback_prompt_principle_over_hardcoded_list.md` — 動態 ls 不釘死 cluster list 原則
- `reference_cc_auto_memory_limits.md` — 25 KB / 200 行 limit 來源
- `/wiki-promote` — promotion candidate 細節 audit + drafting（本 command 只 hint，不 draft）
- `feedback_local_analysis_audit_cross_check.md` — 2026-05-13 跨 channel cross-check 教訓（F pass wiki cross-check 升級的觸發 source；避免重複列已 wiki 化的 cluster 為 promote 候選）
- `feedback_memory_cluster_maintenance.md` §引用自有 code/config 路徑規範 — H 維度的前向配套（寫精確路徑讓 H 能精準 flag）
- `reference_awesome_harness_engineering_eval_2026_05_30.md` — H 維度（verify-on-schedule）+ citation-as-truth 理論來源（GitHub Copilot agentic memory）；wikilink 形式 `[[awesome-harness-engineering-eval-2026-05-30]]` 走四路解析的路徑 2（frontmatter name），是有效引用
- `Kausha3/agent-memory-bench` (github, 2026-06-27 v0.1) — J 維度設計借鑑來源；四 failure mode (retraction / collision / recall / conflict) → cold scan = recall 反向；retraction 由 I 維度 cover；collision + conflict 暫不固化（pilot 2026-06-29 yield 過低）
- `~/.claude/hooks/memory-ripple.sh` + `~/.claude/logs/memory-ripple-audit.jsonl` — K 維度的 write-time 對偶（狀態反轉寫入即時提醒波及面 triage）；兩機制互為驗證面：K 抓 hook 的 miss、hook audit log 供 K review 反查。設計脈絡見 [[feedback_memory_state_change_ripple_convention]]（2026-07-05 MiMo 退訂事故驅動）
