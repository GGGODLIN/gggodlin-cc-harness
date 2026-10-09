---
description: 把成熟 memory 結論 promote 成 publishable wiki entity（user trigger，不是 auto）
---

# Wiki Promote

把 session memory 內成熟 + 公開友好的結論 promote 成 `~/.claude/wiki/` entity。**永遠 user-triggered**——auto trigger 會把 wiki 拉回 memory 角色（散亂、半熟、含敏感 context）。

## 1. 讀規範 + 動態 audit 當下狀態

```bash
# Wiki 寫作規範
cat ~/.claude/wiki/_schema.md

# 現有 entity（避免重複 promote）
ls ~/.claude/wiki/

# Memory cluster + standalone audit
# consolidated 大腦優先：autoMemoryDirectory（settings.local.json > settings.json）；否則退回 per-project scope
MEMORY_DIR=$(jq -r '.autoMemoryDirectory // empty' "$HOME/.claude/settings.json" "$HOME/.claude/settings.local.json" 2>/dev/null | grep . | tail -1)
MEMORY_DIR="${MEMORY_DIR/#\~/$HOME}"
if [[ -z "$MEMORY_DIR" ]]; then
  PROJECT_HASH=$(pwd | sed 's|^/|-|; s|/|-|g')
  MEMORY_DIR="$HOME/.claude/projects/$PROJECT_HASH/memory"
fi
ls "$MEMORY_DIR"/_index_*.md   # cluster 列表（動態，不要記固定）
cat "$MEMORY_DIR"/MEMORY.md    # 看 standalone reference / project
```

## 2. 篩選 promotion 候選

對每個 cluster + standalone reference / project entry 評估三條準則：

| 準則 | 通過判定 |
|---|---|
| **成熟度** | cluster 內 ≥3 entry，或 standalone reference 已 stable（最後改動 > 1 週沒大調整） |
| **公開友好** | entity-centric > user-specific（談「工具/概念行為」勝過「使用者 setup / 偏好 / 帳號」） |
| **未重複** | `~/.claude/wiki/` 內沒對應 entity，或現有 entity 嚴重 stale 該 refresh |

**自動跳過**：
- `feedback_*` / `user_*` memory — 本質私人，永不入 wiki
- 含個人帳號 / 內部路徑 / 機器名而**未 sanitize** 的內容
- 含 active project 內部 state 的 `project_*` — 等 project 結案後才考慮
- Stale 內容（已過時 / 自標 superseded）

## 3. 草擬（不要直接寫 wiki/）

對每個通過篩選的候選：

1. 按 `_schema.md` 當下格式寫 frontmatter（具體欄位 read schema 拿——schema 可能演進，不要硬編碼欄位列表）
2. Body 從 cluster file + 對應 topic file 抽精華，寫成 entity-centric narrative（不是時間軸）
3. **Sanitize check**：列出來源 memory 內含個人 context 的部分，**標清楚要 sanitize 的點**：
   - 個人路徑（`~/Desktop/projects/...`）→ 通用化或標 「per-user」
   - 帳號名 / 機器名（owner / alex / M5 Pro 主機名）→ 改通用 reference 或 redact
   - 內部 project 名稱 → 評估是否該公開
   - 對話片段 / 決策軌跡 → 改 entity 觀點敘述
4. `sources` 欄位列出 source memory file（標 「extracted from session memory cluster」即可，不要 leak 個人 session UUID）

## 4. 報告候選清單給 user review

**不要直接 Write 任何 wiki file**。先列：

```
找到 N 個 promotion 候選：

1. [候選 entity 名] from cluster X / standalone Y
   - 成熟度：cluster N entries，最後改動 D 天前
   - Sanitize 點：A / B / C
   - 草擬 frontmatter 預覽：(展示)
   - 草擬 body 摘要（前 3 行）

2. ...

請選要 promote 哪些（編號 / "全部" / "跳過"）+ 個別 sanitize 細節調整。
```

## 5. User confirm 後寫入

- Write `~/.claude/wiki/<entity-slug>.md`（按 schema 格式）
- 更新 `~/.claude/wiki/index.md` append 新 entity 摘要行
- 更新 `~/.claude/wiki/log.md` append promotion 記錄
- **不動 source memory**（保留作為 working notes，wiki 是 sanitize 後的下游 publish）

寫入完成後接 Step 6 簡短報告。

## 6. 完成後簡短報告

寫了 / 改了哪幾個 wiki file、sanitize 了哪些點、index.md 有沒有更新。不重複 entity 內容。

## 設計原則 cross-reference

- **Memory → wiki 是 promotion 不是並行**：cluster 結構吸收高頻結論，wiki 是低頻 publishable curation
- **永遠 user-triggered**：見 `feedback_memory_to_wiki_promotion.md`
- **不釘死 cluster 數量**：see `feedback_prompt_principle_over_hardcoded_list.md`——每次跑時動態 ls cluster 結構，cluster add/split/merge/rename 不影響本 command
