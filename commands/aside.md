---
description: Answer a quick side question without interrupting or losing context from the current task. Resume work automatically after answering.
---

# Aside Command

Ask a question mid-task and get an immediate, focused answer — then continue right where you left off. The current task, files, and context are never modified.

## Process

Do NOT touch, edit, create, or delete any files during the aside.

### Step 2: Answer the question directly

Answer only what was asked; leave the supporting detail for after the task.

- Lead with the answer, not the reasoning
- If the question is about the current file or code being worked on, reference it precisely (file path and line number if relevant)
- If answering requires reading a file, read it — but read only, never write

Format the response as:

```
ASIDE: [restate the question briefly]

[Your answer here]

— Back to task: [one-line description of what was being done]
```

### Step 3: Resume the main task

After delivering the answer, immediately continue the active task from the exact point it was paused. Do not ask for permission to resume unless the aside answer revealed a blocker or a reason to reconsider the current approach (see Edge Cases).

---

## Edge Cases

**No question provided (`/aside` with nothing after it):**
Respond:
```
ASIDE: no question provided

What would you like to know? (ask your question and I'll answer without losing the current task context)

— Back to task: [one-line description of what was being done]
```

**Question reveals a potential problem with the current task:**
Flag it clearly before resuming:
```
ASIDE: [answer]

⚠️ Note: This answer suggests [issue] with the current approach. Want to address this before continuing, or proceed as planned?
```
Wait for the user's decision before resuming.

**Question is actually a task redirect (not a side question):**
If the question implies changing what is being built (e.g., `/aside actually, let's use Redis instead`), clarify:
```
ASIDE: That sounds like a direction change, not just a side question.
Do you want to:
  (a) Answer this as information only and keep the current plan
  (b) Pause the current task and change approach
```
Wait for the user's answer — do not make assumptions.

**Question is about the currently open file or code:**
Answer from the live context. If the file was read earlier in the session, reference it directly. If not, read it now (read-only) and answer with a file:line reference.

**No active task (nothing in progress when `/aside` is invoked):**
Still use the standard wrapper so the response shape stays consistent:
```
ASIDE: [restate the question briefly]

[Your answer here]

— Back to task: no active task to resume
```

**Question requires a long answer:**
Give the essential answer concisely, then offer:
```
That's the short version. Want a deeper explanation after we finish [current task]?
```

**Multiple `/aside` questions in a row:**
Answer each one in sequence. After the last answer, resume the main task. Do not lose task state across a chain of asides.

**Aside answer implies a code change is needed:**
Note the change needed but do not make it during the aside:
```
ASIDE: [answer]

📝 Worth fixing: [what should be changed]. I'll flag this after the current task unless you want to address it now.
```

**Question is ambiguous or too vague:**
Ask one clarifying question — the shortest question that gets the information needed to answer. Do not ask multiple questions.

