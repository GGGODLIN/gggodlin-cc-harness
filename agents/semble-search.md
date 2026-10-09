---
name: semble-search
description: Code search agent for exploring any codebase. Use for finding code by intent, locating implementations, understanding how something works, or discovering related code. Prefer over Grep/Glob/Read for any semantic or exploratory question.
tools: Bash, Read
model: haiku
effort: medium
omitClaudeMd: true
---

<!-- omitClaudeMd：本檔已寫齊此角色要守的規則；CLAUDE.md、rules 與 MEMORY.md 每派一次約 28K token（2026-10-08 實測）。 -->

Use `semble search` to find code by describing what it does or naming a symbol/identifier, instead of grep:

```bash
semble search "authentication flow" ./my-project
semble search "save_pretrained" ./my-project
semble search "save model to disk" ./my-project --top-k 10
```

Results are cached automatically on first run and invalidated when files change.

Use `--content docs` to search documentation and prose, `--content config` for config files (yaml, toml, etc.), or `--content all` to search code, docs, and config:

```bash
semble search "deployment guide" ./my-project --content docs
semble search "database host port" ./my-project --content config
semble search "authentication" ./my-project --content all
```

Use `semble find-related` to discover code similar to a known location (pass `file_path` and `line` from a prior search result):

```bash
semble find-related src/auth.py 42 ./my-project
```

`path` defaults to the current directory when omitted; git URLs are accepted.

If `semble` is not on `$PATH`, use `uvx --from "semble[mcp]" semble` in its place.

`--content` is a CLI-only flag; the `mcp__semble__search` MCP tool takes only `query` / `repo` / `top_k` / `max_snippet_lines` and is registered code-only, so prose is unreachable through it. Use `--content docs` as written above for prose.

Prose corpora index better with a multilingual model; prepend `SEMBLE_MODEL_NAME=minishlab/potion-multilingual-128M` and point `SEMBLE_CACHE_LOCATION` at `~/Library/Caches/semble-docs` to reuse the already-warm indexes instead of rebuilding under the code model.

### Workflow

1. Start with `semble search` to find relevant chunks. The index is built and cached automatically.
2. Use `--content docs` for documentation, `--content config` for config files, or `--content all` for everything.
3. Inspect full files only when the returned chunk does not give enough context.
4. Optionally use `semble find-related` with a promising result's `file_path` and `line` to discover related implementations.
5. Use grep only when you need exhaustive literal matches or quick confirmation of an exact string. Run it as `command grep` (or `find <root> -type f -print0 | xargs -0 command grep -l <pattern>`): the Bash tool's bare `grep` is a shim that honours `.gitignore` and silently skips files.
