# security-llm-features

diff 碰到 LLM 呼叫、prompt 組裝、agent 工具或 RAG 時的安全檢查，對映 OWASP Top 10 for LLM Applications（absorbed from addyosmani/agent-skills security-and-hardening + security-auditor, 2026-07-11）。內容整理自搬遷前 `agents/security-reviewer.md` 的「AI / LLM Feature Check」一段。

## 適用

角色：security-reviewer。diff 含 LLM 呼叫、prompt 組裝（system prompt 或 user prompt 拼接）、agent 工具、RAG 時才適用。路徑只是提示：`**/prompts/**`、`**/llm/**`、`**/agents/**`、`**/rag/**` 先列為候選；路徑沒比對到不能排除這一組，改動檔名不含這些字樣（例如一般的 `src/summarize.ts`）時，看 diff 有沒有把使用者內容、抓來的網頁或檔案內容拼進 prompt，有就套用。其他角色不套用。

## AI / LLM Feature Check

1. **Model output is untrusted input**（LLM05）— LLM 輸出直通 `eval` / SQL / shell / `innerHTML` / 檔案路徑？跟使用者輸入同等對待：驗證、參數化、escape。
2. **System prompt is not a security boundary** — 權限、租戶隔離、費用上限靠 prompt 裡的「你不可以…」約束？必須在 code 層 enforce；prompt 可被注入繞過。
3. **Prompt injection surface**（LLM01）— 使用者內容 / 抓來的網頁 / 檔案內容被拼進 prompt 時有沒有隔離標記？拼接處是注入口。
4. **Excessive agency**（LLM08 類）— agent 拿到的工具權限超過任務需要？mutation 類工具有沒有 confirm / allowlist gate？
5. **RAG tenant partition** — 多租戶場景 embeddings / vector store 有沒有 per-tenant 隔離？query 時 filter 靠 LLM 自律 = 沒有隔離。
6. **Unbounded consumption**（LLM10）— 使用者可觸發的 LLM 呼叫有沒有 rate limit / token 上限 / 迴圈上限？沒有 = 錢包 DoS。
