# Terminal backend routing

- 終端機後端只認身分變數，不認「CLI 有裝」。Herdr 身分包含兩種等價形式（六個審查驗收角色的 `open-seat.py` 僅認 `HC_TERMINAL_ID`，見 `pi-subtasks.md`）：
  - 舊版 Herdr TUI：`HERDR_PANE_ID` 與 `HERDR_WORKSPACE_ID` 齊全（只出現其中一個欄位時，當作沒有身分）。
  - 新版 Herdr App / Core：`HC_TERMINAL_ID` 存在（搭配 `herdr-app` 與 `hc` CLI）。
🔌 接線點：終端後端 — 見 WIRING.md
- 如果要第二意見或委派任務，就不照貼顧問給的 headless 指令，不跑 `claude -p`、`codex exec` 或 launcher 加 `-p`，不以 subagent model override 換模型，也不自寫啟動器；只有 `config/second-opinion-seats.json` 明列該用途與原因時才走例外。pi-subtask 照現行規則保留。如果使用者在當輪明確點名要用 `claude -p`、`codex exec` 這類 headless 呼叫，就照做，並在同一則提醒它會繼承本 session 的模型映射、可能沒跑到要的模型；顧問建議、上一輪的指定或「用什麼都行」不算點名。尚未遷移的呼叫端既有路徑照舊（advisor 的原生 Fable Agent 與網頁 GPT Pro），不因本條改判不可用。
- 如果開的是實作 worker，就先取得綁定任務、repo、worker 數的同意；同意實作不等於同意開 worker。如果開的是唯讀單席，就不另問派工同意，但外部額度席仍要使用者明選；選通道不授予選席權。
- 承接 `dispatch-and-verify.md`：workflow agent 亦不得自開 Herdr，僅 workflow 內部席位走席位目錄例外。
- 如果跨模型需求沒有完整 Herdr 身分，或席位目錄沒有該席／尚未啟用，就回報該席目前不可用，不自行退回 headless（使用者當輪點名的照上面那條）或換模型。如果沒有完整身分的一般 shell 任務不需要另一個模型，就直接用 shell，不叫終端機後端 skill；使用者提到 Herdr 不等於授權去連它。
- 任何 skill、rule、script 都不自動拉起 Herdr server。後端沒在跑就回報並停，讓使用者決定；啟動會動到使用者沒看著的畫面與 session。
