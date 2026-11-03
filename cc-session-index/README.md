# cc-session-index (`ccsi`)

English | [繁體中文](/README.zh-TW.md)

Index your local **Claude Code**, **Codex**, and **Pi** `.jsonl` session transcripts into SQLite FTS5 (`tokenize='trigram'`), and stream normalized events across all three tools from a single standard-library Python script.

https://github.com/user-attachments/assets/66ce4fa8-bc2b-47f8-8938-64a539314320

The conversation in the video is made up. The 0.05 s is the same search run on the author's real index (2026-10-20, including Python startup).

Once a transcript folder grows past a few tens of gigabytes, `grep -r` across `.jsonl` files takes too long for an agent to run mid-turn. Most session-memory tools either use SQLite's default `unicode61` tokenizer, which cannot match Chinese, Japanese, or Korean substrings, or pin an English-only embedding model.

On the author's machine (`44 GB` across `53,016` `.jsonl` files, `1.50M` indexed rows, `3.5 GB` SQLite file, measured 2026-10-19), a full build takes `371.5s` and incremental runs take `0.6s–6.0s`.

## How it works

1. `ccsi index` walks the transcript roots for Claude Code, Codex, and Pi. For each file it stores `(mtime, size, offset, ino, rows)`. When a file grows with the same inode, `ccsi` seeks to the previous byte `offset` and indexes only the newly appended lines; if the last line is still being written and lacks a trailing newline, the cursor stays at the start of that line until the next run.
2. User and assistant text are written to an FTS5 table using the `trigram` tokenizer, alongside a `message_refs(mid, path)` lookup table so per-file replacements and `-C` context queries use an index instead of scanning FTS5.
3. Tool calls are summarized down to their searchable arguments (`Read`/`Edit`/`Write`/`NotebookEdit` file paths, `Bash` commands, `Grep`/`Glob` patterns, `Skill` names and args, `Agent`/`SendMessage` prompts). Tool calls with empty inputs (`{}`), expanded skill bodies (`Base directory for this skill:`), and `<system-reminder>` blocks are skipped; slash commands (`<command-name>`) and `<task-notification>` results are kept.
4. `ccsi events` reads the same transcripts and emits one JSONL object per event (`vendor`, `session`, `path`, `ts`, `cwd`, `role`, `kind`, `tool`, `model`, `text`) so you can query all three agents with `jq`.

| Vendor | Default Root (override env var) | Transcript Format |
|---|---|---|
| `cc` | `~/.claude/projects/**/*.jsonl` (`$CLAUDE_CONFIG_DIR/projects`) | `type=user/assistant` + `message` |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl`, `~/.codex/archived_sessions/rollout-*.jsonl` (`$CODEX_HOME`) | `session_meta` / `turn_context` / `response_item` / `event_msg` + `payload` |
| `pi` | `~/.pi/agent/sessions/**/*.jsonl` (`$PI_CODING_AGENT_DIR/sessions`) | `session` / `model_change` / `message` |

## Install

Requires Python 3.9+ linked against **SQLite 3.34.0+** with FTS5 `trigram` support (included in macOS Homebrew Python and standard Linux distributions). No `pip install` needed.

```sh
git clone https://github.com/GGGODLIN/cc-session-index.git
mkdir -p ~/.local/bin
ln -s "$PWD/cc-session-index/ccsi" ~/.local/bin/ccsi
# Ensure ~/.local/bin is in your PATH (e.g. export PATH="$HOME/.local/bin:$PATH")
ccsi index
```

### Wire into Claude Code (`~/.claude/CLAUDE.md`)

Putting `ccsi` on `PATH` is not enough on its own; the model will not call it unless a rule tells it when to look up past sessions. On the author's setup, `ccsi` was called 15 times in August before being added to the routing rules, and 2,569 times across 429 root sessions over September and October after adding this line to `~/.claude/CLAUDE.md` (or `rules/common/code-search.md`):

```markdown
- **Session history search** (how we solved X before, why an approach was dropped, which session made a decision) → `ccsi search "<query>" -k 5` (add `-C 2` for surrounding same-file messages, `--exclude-session <UUID-prefix>` to skip the current session, `--vendor {cc,codex,pi}` to filter). Uses SQLite FTS5 `trigram` (run `ccsi index` first if recent sessions are not indexed yet): include at least one >=3-char token or quoted phrase (e.g. `ccsi search '"測試 假綠"'`), and split uncertain multi-concept queries into separate searches. For unindexed `tool_result` outputs, use `ccsi events --session <id>`.
```

## Usage

```sh
ccsi index                                          # Build or incrementally update index (all vendors)
ccsi index --vendor codex                           # Index only a specific vendor (cc / codex / pi)

