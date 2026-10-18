# pr-review-baseline-dependency-bumps

`/pr-review` 的跨面向基準清單之一（Dependency Bumps）。共通說明見 `pr-review-baseline-reuse`。

## 適用

由 `/pr-review` 派出時必套：派工 prompt 寫「由 /pr-review 派出」就套用。本組內容照原清單只在 PR 的 diff 觸及依賴檔時才適用（下方第一句），沒有依賴變更就不必逐條交代。

## 檢查項（Dependency Bumps）

PR 的 diff 觸及 package.json / lockfile / 版本檔時加掃三律（absorbed from addyosmani/agent-skills, 2026-07-11）：

1. **Read the changelog, not just the version number** — reviewer 要求 PR 描述附 changelog 重點（或自己 `gh api` / registry 查）；「只是 bump 版本」不是免審理由，breaking change 常藏在 minor。
2. **One dependency per change** — 一個 PR 混多個無關依賴升級 → 建議拆；出事時無法 bisect 是哪一個。
3. **Review the lockfile diff, not just package.json** — transitive 依賴的實際變動在 lockfile；package.json 沒動但 lockfile 大動 = 重點審查對象（supply-chain 面同時參照 strict-liability 清單）。
