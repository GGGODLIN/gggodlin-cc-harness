#!/bin/bash
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:~/.local/bin"
export PATH

REPO_DIR="$HOME/code/social-info"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="$REPO_DIR/logs"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="${PATH_ROT_OUT:-$OUT_DIR/$DATE-path-rot.md}"
LOG="$LOG_DIR/local-analysis-path-rot-$DATE.log"
CLAUDE_ROOT="${PATH_ROT_CLAUDE_ROOT:-$HOME/.claude}"
WHITELIST="${PATH_ROT_WHITELIST:-$REPO_DIR/scripts/local-analysis/path-rot-whitelist.txt}"
mkdir -p "$OUT_DIR" "$LOG_DIR"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

log "═══ claude path rot check ($DATE) root=$CLAUDE_ROOT ═══"

RESULT=$(python3 - "$CLAUDE_ROOT" "$WHITELIST" <<'PY'
import os, re, sys, glob, json

root, whitelist_path = sys.argv[1], sys.argv[2]
home = os.path.expanduser("~")

scan_files = [os.path.join(root, "CLAUDE.md")]
for pat in ("rules/**/*.md", "skills/*/SKILL.md", "commands/*.md", "agents/*.md", "references/*.md"):
    scan_files += glob.glob(os.path.join(root, pat), recursive=True)
scan_files = [f for f in scan_files if os.path.isfile(f)]

whitelist = set()
if os.path.isfile(whitelist_path):
    for line in open(whitelist_path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#"):
            whitelist.add(line)

path_re = re.compile(r"(?:~|\$HOME|" + re.escape(home) + r")/\.claude(?:-max|-team)?/[A-Za-z0-9_./\-]+")
skip_chars = set("*{}<>$?[]")
placeholder_re = re.compile(r"(YYYY|/foo\b|/foo/|abc123|entity-X|[-_]$)")
runtime_prefixes = ("state/", "cache/", "sessions/", "review-zh/", "logs/", "explain-diffs/")
broken, checked, seen = [], 0, set()

def is_runtime(rel):
    return any(rel.startswith(p) for p in runtime_prefixes)

for f in scan_files:
    try:
        text = open(f, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    for lineno, line in enumerate(text.split("\n"), 1):
        for m in path_re.finditer(line):
            raw = m.group(0).rstrip(".,;:)")
            if any(c in raw for c in skip_chars) or placeholder_re.search(raw):
                continue
            if raw.endswith("/"):
                continue
            rel = re.sub(r"^.*?/\.claude(?:-max|-team)?/", "", raw)
            if is_runtime(rel) or rel.endswith("-state.json"):
                continue
            key = (f, raw)
            if key in seen:
                continue
            seen.add(key)
            if raw in whitelist:
                continue
            variant = re.match(r"^.*?/(\.claude(?:-max|-team)?)/", raw).group(1)
            resolved = os.path.join(root, rel) if variant == ".claude" else os.path.join(home, variant, rel)
            checked += 1
            if not os.path.exists(resolved):
                broken.append((os.path.relpath(f, root), lineno, raw))

print(json.dumps({"files": len(scan_files), "checked": checked, "broken": broken}, ensure_ascii=False))
PY
)

FILES=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["files"])')
CHECKED=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["checked"])')
BROKEN_COUNT=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["broken"]))')

if [ "$BROKEN_COUNT" -eq 0 ]; then
  printf '__SILENT__' > "$OUT"
  log "done. files=$FILES checked=$CHECKED broken=0 → __SILENT__"
  exit 0
fi

{
  echo "# Claude path rot report ($DATE)"
  echo ""
  echo "**目標**：\`CLAUDE.md\` / \`rules/\` / \`skills/*/SKILL.md\` / \`commands/\` / \`agents/\` / \`references/\` 內以 \`~/.claude/\` 或絕對路徑寫死的檔案引用，逐一驗證仍存在。只報告不修改；含 glob／變數的路徑跳過；白名單：\`$WHITELIST\`。"
  echo ""
  echo "## 結果"
  echo ""
  echo "- 掃描檔案：${FILES}"
  echo "- 檢查路徑（去重）：${CHECKED}"
  echo "- 失效：**${BROKEN_COUNT}**"
  echo ""
  echo "## 失效清單（file:line → 路徑）"
  echo ""
  printf '%s' "$RESULT" | python3 -c '
import json, sys
for f, ln, p in json.load(sys.stdin)["broken"]:
    print(f"- `{f}:{ln}` → `{p}`")'
  echo ""
  echo "處置：改名／搬移就更新引用；刻意保留的範例路徑加進白名單（一行一路徑，原文形式）。"
} > "$OUT"

log "done. files=$FILES checked=$CHECKED broken=$BROKEN_COUNT report=$OUT"
