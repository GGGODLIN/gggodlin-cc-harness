# security-validation-ladder

報之前先試重現，重現不了才退靜態；靜態追源的七元組與 confidence 三級。內容整理自搬遷前 `agents/security-reviewer.md` 的「驗證階梯」與「靜態追源的七元組」兩段（2026-08-01, from openai/codex-security validation + static-finding-assessment），原文保留。CRITICAL finding 要立刻報、並寫出使用者要做的輪替步驟，屬流程，留在定義檔。

## 適用

角色：security-reviewer。每次安全審查要把一條 finding 寫進報告前都套，不看路徑、不看語意。其他角色不套用。

## 驗證階梯（報之前先試重現，重現不了才退靜態）

依序取**最強可行**的方法，取到就停：

1. **既有測試 harness 加一個最小 focused test** — 斷言「漏洞行為成立」，不是斷言「功能正常」
2. **真實介面重現** — HTTP route / loader / action / CLI / parser 入口，餵最小 crafted input 打到 sink
3. **靜態追源** — 用下面的七元組

Build 失敗、缺服務、缺 secret、環境跑不起來 → **寫成 proof gap 留在 finding 裡，不是反證、不能當抑制理由。**

Confidence 由你實際拿到的最強證據決定，**不由 bug class 聽起來多可怕決定**。沒驗過就不要寫得像驗過。

## 靜態追源的七元組（缺哪格就明寫「未證」）

`source`（攻擊者可控的輸入從哪進來）→ `control`（該擋沒擋的那道守衛，file:line）→ `sink`（危險操作）→ `reachable path`（把前三者連起來的實際 code 路徑）→ `boundary`（哪個產品介面、跨了哪條信任邊界）→ `counterevidence`（你查到最強的反向 repo 證據）→ `proof gap`（缺哪個事實才無法下更強結論）

相依套件存在、字串命中、半條呼叫鏈——**都不算完成評估**。缺 runtime / 部署 / 政策事實時寫成 proof gap，不要腦補填上。

**Confidence 三級**：路徑精確 + 前提明確 + 無未解反證 = 高；路徑合理但呼叫鏈、config、版本或部署證據不全 = 中；靜態支撐薄弱或缺 repo 脈絡 = 低。
