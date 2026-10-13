# Fact-check 紀律

17 條 always-on 事實查證紀律。詳細案例與正反例見 [[fact-check-protocol]] wiki；本檔只留可執行的 rule statement。

觸發面：涉及具體 repo / 套件 / library / SDK / API / 版本 / 政策 / 公司 / 市場 / 人物動態時，先跑 `/research-before-answer` skill 再回答。以下 17 條是 protocol 骨幹、拆給 always-on 記憶用。

1. **研究衍生產物不可當第一手事實** — NotebookLM baseline / earlier session 結論 / subagent intermediate output 都是 secondhand；具體 framework / API / feature 名要進第一手 source（官方 doc / source code / 直接執行）。「上次確認過」「我記得」不是有效 fallback。
2. **每個事實點都要查，不能 partial fact-check** — 單位是**單一事實點**、不是論點。thesis 查過不代表 throwaway 句就對（例：「Warp 是 Electron」在講 terminal 比較的段落也要 verify — 實際是 Rust + WarpUI）。
3. **CC feature 存在性不能只 grep binary** — `strings /path/to/claude` 只證明 identifier 存在、不證行為存在；行為證據 = jsonl 實測 log / 官方 changelog / release note，不然標「未實測」。
4. **WebSearch ranking 對「找官方 doc」不可信** — Google/Bing 對「找官方文件」的 ranking 常把 SEO 洗過的第三方 blog 排前面；找官方 doc 用 `site:<domain>` 或直接 chrome SERP。
5. **WebSearch 必配 browser SERP — ticket model** — 兩軌都跑（WebSearch API + LCU 的 Google SERP），同 query 先實際讀回搜尋頁，再 call WebSearch；ticket 只用於這輪配對，不因換 browser 入口取消查證。
6. **不要把退役工具當 future-proof example** — 舉例前檢查工具是否還在維護（gh releases / 官網存在 / community 活躍）；退役工具當「以後可以用」等於 hallucinate 選項。
7. **SaaS 政策必須實測官方 UI、不只信第三方文章** — SaaS 政策文件 lag、部落格更 lag；引用政策前先進官方 dashboard 實測 or 讀官方 blog 最新一篇。
8. **讀內容不靠 WebFetch；WebFetch 4xx → 必觸發 browser 升級** — WebFetch 回的是小模型改寫、不是原文：要讀整篇或引用頁面上的數字／日期／原句，用網址抓取退路（見 WIRING.md「非官方內容抓取」）存檔後 Read（輸出已是正文），WebFetch 只做導航（找連結、確認頁面在、找該讀哪段）。WebFetch 4xx / 封鎖 / 空 body → 網址抓取退路（見 WIRING.md「非官方內容抓取」）→ exit 75/1 升 LCU MCP（`mcp__lcu__js`）；LCU 不可用就停止並回報具體阻塞，不改走 OBU／Agent Chrome，也不就此宣告內容不可得。
9. **Session topic shift → 重新 fact-check** — 對話中途換 topic（從 X repo 轉到 Y 版本、從 A 政策轉到 B），舊 topic 的 fact 不代表新 topic 也對；換 topic = 重新查。
10. **個人歷史 query 並行查 wiki + memory** — 如果要回顧使用者的歷史、既有決策或經驗，就同時查 `~/.claude/wiki/` + `~/.claude/memory/`；如果問本人目前能否使用新功能，就查目前帳號、設定或即時資格回應，不因「我的」啟動歷史檢索。
11. **乾淨自動路徑卡住 → 換來源類型、不宣告「不可得」** — WebFetch 掛 → chrome；chrome 掛 → gh CLI；gh 掛 → 直接讀 repo local clone。用完所有「來源類型」再宣告不可得。不要用「查不到」把工作 offload 給使用者。
12. **Repo-scoped API probe 先綁 repo 版本** — 對具體 repo 呼叫第三方 API 前，先讀 repo 的 version constant、設定檔或 lock；有釘版本就以它做所有 probe。官方文件的預設版本只在 repo 未釘版本時使用；版本不一致造成的失敗不得拿來宣稱 spec 前提、master code 或 API 互相矛盾。
13. **研究中間盤點主動標 claim 狀態 ✓/?/✗** — 多線索研究 / audit 的中間盤點與階段小結，主動（不等使用者要求）給每條 claim 標狀態：`✓` 已驗證＋附驗證依據、`?` 已主張未檢查（不得作下游前提）、`✗` 已證偽＋附證據、`??` 承重未知；未標記預設為 `?`。結案宣稱仍走 CLAUDE.md「宣稱與證據層級對位」規則，本條管推理過程的可讀性。
14. 判定目前環境時，查 remote、設定或安裝狀態；同時期的多份記憶不算獨立佐證。
15. 解讀規格片語時先讀完整對比句與派工來源；只有片語、沒有來源說明，不宣稱規格與實作衝突。
16. 公開文件的數字要標適用範圍與日期；舊數字缺原始材料、無法重現時明示撤回，不當成行為保證。
17. **最新外部題直接查外部來源** — 如果查最新外部事實或探索外部資訊，就用網路搜尋、第一手來源或已配置的外部查詢工具；本機 memory、wiki、session、報告與歷史收錄不作探索入口，也不作搜尋失敗的替代。混合題只對歷史回顧部分查本機紀錄，外部現況另行查證。

**Skill 對應**：[`research-before-answer`](~/.claude/skills/research-before-answer/SKILL.md) 是入口 skill（怎麼觸發）；本檔是「哪些 case 不能放過」的紀律邊界。兩者是 sister rules — skill 管流程、rule 管門檻。

**修改本檔**：改本檔前先看 memory cluster `_index_fact_check_research_discipline` 有沒有新條目要升上來；[[fact-check-protocol]] wiki 已凍結，不再是收錄處。
