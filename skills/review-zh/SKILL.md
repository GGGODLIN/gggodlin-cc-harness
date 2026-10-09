---
name: review-zh
description: Use when writing or editing non-Traditional-Chinese markdown to be shown to the user (skill SKILL.md, CLAUDE.md edits, plan files, README, design docs, RFC drafts). Generates a Traditional Chinese review copy at ~/.claude/review-zh/ for native-language review. Skip when source is already Traditional Chinese, is pure code, or is trivial (commit messages, PR titles, short config comments). Also invokable manually via /review-zh.
---

# 繁中 review 副本

寫 skill 或文件（含 CLAUDE.md 編輯、plan 檔、README 等任何 markdown 內容）時，在 `~/.claude/review-zh/` 產出繁中副本供使用者 review。

## 命名規則（路徑編碼）

用 `__` 取代 `/`：

- `~/.claude/skills/figma-context-budget/SKILL.md` → `~/.claude/review-zh/skills__figma-context-budget__SKILL.md`
- 專案內檔案用 repo 名起頭：`oldco-shop/docs/foo.md` → `oldco-shop__docs__foo.md`

## 刪除時機

- 使用者對原版給出 feedback 或確認 OK 後，**主動詢問**是否刪除繁中副本
- 使用者明確說刪才刪；說保留就留著，不施加引導
- 這是暫存檔，不進 git、不進專案目錄

## 不適用情境（跳過，不產副本）

- 純程式碼修改（.ts / .tsx / .cljs / .py / .go 等）
- 原檔已經是繁體中文（如 `~/.claude/CLAUDE.md` 本身、使用者的 wiki、個人 notes）
- 使用者明確說「這次不用繁中版」
- 極短內容：commit message、PR 標題、一兩行的 config 註解
- 短 PR description / issue body（非長文件，產副本對使用者沒幫助）

## 手動觸發

`/review-zh` 可在對話中呼叫，對指定檔案補產副本。

## 舊副本處理

產出前先看 `~/.claude/review-zh/` 有無同名舊副本，過期就覆蓋；來源檔已改名的孤兒副本順口提醒使用者可刪。
