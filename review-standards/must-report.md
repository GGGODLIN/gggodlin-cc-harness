# must-report

程式碼審查必報清單。審程式碼正確性與品質的審查每次都套，不看路徑、不看語意。全 repo 只有這一份成員清單；其他文件要提到這些項目，只寫指向本檔的引用。

舊文件裡的「strict-liability」「不必先搜就能提」「always-flag」指的都是第二層。

## 第一層：危險訊號（每次都查）

每次審查都在 diff 新增或修改的行裡找下列訊號。訊號本身不是缺陷：找到後看第二層的成立條件與下方例外，條件不成立就不報成確定缺陷；要報就走呼叫端原本的找問題流程，含搜尋與舉證。

- 疑似憑證的字面值：API key、token、密碼、連線字串
- 字串串接或插值組出的 SQL
- `eval`、`new Function`（任何輸入）
- shell 指令呼叫（`child_process`、`subprocess` 的 shell 模式、`os.system` 之類）
- 明文密碼的比對或儲存
- `innerHTML`、`dangerouslySetInnerHTML`

## 第二層：證據充分時直接報

下列缺陷只要 diff 本身就證明成立，就直接報，不做全 repo 搜尋，也不做上游保護分析。嚴重度照各角色自己的判準，本清單不定嚴重度。

- 硬編憑證：diff 新增的真實憑證明文。不在下方「已知非敏感憑證」上。
- SQL 注入：SQL 由使用者輸入字串串接組成。
- `eval` 或 `new Function` 吃使用者可控的輸入。
- shell 指令帶使用者可控的輸入。
- 明文密碼的比對或儲存。
- `innerHTML` 或 `dangerouslySetInnerHTML` 吃使用者輸入，且沒有經過下方例外所列的消毒器。
- diff 內肉眼可見的 typo。

## 例外

例外只縮小第二層的成立條件，不新增必報項。

- 已知非敏感憑證：diff 新增的明文若是以下各檔寫明的 key，不算硬編憑證，範圍照各檔所寫，不擴大到同一 provider 的其他 key。位置引用，不在此複製 key 值。
  - `memory/feedback_context7_api_key_non_sensitive.md`
  - `memory/feedback_groq_free_api_keys_non_sensitive.md`
  - `memory/feedback_openrouter_personal_key_non_sensitive.md`
- 消毒後使用的 HTML：賦值前先經 `sanitize-html` 或 `DOMPurify` 過濾的 `innerHTML`、`dangerouslySetInnerHTML`，只當訊號檢查，不報成確定缺陷；檢查的是消毒器真的在這條賦值路徑上。看不到消毒器就回到第二層。
