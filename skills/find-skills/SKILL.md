---
name: find-skills
description: Use only when the user explicitly asks about extending agent capabilities or installing new skills - "find a skill for X", "is there a skill that can...", "裝個 skill 來做 X". Do not use for general how-to or technical questions (those go to normal research, not skill discovery), nor when the user just wants the task done.
upstream: vercel-labs/skills
upstream-path: skills/find-skills/SKILL.md
upstream-status: needs-reconciliation
---

# Find Skills

上游變化：`diff` 本檔與 `~/.agents/skills/find-skills/`（CLI 管理的副本，`npx skills update` 後比對）。

This skill helps you discover and install skills from the open agent skills ecosystem.

## What is the Skills CLI?

The Skills CLI (`npx skills`) is the package manager for the open agent skills ecosystem. Skills are modular packages that extend agent capabilities with specialized knowledge, workflows, and tools.

**Key commands:**

- `npx skills find [query]` - Search for skills interactively or by keyword
- `npx skills add <package>` - Install a skill from GitHub or other sources
- `npx skills check` - Check for skill updates
- `npx skills update` - Update all installed skills

**Browse skills at:** https://skills.sh/

## How to Help Users Find Skills

### Step 2: Check the Leaderboard First

Before running a CLI search, check the [skills.sh leaderboard](https://skills.sh/) to see if a well-known skill already exists for the domain. The leaderboard ranks skills by total installs, surfacing the most popular and battle-tested options.

For example, top skills for web development include:
- `vercel-labs/agent-skills` — React, Next.js, web design
- `anthropics/skills` — Frontend design, document processing

### Step 3: Search for Skills

If the leaderboard doesn't cover the user's need, run the find command:

```bash
npx skills find [query]
```

For example:

- User asks "how do I make my React app faster?" → `npx skills find react performance`
- User asks "can you help me with PR reviews?" → `npx skills find pr review`
- User asks "I need to create a changelog" → `npx skills find changelog`

### Step 4: Verify Quality Before Recommending

**Do not recommend a skill based solely on search results.** Always verify:

1. **Install count** — Prefer skills with 1K+ installs. Be cautious with anything under 100.
2. **Source reputation** — Official sources (`vercel-labs`, `anthropics`, `microsoft`) are more trustworthy than unknown authors.
3. **GitHub stars** — Check the source repository. A skill from a repo with <100 stars should be treated with skepticism.

### Step 5: Present Options to the User

When you find relevant skills, present them to the user with:

1. The skill name and what it does
2. The install count and source
3. The install command they can run
4. A link to learn more at skills.sh

Example response:

```
I found a skill that might help! The "react-best-practices" skill provides
React and Next.js performance optimization guidelines from Vercel Engineering.
(185K installs)

To install it:
npx skills add vercel-labs/agent-skills@react-best-practices

Learn more: https://skills.sh/vercel-labs/agent-skills/react-best-practices
```

### Step 6: Offer to Install

若使用者點頭，實際安裝命令：

```bash
npx skills add <owner/repo@skill> -g -y
```

The `-g` flag installs globally (user-level) and `-y` skips confirmation prompts.

### Step 7: Confirm the Install

After installing, verify the skill directory actually exists (e.g. `ls ~/.agents/skills/<skill>` or the path the CLI reported) and tell the user it is ready. An install command that errored silently leaves the user thinking they have a skill they don't.

## When No Skills Are Found

沒有相符的 skill 時：說明沒找到，直接用一般能力接手該任務，並在使用者常做這件事時提一句 `npx skills init <name>` 可自建。
