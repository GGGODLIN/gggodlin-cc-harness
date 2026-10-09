回報規則寫在 CLAUDE.md 裡，長對話中模型會逐漸忘記；把白話回報規則做成 output style，就能每個回合收到提醒。


檔名與 frontmatter 的 name 刻意取內建 style 的名字 Explanatory：原作者在 Claude Code 2.1.234 實測，只有內建名字（Explanatory／Learning／Proactive）每回合會收到「記得遵守 style」的提醒，自訂名字收不到；自訂檔取內建名字，可以同時拿到自己的內容和提醒。這靠的是實作細節、不是官方保證，改版後可能安靜失效（退回真正的內建 Explanatory，沒有錯誤訊息）。frontmatter 的 `keep-coding-instructions` 預設是 false，會拿掉 Claude Code 內建的工程指令，這裡刻意設 true。
