context 壓縮後，原生摘要常漏掉關鍵的原話與決定；compact-guard 在壓縮前存一份可稽核的 checkpoint，壓縮後把篩選過的原始對話證據注回來。


整個 `compact-guard/` 目錄放到 `~/.claude/compact-guard/`；先在該目錄跑 `npm test`，再用 `node bin/install.mjs --install` 把三組 hook 合併進設定（安裝器只管理帶 `compact-guard/v1/...` 識別碼的項目，會先備份）。Codex 的安裝與信任步驟、停用方式見 `compact-guard/README.md`。
