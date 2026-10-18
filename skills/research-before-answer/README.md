# `research-before-answer` — 回答前雙軌事實查證圖解

回答涉及具體套件、版本、API、價格、政策或最新外部動態的問題前，強制先分流題型、走第一手來源與雙軌搜尋，並在輸出前完成 R1–R3 自查，避免拿過時記憶或二手摘要當事實。完整規範見同目錄的 [`SKILL.md`](/skills/research-before-answer/SKILL.md)。

## 運作流程圖

![research-before-answer 雙軌事實查證與自查流程](/skills/research-before-answer/research-before-answer-flow.svg)

<details>
<summary>展開查看 Mermaid 結構原始碼（供 Agent／文字搜尋對照）</summary>

```mermaid
flowchart LR
  subgraph S1["Stage 1 · 題型與來源分流"]
    Trigger["識別事實查證觸發條件"] --> Ext["最新外部事實／本人即時資格"] --> Hist["個人歷史決策回顧（wiki + memory）"]
  end
  subgraph S2["Stage 2 · 雙軌搜尋與第一手抓取"]
    Gate1["GATE 1：LCU Google SERP ＋ WebSearch 配對"] --> Primary["Context7 / gh / LCU Firecrawl 第一手抓取"]
    Gate1 -.-> Monid["Monid 社群評價補查（選用）"]
  end
  subgraph S3["Stage 3 · R1–R3 交付前自查"]
    Verify["R1–R3：第一手來源・同句出處・代理指標分離"] --> Output["GATE 2：決策表出處綁定與低信心標記"]
  end
  Hist --> Gate1
  Primary --> Verify
  Monid -.-> Verify
```

</details>

## 同目錄與隨附元件對照

| 檔案 | 角色 |
|---|---|
| [`SKILL.md`](/skills/research-before-answer/SKILL.md) | 觸發條件、三路分流、雙軌搜尋、網頁抓取退路與 R1–R3 自查規則 |
| [`/rules/common/fact-check.md`](/rules/common/fact-check.md) | 與本 skill 配對的 17 條常駐事實查證紀律（本 skill 管流程、rule 管門檻） |
| [`references/monid-opt-in.md`](/skills/research-before-answer/references/monid-opt-in.md) | 補查社群評價與外部公開資料時的贈額查價與邊界規範 |
| [`evals/eval.yaml`](/skills/research-before-answer/evals/eval.yaml) ＋ [`evals/cases/`](/skills/research-before-answer/evals/cases/) | 16 個真實查證陷阱的評估題庫（版本幻覺、免費額度變更、代理指標誤判等） |
| [`scripts/tests/inline-verify-contract.test.sh`](/skills/research-before-answer/scripts/tests/inline-verify-contract.test.sh) | 鎖定 R1–R3 自查條款與決策表輸出格式的契約測試 |
