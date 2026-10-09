# 最強模型定義

這是使用者指定的換模免問名單，不是模型能力排名。目前只供 trial-review 的強模型通知使用；不改派工、模型設定或 effort。

## 免問名單

| 家族 | 實際模型識別 |
|---|---|
| Fable | `claude-fable-` 開頭的實際模型 ID |
| Astra | `GPT_ASTRA` 的值，讀 [GPT 版本表](/config/gpt-models.env)；不另存一份型號 |

如果主 session 的實際模型命中名單，就沿用目前模型，不發換模通知。strong 標記仍說明這題需要深入判斷，不代表還要換到另一顆模型。

## 判定順序

1. 取目前主 session 最近一筆非 `<synthetic>` assistant 事件的 `message.model`；不取 subagent、歷史其他 session 或報告自述的模型。
2. 比對前去除 effort 的 `(high)`／`(max)` 等尾綴與 `[1m]` context 標記，不因 effort 不同把同一家族判成另一顆模型。
3. 如果查不到實際模型，或只知道 requested alias／設定名稱，就不據此免問；例如 requested=`fable`、實際=`grok-4.7-build`，不算 Fable。
4. 如果未命中名單，就沿 trial-review 原有通知、停下等使用者與交接步驟；使用者已明說用目前模型繼續時，仍依原規則不重問。

免問只略過換模通知與為換模而暫停的動作，不省略認領、研究、證據查核或拍板。研究本身若有範圍、權威或風險待人類決定，仍照原流程停下。

## 維護

如果使用者更改免問家族，就改本檔並重驗通知分支。Astra 換代只沿 GPT 版本表，不改其他模型池或全域設定。
