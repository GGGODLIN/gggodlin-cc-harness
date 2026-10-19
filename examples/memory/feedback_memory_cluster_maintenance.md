---
name: MEMORY.md 兩層 index 結構維護規則
description: 把 reference / project 重組成 cluster + 2nd-level index (_index_*.md)，搭配分域路由（work/ projects/ general/ vs root），避免頂層 MEMORY.md 超過 25 KB / 200 行上限。
type: feedback
modified: 2026-05-07T09:00:00.000Z
---
> mock 範例：格式照真實的兩層記憶維護規範寫，供 `hooks/memory_reminder_common.py`（由 `auto-memory-jev.py` 與 `checkpoint-judge.sh` 呼叫）動態抽取下方 Tier 1 到 Tier 3 之間的段落注入。實際使用時請複製到 `~/.claude/memory/feedback_memory_cluster_maintenance.md`。

**Rule**: 新增或更新記憶時，**必須先分域路由判 scope、root 域再做 cluster check**。`MEMORY.md` 不平鋪所有條目，只放「cluster 指針 + 少數尚未成群的 standalone」。

**Why**: Claude Code 官方對頂層 `MEMORY.md` 設有 25 KB / 200 行上限。若每次直接往 `MEMORY.md` 尾端塞新條目，幾週就會撞上上限並截斷後續內容；改用兩層索引（`MEMORY.md` → `_index_*.md` → 葉節點 `.md`）才能無上限擴充記憶庫。

## Tier 1: 寫前必看（hook 動態 inject）

下列段落是寫入或更新記憶當下必看的步驟，由 `memory_reminder_common.py` 動態注入提醒訊息。

**模型欄**：`feedback` 類條目內文可附「模型: <resolved id>」＋「CC 版本: <x.y.z>」兩行，記錄規則誕生時的環境背景。

## 分域路由（scope check）

`~/.claude/memory/` 是集中管理的大腦目錄，按範圍分域：

- **root** = 通用研究與跨專案大腦本體（`MEMORY.md` + `_index_*.md` cluster + 通用 `reference` / `feedback` / `user` 檔）
- **`general/`** = 一般開發環境・基礎設施・工作習慣，`general/_INDEX.md`
- **`work/<repo>/`** = 各工作專案各自累積的記憶，各自 `work/<repo>/_INDEX.md`
- **`projects/<proj>/`** = 各個人專案各自累積的工作記憶，各自 `projects/<proj>/_INDEX.md`
- 只有頂層 `MEMORY.md` 會自動載入；各域 `_INDEX.md` 與所有 `_index_*.md` 皆按需讀取（on-demand Read）

**寫入規則**：寫條目前先判 scope，屬於特定專案或一般環境的直接放進對應子目錄並更新該目錄的 `_INDEX.md`（若該子目錄是第一次建立，先在頂層 `MEMORY.md` 的「分域路由」段補一行指向該 `_INDEX.md` 的入口，之後新增條目就不再動頂層 `MEMORY.md`）；只有跨領域通用條目才放 root 並走下方決策樹。

## How to apply（決策樹）

（僅 root 域條目；先過上方「分域路由」判 scope）

```
新 reference / project 條目寫好檔案 →
   ├─ 屬於現有 cluster 之一？（以 `ls ~/.claude/memory/_index_*.md` 當下清單為準）
   │   ├─ YES → 更新對應的 _index_<topic>.md 加一行（插在 ## Maintenance 之前），並將 frontmatter 的 entries 計數 +1；MEMORY.md 不動
   │   └─ NO  → ↓
   ├─ 同主題 standalone 已 ≥3 條？
   │   ├─ YES → 建新 cluster _index_<新 topic>.md + 把舊 standalone 條目遷入該 cluster 並從 MEMORY.md standalone 區移除 + 在 MEMORY.md 加一行 cluster 指針
   │   └─ NO  → ↓
   └─ 加進 MEMORY.md standalone 區（最後手段）
```

## 跨 cluster cross-link 規範

走完 cluster check 後，花 30 秒掃描其他 `_index_*.md`（`command grep -l "<關鍵詞>" ~/.claude/memory/_index_*.md`）：

- 若同一工具或事件的不同面相散在別的 cluster，兩邊條目互相加上 `[[檔名]]` 雙向連結。
- 若主題重疊到應該合併，直接更新既有檔案、不另建新檔。

## Index 行長度紀律

`MEMORY.md` 與 `_index_*.md` 的索引行只負責回答「什麼時候該點進來讀這篇」，**不搬運檔案內文**；單行控制在 40–80 tokens 以內，細節留在葉節點檔案裡。

## 當場修邊界與修復紀律

工作中發現既有記憶過期或被使用者指正時：

- **只修撞到的那一段**：就地更新或撤下過期敘述，緊接著加一行固定格式更正行：
  `> 更正行 YYYY-MM-DD：<撤下或改寫了哪句>；現況來源：<可重驗的路徑、指令或 commit>`
- 有日期的歷史實測快照保留當時日期與數據，把「當時測得」與「目前現況」分開寫。

## Tier 3: 細節參考（LLM 視需要 Read）

- 更新 `_index_<topic>.md` 時，新條目必須插在 `## Entries` 段尾（`## Maintenance` 標題之前），避免落入維護說明區。
- 對 `MEMORY.md` 做局部 `Edit` 時，前後各帶一行既有內容定位，避免把相鄰兩行黏成同一行。
