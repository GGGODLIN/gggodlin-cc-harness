# Research Before Answer — 歷史踩坑與規則演進紀錄

本檔保存自 `SKILL.md` 移出的歷史案例與規則演進背景；現役執行規則與 R1–R4 自查標準均已寫入 `SKILL.md` 正文。

- WebSearch 排名容易漏掉官方文件，需搭配 chrome SERP nav 並行比對才不會漏
- WebFetch 拿到 4xx/5xx 或內容明顯不夠（403 / 亂碼 / 模板）時必須立刻 fallback，不能回「抓不到」就跳過
- 用瀏覽器抽取 SPA 內容時要按頁面狀態等待再讀，通用抓法會漏（舊瀏覽器工具時期的經驗，原文已退役、公開版不附）
- 查證做得再全、交付端仍會丟資訊：低信心標記被平述、來源限制被整條省略、無版號成績掛到具體版號（離線抽驗連兩週抓到真 FAIL）→ 加「交付前 inline 自查」段
- 2026-08-25 抽驗抓到三種漏網：decision table 的取捨列沒逐列出處、proxy metric 被外推成 target verdict、未查證的 cleanup／成本理由被拿來排除方案；另有 auditor 回 `R2 FAIL` 卻同時寫 `VERDICT: COMPLIANT`。修法是 claim inventory、metric→target→attribution、替代方案理由納入 R2/R3，以及互斥 verdict＋final draft 重驗。
- 2026-08-29 同一份 draft、同一條「信心標記」規則，auditor 兩輪各自解讀（第一輪抓 2 處漏 token 倍數、第二輪只抓 token 倍數）：規則只寫判準沒給實例，「宣稱」兩字被當成標記、對象自稱沒列進來源清單。修法＝來源清單補「對象自稱」、附一對只差 ⚠️＋來源註的 ❌／✅ anchor、第一手指令數字明文排除；同稿加 anchor 後 2/2 抓全，壓力場景 4 FAIL／1 PASS／3 N-A 零誤標。機制借自 NeoLabHQ/context-engineering-kit meta-judge（改寫不抄）
- 2026-10-15 16 題回歸評測在 Claude runtime（sonnet-4-6）為 5 PASS／10 FAIL／1 ERROR，同題 GPT runtime 為 11/5：LCU 在 eval 環境失敗後，GPT 轉走 fetch-fallback／gh 抓原頁，Claude 停在 WebSearch 摘要作答、出處堆文末、自填 self-verify: COMPLIANT、刪子 agent 的「找不到」。修法＝R1 把 SERP 降為找 URL、淺題接抓取層、R2 同句出處 anchor、R3 子 agent 限定句原樣保留、未派 auditor 不寫 self-verify 行
