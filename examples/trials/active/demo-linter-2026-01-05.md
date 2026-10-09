detail-key: active/demo-linter-2026-01-05.md
detail-title: demo-linter 試用

> mock 範例：trial 詳細檔的格式照真實的寫，工具與數字都是虛構的。

## 為什麼試
想知道 demo-linter（虛構工具）能不能取代手動檢查 Markdown 連結。

## 判準
- KEEP：一週內至少抓到 2 個真的斷掉的連結，誤報不超過 1 個。
- KILL：一週內 0 個真問題，或誤報多到每次都要手動排除。

## 觀察紀錄
- 2026-01-07：抓到 1 個斷連結（真的）。
- 2026-01-09：1 個誤報（把錨點連結當成檔案）。

## 回退方式
移除 `~/.claude/settings.json` 裡對應的 hook 註冊，刪除 demo-linter 的安裝目錄。
