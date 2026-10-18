# security-sibling-call-sites

抓到一個代表案例不等於抓完：同一個 patch 常常在好幾個地方犯同一件事。內容整理自搬遷前 `agents/security-reviewer.md` 的「同模式的其他呼叫點」一段（absorbed from openai/codex-security security-diff-scan + finding-discovery + final-report, 2026-08-01）。

## 適用

角色：security-reviewer。每次安全審查都套：擴查範圍只在 diff 動到下列 wrapper 時啟動，「報告時不准為了好看併條」每次報 finding 都適用。其他角色不套用。

## 同模式的其他呼叫點

抓到一個代表案例不等於抓完——同一個 patch 常常在好幾個地方犯同一件事。

**擴查範圍**：diff 動到 shared helper / guard / route pattern / query builder / serializer / 反序列化入口 / 檔案或網路 sink 的 wrapper 時，把「同一個 patch 也改到的」或「因為這次改動而變得可達的」其他呼叫點一併查，每一個各自帶自己的 source → control → sink 證據。

**收束邊界**：未被 diff 觸及的 sibling 當 negative control（對照組），只有在這次改動讓它**新**可利用、或動到它依賴的共用控制 / sink 時才報。該 pattern family 窮盡就停，不要擴散成整 repo 枚舉。

**報告時不准為了好看併條**：每一個可獨立攻擊的 source → control → sink 各自一條。同一支 helper 的不同 API mode（`execute` / `executemany` / `executescript`、`pickle.load` / `loads`、`yaml.load` / `load_all`）、不同 route、不同缺 auth 的 endpoint，都算獨立條目。只有「wrapper + 它唯一的 sink」這種拆不開的證據組才算同一條。

**wrapper 是可達性證據，不是收攏子 sink 的理由。** finding 若寫「所有 / 每個 X 都受影響」，就要把具體實作逐一列出來，不能只留在敘述裡。
