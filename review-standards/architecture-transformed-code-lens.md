# architecture-transformed-code-lens

審轉換過（例如 code-modernization 產出）的程式碼時用的懷疑式檢查。內容搬自搬遷前 `agents/architecture-critic.md` 的 Review lens 第二半（For transformed code），文字不改。

## 適用

角色：architecture-critic。審查對象是轉換過或剛改寫的程式碼模組。審的是文件、spec 或 packet 時不適用；派工 prompt 明說忽略這一組（`/review-spec` 會這樣關掉它）時，記為相關但沒套用並寫「派工指定」。其他角色不套用。

## For transformed code

- Is this idiomatic for the target stack, or is legacy structure leaking
  through? (Flag "JOBOL" — procedural Java with COBOL variable names.)
- Is error handling meaningful or ceremonial?
- Are there abstractions with exactly one implementation and no second use
  case in sight?
- Does the test suite actually pin behavior, or just exercise code paths?
- What would the on-call engineer need at 3am that isn't here?
