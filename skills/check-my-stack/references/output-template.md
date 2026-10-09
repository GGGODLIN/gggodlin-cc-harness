<!-- 本檔在契約測試底下：bash ~/.claude/skills/check-my-stack/scripts/tests/plain-language-presentation.test.sh -->

# Output Template

The competitive analysis report is a plain-language answer followed by exactly four blocks, a Gate Ledger, and a verdict. The full order is: 先用白話回答 → Block 1 → Block 2 → Block 3 → Block 4 → Gate Ledger → Verdict. Block 1 remains the first evidence block because it prevents a feature-tour framing. (A Step 0 fast-kill report is shorter: plain-language answer + Gate Ledger + verdict only.)

## 先用白話回答

依序寫下列六項，用小標題分開，每項寫給沒看過這個工具的使用者。這段不使用 extract／frame／Gate Ledger／商數／maturity／reconcile 等內部術語；其他術語第一次出現就附一句白話。六項都是下方 blocks 的白話摘要，不為它多跑任何步驟：

1. **結論**：一兩句直接回答使用者原問句——值不值得、整包還是只借一部分。
2. **它是什麼**：白話講它幫人做什麼，並點名在使用者手上對應 Block 1 的哪一項。
3. **跟你現有的差在哪**：Block 2 的白話摘要——對照那一項多了什麼、少了什麼。
4. **用了會得到什麼**：Block 3 的白話摘要——哪些情況用得上，以及使用者有沒有這個痛點。
5. **代價**：會不會動到使用者的設定或流程、要花的錢／token／API key／訂閱、license 與維護風險。
6. **依結論二選一**：trial → 最小試用步驟（最多三步）與觀察什麼；extract 或拒絕 → 可借走的機制與要接進哪裡（Block 4），沒有就寫「沒有」。

預設路徑的聊天主報告＝這六項＋六項沒涵蓋到的原問句各一段白話答案＋Verdict 一行＋證據副檔連結；下方 Blocks 1–4 與 Gate Ledger 寫入證據副檔，不貼回聊天。

## 退役／缺口盤點路徑

使用者在盤點既有 pack／framework 退役前缺口時，聊天主報告固定為 `缺什麼／哪些已對應／退役前做哪三件`，並附證據副檔連結。完整 Blocks 1–4 與 Gate Ledger 寫入證據副檔；分析本身仍完整走完，不把這條路當 narrow-scope 捷徑。

## Block 1 — Existing stack inventory (the baseline)

A compact table of what the user already has in this domain. This establishes the divisor before the tool is described.

| Capability area | Existing implementation (name it precisely) | Maturity | Reconciled |
|---|---|---|---|

Maturity values: mature / mature+automated / in-trial / rejected-and-removed / aspirational. The Reconciled column is filled only for load-bearing rows: `install-verified` / `adoption-verified` / both / `unreconciled`. A row that fails a check keeps its honest label ("installed, adoption unverified") — it cannot be cited as a mature divisor.

Below the table, state in one or two sentences the governing lesson that runs through the user's prior decisions in this domain.

## Block 2 — Tool capability ÷ existing maturity (point-by-point)

| Tool selling point | User's existing equivalent | Quotient |
|---|---|---|

Quotient column is a conclusion, not a description: `≈0, yours is at least as good` / `<0, re-litigates a settled rejection` / `non-zero — see Block 4`. After the table, write a short prose paragraph on the **key quotient argument** — the tool's most consequential row and why the arithmetic lands where it does, in either direction. Name the specific prior case it echoes if one was actually retrieved.

## Block 3 — Best-frame search result

The tool's own frame plus at most one alternative frame, each anchored to a named Block 1 capability area and carrying its pain-vs-absence answer:

| Frame | Anchors to (Block 1 area) | Pain or absence? | Assessment |
|---|---|---|---|

"None found" beyond the tool's own frame is a legal, common result — say it plainly rather than inventing a speculative frame.

## Block 4 — Extraction hunt result

Only when the hunt ran (draft verdict was rejection/landscape). Otherwise write one line: "not run — draft verdict was adopt/trial".

| Stealable mechanism | Graft point in the user's stack | Reason rejected (if rejected) |
|---|---|---|

Closed-source tools: note the downgrade to API-level / architecture-concept assessment. Report the hunt honestly whichever way it goes — neither pad it to make the tool look useful, nor wave it off in one line when source was available and unread.

## Gate Ledger (before the verdict — the audit artifact)

Fixed lines; every line appears even when the answer is "unchecked":

```
Step 0: <no-qualification | lineage: <entry> + 同型論證 + mini-reconcile result | dealbreaker: <entry>>
Challenge 1 mechanism layer: <checked → evidence | unchecked>
Challenge 2 alternative frame: <checked → Block 3 pointer | unchecked>
Challenge 3 extraction: <checked → Block 4 pointer | unchecked>
Challenge 4 testing triage: <Runnable now → output below | with-approval → command+risk | not-cheap → blocking factor + would-run command>
Tool-specific axis: <finding | none, checked>
Test output: <pasted result | n/a>
```

## Verdict

One paragraph. State the outcome (adopt / trial / extract / watch-defer / landscape) and the reasoning's convergence point, whatever the root cause is. Then the required attachments by outcome: rejection → work shown + overturn condition; trial → KPI + review date + kill condition + active.md entry name; extract → mechanism + graft point + next action; watch-defer → revisit trigger. Close with the action exit — "cheapest path to value" or "the test that would settle it"; "none — overturn condition: X" is legal, and Step 0 fast-kills skip the action path. Record the frame-scoped write-back line that went to the precedent log.

## Table-width discipline (enforce before emitting any table)

The user reads in a terminal where over-wide tables are reformatted and lose information. Before emitting each table:

- Keep each row's display width ≤ 120 chars, counting CJK characters as width 2.
- Never use `<br>` inside cells — it is not rendered and the literal string is counted into width.
- Pre-scan every cell for: markdown links, enumerations of 4+ items, full sentences. If a cell hits any of these, do not use a table — convert that content to prose or split into a narrower table.
- Row/column count is not the trigger; rendered display width is. When a row would exceed the limit, move detail into the prose paragraph that follows the table rather than widening cells.
