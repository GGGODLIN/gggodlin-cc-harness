# Fact-check 紀律

觸發面：涉及具體 repo / 套件 / library / SDK / API / 版本 / 政策 / 公司 / 市場 / 人物動態時，先跑 `/research-before-answer` skill 再回答（詳細案例與正反例見 [[fact-check-protocol]] wiki）。

1. **研究衍生產物不可當第一手事實** — NotebookLM baseline / earlier session 結論 / subagent intermediate output 都是 secondhand；具體 framework / API / feature 名要進第一手 source（官方 doc / source code / 直接執行）。「上次確認過」「我記得」不是有效 fallback。
2. **每個事實點都要查，不能 partial fact-check** — 單位是**單一事實點**、不是論點。thesis 查過不代表 throwaway 句就對（例：「Warp 是 Electron」在講 terminal 比較的段落也要 verify — 實際是 Rust + WarpUI）。
3. **CC feature 存在性不能只 grep binary** — `strings /path/to/claude` 只證明 identifier 存在、不證行為存在；行為證據 = jsonl 實測 log / 官方 changelog / release note，不然標「未實測」。
4. **WebSearch ranking 對「找官方 doc」不可信** — Google/Bing 對「找官方文件」的 ranking 常把 SEO 洗過的第三方 blog 排前面；找官方 doc 用 `site:<domain>` 或直接 LCU 的 Google SERP。
5. **WebSearch 必配 browser SERP — ticket model** — 兩軌都跑（WebSearch API + LCU 的 Google SERP），同 query 先實際讀回搜尋頁，再 call WebSearch；ticket 只用於這輪配對，不因換 browser 入口取消查證。
6. **不要把退役工具當 future-proof example** — 舉例前檢查工具是否還在維護（gh releases / 官網存在 / community 活躍）；退役工具當「以後可以用」等於 hallucinate 選項。
7. **SaaS 政策必須實測官方 UI、不只信第三方文章** — SaaS 政策文件 lag、部落格更 lag；引用政策前先進官方 dashboard 實測 or 讀官方 blog 最新一篇。
8. **讀內容不靠 WebFetch；4xx 必升 browser** — X 單篇（`/status/`、`/article/`、`/thread/`）先跑 X／Twitter 抓取退路（見 WIRING.md「非官方內容抓取」）存檔 Read（附圖下原圖 Read）；探索 X 熱點／關鍵字／帳號先跑 `x-search.sh "<query>"`，引用數字或原話須對該 URL 補跑 X／Twitter 抓取退路（見 WIRING.md「非官方內容抓取」）核對。Discord 頻道／訊息連結（`discord.com/channels/...`）先跑 `bash ~/.claude/scripts/discord-fetch.sh "<url>" -o <out.md>` Read（走本機 DCE＋Keychain `DISCORD_TOKEN`），不要先開桌面版。公開 HTML 研究頁先跑 `python3 ~/.claude/scripts/context-dev-scrape.py <url> <out.md>` Read，核對 url、正文、程式碼、表格與連結；非 0 或缺內容接網址抓取退路（見 WIRING.md「非官方內容抓取」）。需登入／視覺／互動直接用正式 LCU；Reddit 走既有專用路徑，原生 Markdown 直讀。Context.dev／Firecrawl 只送公開 URL（不傳 cookies／私人檔／憑證），新增權限／付費確認照既有邊界。WebFetch 只做導航（它回小模型改寫）。其他頁面與日報／workflow 批次走網址抓取退路（見 WIRING.md「非官方內容抓取」）存檔 Read。上述腳本 exit 75/1 或缺關鍵內容才升正式 LCU；LCU 不可用就回報缺口，不宣告不存在。
9. **Session topic shift → 重新 fact-check** — 對話中途換 topic（從 X repo 轉到 Y 版本、從 A 政策轉到 B），舊 topic 的 fact 不代表新 topic 也對；換 topic = 重新查。
10. **個人歷史 query 並行查 wiki + memory** — 如果要回顧使用者的歷史、既有決策或經驗，就同時查 `~/.claude/wiki/` + `~/.claude/memory/`；如果問本人目前能否使用新功能，就查目前帳號、設定或即時資格回應，不因「我的」啟動歷史檢索。
11. **乾淨自動路徑卡住 → 換來源類型、不宣告「不可得」** — 抓取腳本／WebFetch 掛 → 正式 LCU；LCU 不可用時不換其他 browser，改走非瀏覽器官方管道（`gh CLI` → 直接讀 repo local clone）。用完所有「來源類型」再宣告不可得。不要用「查不到」把工作 offload 給使用者。
12. **Repo-scoped API probe 先綁 repo 版本** — 對具體 repo 呼叫第三方 API 前，先讀 repo 的 version constant、設定檔或 lock；有釘版本就以它做所有 probe。官方文件的預設版本只在 repo 未釘版本時使用；版本不一致造成的失敗不得拿來宣稱 spec 前提、master code 或 API 互相矛盾。
13. **研究中間盤點主動標 claim 狀態 ✓/?/✗** — 多線索研究 / audit 的中間盤點與階段小結，主動（不等使用者要求）給每條 claim 標狀態：`✓` 已驗證＋附驗證依據、`?` 已主張未檢查（不得作下游前提）、`✗` 已證偽＋附證據、`??` 承重未知；未標記預設為 `?`。結案宣稱仍走 CLAUDE.md「宣稱與證據層級對位」規則，本條管推理過程的可讀性。
14. 判定目前環境時，查 remote、設定或安裝狀態；同時期的多份記憶不算獨立佐證。
15. 解讀規格片語時先讀完整對比句與派工來源；只有片語、沒有來源說明，不宣稱規格與實作衝突。
16. 公開文件的數字要標適用範圍與日期；舊數字缺原始材料、無法重現時明示撤回，不當成行為保證。
17. **最新外部題直接查外部來源** — 如果查最新外部事實或探索外部資訊，就用網路搜尋、第一手來源或已配置的外部查詢工具；本機 memory、wiki、session、報告與歷史收錄不作探索入口，也不作搜尋失敗的替代。混合題只對歷史回顧部分查本機紀錄，外部現況另行查證。
