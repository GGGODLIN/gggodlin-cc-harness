# Terminal backend routing

- 終端機後端只認身分變數，不認「CLI 有裝」。Herdr 身分包含兩種等價形式：
  - 舊版 Herdr TUI：`HERDR_PANE_ID` 與 `HERDR_WORKSPACE_ID` 齊全（只出現其中一個欄位時，當作沒有身分）。
  - 新版 Herdr App / Core：`HC_TERMINAL_ID` 存在（搭配 `herdr-app` 與 `hc` CLI）。
🔌 接線點：終端後端 — 見 WIRING.md
- 沒有完整 Herdr 身分 → 不叫終端機後端 skill，用 shell 直接做；使用者提到 Herdr 不等於授權去連它。
- 任何 skill、rule、script 都不自動拉起 Herdr server。後端沒在跑就回報並停，讓使用者決定；啟動會動到使用者沒看著的畫面與 session。