ccsi search "query string" -k 10                    # Full-text search (top 10 hits, 64-trigram snippet)
ccsi search "Herdr 左下角 狀態" -C 2                 # Show 2 indexed messages before & after hit in the same file
ccsi search '"測試 假綠"' -k 5                       # Pass literal quotes to FTS5 for a phrase of 2-char CJK words
ccsi search "advisor.md" --exclude-session 94c245bb # Exclude current session by UUID/path substring
ccsi search "pineedle" --vendor pi                  # Restrict search to one vendor

ccsi events --vendor codex --since 2026-09-13 --kind tool_call --tool spawn_agent
ccsi events --session 97ac80ca --kind text
```

### Storage & Environment Variables

- Default index location (created with `0700` directory and `0600` file permissions):
  - macOS: `~/Library/Caches/cc-session-index/index.sqlite`
  - Linux / other: `${XDG_CACHE_HOME:-~/.cache}/cc-session-index/index.sqlite` (absolute `XDG_CACHE_HOME` only)
  - Override: set `CCSI_DB_DIR=/custom/path`
- Concurrency: `ccsi index` acquires an exclusive `flock` on `<DB_DIR>/index.lock` before loading file metadata.

### Scheduled Background Refresh (Optional)

On macOS (`~/Library/LaunchAgents/local.cc-session-index.plist`), point `ProgramArguments` to your Python 3.9+ binary (e.g. `/opt/homebrew/bin/python3`) and run every 15 minutes (`900` seconds) at background priority:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>local.cc-session-index</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/python3</string>
    <string>/Users/YOUR_USER/.local/bin/ccsi</string>
    <string>index</string>
  </array>
  <key>StartInterval</key>
  <integer>900</integer>
  <key>ProcessType</key>
  <string>Background</string>
  <key>LowPriorityIO</key>
  <true/>
  <key>Nice</key>
  <integer>10</integer>
</dict>
</plist>
```

On Linux (`crontab -e`):

```cron
*/15 * * * * ~/.local/bin/ccsi index >> ~/.cache/cc-session-index/cron.log 2>&1
```

## Known limits

- FTS5 `trigram` needs at least one token or quoted phrase of 3 or more characters. Queries made only of 1–2 character tokens (or boolean/quoted queries with `< 3`-char operands) exit with code `2` instead of printing `(no hits)`. In plain space-separated queries that mix `>= 3`-char and `< 3`-char tokens, `ccsi` filters the short tokens with `LIKE`.
- `tool_result` outputs are not indexed in FTS. `messages` stores conversation text (capped at 8,000 chars) and summarized `tool_use` inputs (capped at 2,000 chars). To read `tool_result` outputs, run `ccsi events --session <id> --kind tool_result` (capped at 8,000 chars per event) or open the `.jsonl` file.
- Incremental indexing assumes `.jsonl` files are append-only (`st_ino` unchanged and `st_size` grown), and deleted `.jsonl` files are not purged from `index.sqlite`. Delete `index.sqlite` and run `ccsi index` to rebuild from scratch.

## Tests

```sh
python3 test_ccsi.py -v
```

## License

[MIT](/LICENSE)
