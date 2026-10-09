# Survived Mutant Decision Tree

每個 survived mutant 依此樹判 A/B/C——不要跳、每個都要有分類。

## 決策樹

```
Survived mutant → 問三個問題：

Q1. 這個 mutant 若被線上使用者觸發，會不會產生錯誤的可觀察行為？
    （錯的資料、錯的 UI、錯的 API 回應、錯的計算結果）
    │
    ├─ 是 → A. 寫新 test / 補 assertion kill 它
    │       修法：見 references/survived-patterns.md 對應 pattern
    │
    └─ 否 → Q2

Q2. 這個 mutant 產出的 code 跟原 code 語意等價嗎？
    （例：`i < n` 換 `i != n` 在 for-i-0-loop 等價；
      移除 early-return optimization 但下游邏輯結果相同；
      external API wrapper 兩種 call 產生同結果）
    │
    ├─ 是 → B. 加 // Stryker disable next-line <MutatorName> comment
    │       Comment 內容：說明「為什麼等價」（不是說「這裡不測」）
    │       位置規則：見 references/disable-syntax.md（放錯 silently 失效）
    │
    └─ 否 → Q3

Q3. 這個 mutant 對應的 code path 是 I/O / 防禦性 fallback / catch block error log？
    （unit test 難觸發、integration test 才驗）
    │
    ├─ 是 → C. 判定合法 NoCoverage
    │       Stryker 通常會自己標 # no cov、不需 disable comment
    │       若沒標 → 加 // Stryker disable all 包住該 block、附原因
    │
    └─ 否 → 回 Q1 重新想（可能誤判為「不影響行為」）
```

## Q1 判準：怎麼問「會不會產生錯誤可觀察行為」

想像 mutant 已 ship 到 prod、有 user 觸發到這行：

- 使用者輸入 `{plus: true}`、原 code 回 `'plus'`、mutant 回 `''`——**使用者看到的分類錯了** → Q1 = 是 → A
- Function 內部 `arr.length === 0 return []` 被移除、`[].map()` 也是 `[]`——**使用者無感** → Q1 = 否 → Q2 = 是 → B
- Function 讀 `fs.readFileSync(path)` mutant 換 encoding——**測試環境無這個檔** → Q1 = 否 → Q2 = 否（不等價）→ Q3 = 是 → C

## 常見誤判

### 誤判 1：把 A 錯判為 B

**症狀**：加了 disable comment 但實際上這 mutation 會影響行為。

**訊號**：Comment reason 寫「這裡不重要」/「這是內部 detail」——這種語言 = 你在合理化跳過寫 test。真的等價的 comment 該寫「因為 X 條件下 Y 結果與 Z 結果相同」——**具體、可驗證**。

### 誤判 2：把 C 錯判為 A

**症狀**：硬造 test 觸發 nullish fallback、mock 一大堆 I/O。

**訊號**：Test 寫完後 mock 比 assertion 還多、`jest.fn().mockResolvedValue()` 一堆——test 在測 mock 不在測 logic。

**修法**：判 C 就 disable、把該 code path 交給 integration test。

### 誤判 3：把 B 錯判為 A（過度嚴格）

**症狀**：Early-return optimization 硬寫 test 驗「有沒有跳過 map」。

**訊號**：Test 要用 spy 監測「有沒有呼叫 map」——這是白盒測試 implementation detail、不是行為。

**修法**：判 B、disable comment 附 optimization 原因。

## 對 rerun 的期待

補完 A/B/C 決策 rerun stryker：

- A 修完 → mutation score 上升（killed 增加）
- B 加完 → mutation score 上升（該 mutant 從 stats 移除）
- C 判完（若加 disable all）→ 同 B

若 rerun 分數沒動 → 你的 A assertion 沒真的 kill 對應 mutant（可能 mock 了、可能 assertion 太寬）—— 回 Q1 檢查。
