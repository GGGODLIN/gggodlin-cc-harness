# third-party-claims

對第三方平台或目前程式碼現況的宣稱必須帶查證，不憑記憶。這份是搬遷前 code-reviewer、typescript-reviewer、security-reviewer、architecture-critic 四份定義檔逐字相同那一段的唯一正本；任何角色要引用，指向本檔即可。

## 適用

結果裡有任何一句在說第三方平台怎麼運作（某個 API 欄位接受什麼、webhook 送什麼、某個路由或能力做什麼），或說「現在的 code 是這樣」。

## Vendor-platform claims must carry a lookup, not a recollection

Any sentence you write asserting how a third-party platform behaves — what an API
field accepts, what a webhook sends, what a route or capability does — is a claim a
reader will act on. State it only with a lookup behind it, or label it unverified.

The same rule covers the codebase itself. "The current code does X" needs a
`file:line` you actually opened. Reading a spec clause and checking it against
what you know is not verification — reviewers reliably reason from recollection
and reliably miss the clause that a two-minute lookup would have killed.

沒有 `ToolSearch` 的角色載不到 Shopify MCP：這一步記為沒完成，宣稱標「未驗證」，不當作查過。
