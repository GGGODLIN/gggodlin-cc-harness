# cc-session-index (`ccsi`)

English | [繁體中文](/README.zh-TW.md)

Single-file, zero-dependency SQLite FTS5 (`tokenize='trigram'`) full-text index and normalized event stream over local coding-agent session transcripts (**Claude Code**, **Codex**, and **Pi**).

Instead of running slow `grep -r` scans across tens of gigabytes of `.jsonl` session logs—or adopting heavy vector/Electron stacks whose default tokenizers fail on CJK (Chinese/Japanese/Korean) substrings—`ccsi` gives your coding agent sub-second literal and CJK substring search with append-only incremental indexing in ~600 lines of standard-library Python.

## Why `ccsi`

1. **Native CJK & substring search (`trigram`)**: SQLite's default `unicode61` tokenizer cannot search arbitrary CJK substrings, and many embedding-based session memory tools pin English-only models. `ccsi` uses FTS5 `trigram`, so 3+ character CJK phrases, file paths, identifiers, and error strings work out of the box.
2. **Append-only byte cursor + `message_refs` positioning**: On a production corpus of **44 GB / 53,016 `.jsonl` files / 1.50M indexed rows** (`3.5 GB` SQLite index, measured 2026-10-19), incremental updates take **0.6s–6.0s** by reading only newly appended bytes from `(mtime, size, offset, ino)` and avoiding full-table FTS scans via `message_refs(path, mid)`.
3. **High-signal tool & envelope extraction**: Indexes `Read`, `Edit`, `Write`, `NotebookEdit` file paths, `Bash` commands, `Grep`/`Glob` patterns, `Skill` invocations, and `Agent`/`SendMessage` prompts while skipping empty tool shells and stripping expanded skill prompt bodies (`Base directory for this skill:`) and `<system-reminder>` noise.
4. **Unified cross-agent event stream (`ccsi events`)**: Streams normalized JSONL events across Claude Code, Codex, and Pi (`vendor`, `session`, `path`, `ts`, `cwd`, `role`, `kind`, `tool`, `model`, `text`) for cross-agent auditing without writing three separate parsers.

| Vendor | Default Root (override env var) | Transcript Format |
|---|---|---|
| `cc` | `~/.claude/projects/**/*.jsonl` (`$CLAUDE_CONFIG_DIR/projects`) | `type=user/assistant` + `message` |
| `codex` | `~/.codex/sessions/**/rollout-*.jsonl`, `~/.codex/archived_sessions/rollout-*.jsonl` (`$CODEX_HOME`) | `session_meta` / `turn_context` / `response_item` / `event_msg` + `payload` |
| `pi` | `~/.pi/agent/sessions/**/*.jsonl` (`$PI_CODING_AGENT_DIR/sessions`) | `session` / `model_change` / `message` |

## Install

Requires Python 3.9+ linked against **SQLite 3.34.0+** with FTS5 `trigram` support (included in macOS Homebrew Python and standard Linux distributions). No `pip install` needed.

```sh
git clone https://github.com/example-owner/cc-session-index.git
mkdir -p ~/.local/bin
ln -s "$PWD/cc-session-index/ccsi" ~/.local/bin/ccsi
# Ensure ~/.local/bin is in your PATH (e.g. export PATH="$HOME/.local/bin:$PATH")
ccsi index
```

### Wire into Claude Code (`~/.claude/CLAUDE.md`)

Installing the CLI alone is not enough—agents rarely remember to call a tool unless a routing rule points them to it (on the author's setup, agent calls went from **15** in August before adding the rule to **2,569** across September–October / 429 root sessions after adding it). Add this line to your `~/.claude/CLAUDE.md` (or `rules/common/code-search.md`):

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

## Known Limits

- **Trigram minimum length (3 chars)**: FTS5 `trigram` requires at least one token or quoted phrase of `>= 3` characters. Queries with only 1–2 character tokens (or boolean/quoted queries containing `< 3`-char operands) exit with code `2` and an explanation rather than silently returning wrong results. In plain space-separated queries that mix `>= 3`-char and `< 3`-char tokens, `ccsi` automatically filters the `< 3`-char tokens via `LIKE`.
- **Length caps & `tool_result` bodies**: `tool_result` bodies are not indexed in the FTS table (only conversation text and summarized `tool_use` inputs up to 2,000 chars are indexed in `messages`, with message text capped at 8,000 chars in both `messages` and `ccsi events`). For unindexed `tool_result` outputs, use `ccsi events --session <id> --kind tool_result` (up to 8,000 chars per event) or inspect the source `.jsonl` file.
- **Append-only assumption & deleted transcripts**: Incremental indexing assumes existing `.jsonl` files are append-only (`st_ino` unchanged and `st_size` grown) and does not automatically purge rows for `.jsonl` files deleted from disk; remove `index.sqlite` and re-run `ccsi index` for a clean rebuild.

## Tests

```sh
python3 test_ccsi.py -v
```

## License

[MIT](/LICENSE)
