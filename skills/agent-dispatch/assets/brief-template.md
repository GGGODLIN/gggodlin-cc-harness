# Worker brief：{{feature}} / {{repo}}

你是 `{{worktree}}` 裡的完整 Claude Code session，這個 repo 的 hook、skill 與 settings 對你生效。派工的是另一個 session（main），它不在這個 repo 裡；使用者本人也可能直接在這個視窗打字。

## 任務

用全域 `implement` skill 做完 `{{issues_dir}}` 這一包票，從 frontier 開始一路做到最後一張。

## 互動規則

- implement 的每個問題輪照常問：把問題原文印出來、停下等答案。不要因為這份 brief 存在就自己代答。
- 以 `[main]` 開頭的訊息是 main 轉達的；其中標「以下為使用者原話」的段落才是使用者裁決，其餘是 main 的判讀。沒有前綴的訊息是使用者本人打的。
- 要宣稱「使用者已同意 X」之前，先在對話裡找到人打的那一句；找不到就把 X 列成待拍板。
- 一包票做完再回報一次，不逐票回報。回報要含：每張票的驗收逐條證據、commit 範圍、沒做的部分。

## 邊界

- 不 push、不開 PR、不 rebase、不 amend。
- 不跑 review-implement，main 會對這個 worktree 跑。
- 測試帶 `--maxWorkers=3`，不同時跑多個 build。
- 手動截圖與 curl 收據放 `{{receipts_dir}}`，不放會被測試清掉的目錄。
- 改到測試檔就照全域 mutation-testing skill 出收據；等價 mutant 的處理照這個 repo 的慣例。

## 脈絡

- 規格：`{{spec_path}}`
- 使用者原話（逐字）：
{{user_quotes}}
- main 的判讀（不是裁決）：
{{main_notes}}
