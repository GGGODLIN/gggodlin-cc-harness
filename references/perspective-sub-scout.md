# Perspective sub-scout（外部 archaeology）

源自 stanford-oval/storm 的 Perspective-Guided Question Asking：先找幾篇別人寫過的同題分析，讀出它們共用的切軸，再用這些軸出題。它治的是「題目沒定義清楚 / scope 過大 / 結果發散」——LLM 冷想的角度傾向回到讀題就看得到的那幾個，文獻裡的切軸才會逼出非顯而易見的問題（2026-08-25 合成案例：5 篇 artifact → 7 條軸，3 條是冷想不易命中的重框）。

呼叫點：`brainstorm` Step 2a（外部 archaeology，與 stack archaeology 並列）、`deep-research` Pre-scout Gate（與 URL pool scout 並行）。兩處都是可選子步驟，由下面的判準決定跑不跑。

## 跑不跑：可觀察判準

同時成立才跑：

1. 題目是「外面有人寫過的通用題」——把題目去掉個人名詞後（人名 / repo 名 / 自家機制名），剩下的問題能想像出一篇別人寫的分析文標題。想不出來 = 純自家機制設計題，跳過。
2. 題目還在發散（brainstorm 剛進場、或 deep-research 的 Gate 判為發散題）。事實盤點 / roster 批次 / 定價換算這類已定形的題直接跳過。

成本基準：1 個 agent、約 2.5 分鐘、約 77k tokens（2026-08-25 routed-judge 實跑；WebSearch 4 / WebFetch 5）。題目小到不值這個成本也跳過。

## Steps

派一個 agent（routed-judge）做 1–3，或 main session 自己跑；搜尋上限 8 次。

1. 找 3–5 篇對位 artifact：就這題已有人寫過的分析、比較文、landscape post、awesome list、同類 wiki entry；不要產品頁。每篇記 URL、標題、一句它涵蓋的軸。
2. 觀察這幾篇共用哪些 perspective 軸。
3. 抽 4–7 個 perspective set，每條一行：軸名 ＋ 它會逼出什麼非顯而易見的問題。
4. 交回呼叫點：brainstorm 拿它當 2b framing 的收據（framing 可引 URL）；deep-research 拿它當 Engine routing args 的分軸補強。

低信心 fallback：找不到 ≥3 篇 → 標「⚠️ 低信心 perspective set」、改由 LLM 自己推軸並明說沒有文獻收據；使用者可選 skip。

## 回傳形狀

```
artifacts_found: N
artifacts: URL | 標題 | 涵蓋軸（每篇一行）
shared_axes: 逗號清單
perspective_set: 4–7 行
low_confidence: yes/no
```

## 踩過的坑

- 2026-06-20〜08-25 掛在 deep-research 下 9 週 0 次真實跑：不是機制沒用，是入口錯了——「題目沒定形」的痛點實際走 brainstorm / wayfinder（同期 12 次），deep-research 只被拿來做事實題（1 次）。掛在哪一個 skill，要看痛點真正出現在哪條路。
