# cc-session-index (`ccsi`)

English | [繁體中文](/README.zh-TW.md)

Index your local **Claude Code**, **Codex**, and **Pi** `.jsonl` session transcripts into SQLite FTS5 (`tokenize='trigram'`), and stream normalized events across all three tools from a single standard-library Python script.

https://github.com/user-attachments/assets/66ce4fa8-bc2b-47f8-8938-64a539314320

The conversation in the video is made up. The 0.05 s is the same search run on the author's real index (2026-10-20, including Python startup).

Once a transcript folder grows past a few tens of gigabytes, `grep -r` across `.jsonl` files takes too long for an agent to run mid-turn. Most session-memory tools either use SQLite's default `unicode61` tokenizer, which cannot match Chinese, Japanese, or Korean substrings, or pin an English-only embedding model.

On the author's machine (measured 2026-11-19), `index.sqlite` went from `17.2 GB` in v2 (`6,327,719` indexed rows) to `3.09 GB` in v3 (`2,176,258` rows across `70,212` files). Before the upgrade, the v2 `files` table held `207,509` paths for about `70,000` actual `.jsonl` files. Most entries were duplicate paths from different config directories or paths to deleted files. In v3, `dbstat` attributed `2.888 GB` to the trigram index, `0.107 GB` to `message_refs`, and about `0.1 GB` to the remaining tables combined. A full rebuild scanned `70,202` files in `466.8 s`. Incremental updates took about `2 s`.

## How it works

1. `ccsi index` walks the transcript roots for Claude Code, Codex, and Pi. It stores `(mtime, size, offset, ino, rows)` per file. If a file grows with the same inode and has a saved offset, `ccsi` reads only the appended bytes. If the trailing JSON record is incomplete, the cursor stays at its start until the next run. If a Claude Code config directory's `projects` is a symlink, `ccsi` follows that link, so config directories pointing at the same transcript root share one set of entries in the same index.
2. The FTS5 `messages` table indexes text with `tokenize='trigram'`, `content=''`, and `contentless_delete=1`. It stores no copy of the message text. `paths` stores each file path once, and `message_refs` records the file ID, the row's ordinal in that file, its timestamp, and its role.
3. The extractor keeps conversation text and summarizes searchable tool arguments such as file paths, shell commands, search patterns, skill names and arguments, and agent prompts. It skips tool calls without searchable text, expanded skill bodies, and most `<system-reminder>` blocks. It keeps slash commands and the summary and result from task notifications.
4. `ccsi search` re-reads each candidate `.jsonl` file once and runs the same extractor used to build the index. It puts the reconstructed hit text in a temporary in-memory FTS5 table and calls SQLite's `snippet()`, producing the same excerpt as v2 for the same text and query.
5. `ccsi events` reads the same transcripts and emits one normalized JSONL object per event so you can query all three tools with `jq`.

| Vendor | Default Root (override env var) | Transcript Format |
|---|---|---|
| `cc` | `~/.claude/projects/**/*.jsonl` (`$CLAUDE_CONFIG_DIR/projects`, excluding the mirrored `codex/` subtree) | `type=user/assistant` + `message` |
| `codex` | `~/.codex/sessions/**/*.jsonl`, `~/.codex/archived_sessions/**/*.jsonl` (`$CODEX_HOME`) | `session_meta` / `turn_context` / `response_item` + `payload` |
| `pi` | `~/.pi/agent/sessions/**/*.jsonl` (`$PI_CODING_AGENT_DIR/sessions`) | `session` / `model_change` / `message` |

## Install

Requires Python 3.9+ linked against **SQLite 3.43+** with FTS5 `trigram` support. The index uses `contentless_delete`, which requires SQLite 3.43 or newer. No `pip install` needed.

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
- **Session history search** (how we solved X before, why an approach was dropped, which session made a decision) → `ccsi search "<query>" -k 5` (add `-C 2` for surrounding messages from the same transcript, `--exclude-session <UUID-prefix>` to skip the current session, `--vendor {cc,codex,pi}` to filter). SQLite FTS5 `trigram` needs at least one token or quoted phrase of 3 or more characters (e.g. `ccsi search '"測試 假綠"'`). Run `ccsi index` if recent messages are missing from search, and split uncertain multi-concept queries into separate searches. For unindexed `tool_result` outputs, use `ccsi events --session <id>` (8,000 characters per event) or read the original transcript.
```

## Usage

```sh
ccsi index                                          # Build or incrementally update index (all vendors)
ccsi index --vendor codex                           # Index only a specific vendor (cc / codex / pi)

ccsi search "query string" -k 10                    # Full-text search (top 10 hits, 64-trigram snippet)
ccsi search "Herdr 左下角 狀態" -C 2                 # Show up to 2 messages on each side of the hit from the same file
ccsi search '"測試 假綠"' -k 5                       # Pass literal quotes to FTS5 for a phrase of 2-char CJK words
ccsi search "advisor.md" --exclude-session 94c245bb # Exclude current session by UUID/path substring
ccsi search "pineedle" --vendor pi                  # Restrict search to one vendor

ccsi events --vendor codex --since 2026-09-13 --kind tool_call --tool spawn_agent
ccsi events --session 97ac80ca --kind text
```

`events` emits `vendor`, `session`, `path`, `ts`, `cwd`, `role`, `kind`, `text` (up to 8,000 characters), and `model`, with `tool` on applicable events. Claude Code adds `agent_type` and `agent_model` for `Agent` calls and `skill` for `Skill` calls. Codex adds `effort`, the subagent's `agent_role` from `session_meta`, and `agent_type` for `spawn_agent`. Codex takes the model from `turn_context` and carries it forward to later events.

### Storage & Environment Variables

- Default index location (created with `0700` directory and `0600` file permissions):
  - macOS: `~/Library/Caches/cc-session-index/index.sqlite`
  - Linux / other: `${XDG_CACHE_HOME:-~/.cache}/cc-session-index/index.sqlite` (absolute `XDG_CACHE_HOME` only)
  - Override: set `CCSI_DB_DIR=/custom/path`
- `ccsi index` holds an exclusive `flock` on `<DB_DIR>/index.lock`. If the schema or text extractor version changes, run `ccsi index` without `--vendor` to rebuild from all configured sources. It builds the replacement in the same directory and atomically swaps it in under the lock. Searches can still use the old index during the rebuild.

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

- FTS5 `trigram` needs at least one token or quoted phrase of 3 or more characters. Short-only queries and queries that use FTS syntax with a short operand exit with code `2`. For plain space-separated queries that mix long and short tokens, FTS5 matches the long tokens and returns candidates in rank order. `ccsi` re-derives each candidate's text and checks in Python that it contains every short token, continuing until it fills the requested result count or runs out of candidates.
- In v3, `text` is the only FTS column. FTS column filters such as `path:` and `role:` are unsupported. Use `--vendor` to limit the source or `--exclude-session` to exclude a session by path substring.
- The index covers up to 8,000 characters per conversation text row and 2,000 per tool call summary. To see unindexed `tool_result` outputs, run `ccsi events --session <id> --kind tool_result` (up to 8,000 characters per event) or open the `.jsonl` file.
- On incremental runs, `ccsi index` removes entries for files confirmed deleted within the scan scope. If an entire source root is missing, its entries stay in the index.
- When an original file is missing, unreadable, smaller than when indexed, or has a different inode, search skips its hits and takes the next eligible ranked candidates if available. `-C` reads neighboring rows from the source file, so newly appended rows can appear in context before `ccsi index` makes them searchable.

## Tests

```sh
python3 test_ccsi.py -v
```

## License

[MIT](/LICENSE)
