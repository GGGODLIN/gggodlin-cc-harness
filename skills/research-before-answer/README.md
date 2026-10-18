# `research-before-answer` — 回答前雙軌事實查證圖解

回答涉及具體套件、版本、API、價格、政策或最新外部動態的問題前，強制先分流題型、走第一手來源與雙軌搜尋，並在輸出前完成 R1–R3 自查，避免拿過時記憶或二手摘要當事實。完整規範見同目錄的 [`SKILL.md`](/skills/research-before-answer/SKILL.md)。

## 運作流程圖

```mermaid
flowchart TD
  Start(["涉及具體版本 / API / 價格 / 外部事實"]) --> Route{"來源選路：\n這題問的是什麼？"}

  Route -- "最新外部事實 / 外部探索" --> ExtRoute["直接查外部第一手來源\n（禁用本機 memory / wiki 當探索入口）"]
  Route -- "使用者本人目前資格 / 額度" --> SelfRoute["讀目前帳號、設定檔或即時回應\n（不翻歷史記憶猜現況）"]
  Route -- "個人歷史決策回顧" --> HistRoute["並行查 ~/.claude/wiki/ ＋ ~/.claude/memory/\n＋ session 歷史索引"]

  ExtRoute --> FetchType{"外部資料型態？"}
  FetchType -- "已知套件 / 框架文件" --> OfficialDoc["Context7 MCP ／ gh CLI ／ 官方原碼與 changelog"]
  FetchType -- "開放式網頁搜尋" --> PairedSearch["雙軌搜尋配對（Ticket Model）\nLCU 讀 Google SERP ＋ WebSearch API"]
  FetchType -- "公開 HTML / X 貼文" --> PageFetch["LCU（含 Firecrawl Playground）優先\n缺內容接 🔌 非官方內容抓取退路（見 WIRING.md）"]
  FetchType -- "需補社群評價 / 實測評論" --> Monid["讀 references/monid-opt-in.md\n於授權贈額內查唯讀接口"]

  OfficialDoc --> Verify["交付前 Inline 自查（R1–R3）"]
  PairedSearch --> Verify
  PageFetch --> Verify
  Monid --> Verify
  SelfRoute --> Verify
  HistRoute --> Verify

  subgraph InlineVerify["R1–R3 交付前檢查"]
    direction TB
    R1["R1：每個關鍵宣稱都有第一手來源（二手摘要只當線索）"]
    R2["R2：數據、價格、限制同句附上可點出處與查證日期"]
    R3["R3：代理指標（proxy）不等於目標結論；未驗證處明標『?』或低信心"]
  end

  Verify --> InlineVerify
  InlineVerify --> Output(["輸出最終回答（決策表逐列附來源）"])
```

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`SKILL.md`](/skills/research-before-answer/SKILL.md) | 觸發條件、三路分流、雙軌搜尋、網頁抓取退路與 R1–R3 自查規則 |
| [`/rules/common/fact-check.md`](/rules/common/fact-check.md) | 與本 skill 配對的 17 條常駐事實查證紀律（本 skill 管流程、rule 管門檻） |
| [`references/monid-opt-in.md`](/skills/research-before-answer/references/monid-opt-in.md) | 補查社群評價與外部公開資料時的贈額查價與邊界規範 |
| [`evals/eval.yaml`](/skills/research-before-answer/evals/eval.yaml) ＋ [`evals/cases/`](/skills/research-before-answer/evals/cases/) | 16 個真實查證陷阱的評估題庫（版本幻覺、免費額度變更、代理指標誤判等） |
| [`scripts/tests/inline-verify-contract.test.sh`](/skills/research-before-answer/scripts/tests/inline-verify-contract.test.sh) | 鎖定 R1–R3 自查條款與決策表輸出格式的契約測試 |
