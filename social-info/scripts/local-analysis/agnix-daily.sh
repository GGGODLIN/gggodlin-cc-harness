#!/bin/bash
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:~/.local/bin:/opt/homebrew/bin"
export PATH

REPO_DIR="$HOME/code/social-info"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="$REPO_DIR/logs"
TARGET="${AGNIX_TARGET:-/Users/you/.claude}"
AGNIX_VERSION="0.37.5"
BASELINE="${AGNIX_BASELINE:-$OUT_DIR/.agnix-baseline}"

mkdir -p "$OUT_DIR" "$LOG_DIR"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="${AGNIX_OUT:-$OUT_DIR/$DATE-agnix.md}"
LOG="${AGNIX_LOG:-$LOG_DIR/local-analysis-agnix-$DATE.log}"
mkdir -p "$(dirname "$OUT")" "$(dirname "$LOG")" "$(dirname "$BASELINE")"

{
  echo "=== agnix daily started: $(date) ==="

  RAW=$(mktemp)
  CURRENT=$(mktemp)
  SUPPRESSED=$(mktemp)
  BASELINE_EFFECTIVE=$(mktemp)
  ERROR=$(mktemp)
  trap 'rc=$?; rm -f "$RAW" "$CURRENT" "$SUPPRESSED" "$BASELINE_EFFECTIVE" "$ERROR"; exit $rc' EXIT

  AGNIX_RC=0
  if [ -n "${AGNIX_JSON_INPUT:-}" ]; then
    cp "$AGNIX_JSON_INPUT" "$RAW"
  else
    cd "$TARGET"
    npm_config_ignore_scripts=false npx -y "agnix@$AGNIX_VERSION" --format json . > "$RAW" 2> "$ERROR" || AGNIX_RC=$?
  fi

  if [ ! -s "$RAW" ]; then
    {
      echo "# agnix config-lint 掃描失敗 — $DATE"
      echo ""
      echo "## 🚨 掃描器未產生可用 JSON"
      echo ""
      echo "npx exit code: ${AGNIX_RC}（agnix 有 finding 時本來就以 1 退出，判失敗只看輸出是否為空）。詳見 ${LOG}。baseline 未更新。"
    } > "$OUT"
    [ ! -s "$ERROR" ] || while IFS= read -r line; do printf '%s\n' "$line"; done < "$ERROR"
    echo "agnix execution failed rc=$AGNIX_RC"
    exit 0
  fi

  if ! python3 - "$RAW" "$SUPPRESSED" <<'PYEOF' | sort > "$CURRENT"
import json, sys
allowed = {
    "Unknown frontmatter field 'upstream'",
    "Unknown frontmatter field 'upstream-path'",
    "Unknown frontmatter field 'upstream-pinned'",
    "Unknown frontmatter field 'upstream-status'",
}
allowed_diagnostics = {
    ("error", "settings.json", "CC-HK-008", "Script file not found at 'SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh' (resolved to '~/SEMBLE_SCOPE_WRAPPER=~/.claude/scripts/semble-route3.sh')"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/domains/dev-replies.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/domains/postmortems.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/domains/release-notes.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/domains/tech-articles.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/domains/tickets.md`' is deeper than one level"),
    ("error", "vendor/sepia/plugin.json", "CC-PL-001", "plugin.json must be located in .claude-plugin/ directory"),
    ("warning", "vendor/sepia/plugin.json", "CC-PL-004", "Missing or invalid recommended field: version"),
    ("warning", "vendor/sepia/skills/sepia-hemingway/SKILL.md", "AS-013", "File reference 'references/voices/hemingway.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/voices/`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/voices/registry.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/languages/zh.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/domains/journalism.md`' is deeper than one level"),
    ("warning", "vendor/sepia/skills/sepia/SKILL.md", "AS-013", "File reference 'references/voices/PERSONA-TEMPLATE.md`' is deeper than one level"),
    ("error", "vendor/sepia/.qwenpaw-plugin/plugin.json", "CC-PL-001", "plugin.json must be located in .claude-plugin/ directory"),
    ("warning", "vendor/sepia/.qwenpaw-plugin/plugin.json", "CC-PL-009", "Invalid author object: 'author.name' must be a non-empty string"),
}
with open(sys.argv[2], "w") as suppressed:
    for level, file, rule, message in sorted(allowed_diagnostics):
        normalized = message.replace('|', '¦').replace('\n', ' ')
        print(f"{level}|{rule}|{file}|{normalized}", file=suppressed)
try:
    d = json.load(open(sys.argv[1]))
except (OSError, json.JSONDecodeError) as exc:
    print(f'agnix JSON parse failed: {exc}', file=sys.stderr)
    raise SystemExit(2)
items = d.get('diagnostics') or d.get('issues') or d.get('results') or []
for i in items:
    f = i['file'].replace('~/.claude/', '')
    message = i['message'].replace('|', '¦').replace('\n', ' ')
    if i['rule'] == 'CC-SK-017' and message in allowed:
        continue
    if (i['level'], f, i['rule'], message) in allowed_diagnostics:
        continue
    print(f"{i['level']}|{i['rule']}|{f}|{message}")
PYEOF
  then
    {
      echo "# agnix config-lint 掃描失敗 — $DATE"
      echo ""
      echo "## 🚨 掃描器輸出不是合法 JSON"
      echo ""
      echo "詳見 ${LOG}。baseline 未更新。"
    } > "$OUT"
    echo "agnix JSON parse failed"
    exit 0
  fi

  if [ ! -f "$BASELINE" ]; then
    cp "$CURRENT" "$BASELINE"
    {
      echo "# agnix config-lint baseline 建立 — $DATE"
      echo ""
      echo "首跑，已存 baseline（$(wc -l < "$CURRENT" | tr -d ' ') 條 finding，噪音規則已由 ~/.claude/.agnix.toml 停用）。全量："
      echo ""
      awk -F'|' '{ printf "- [%s] %s `%s` — %s\n", $1, $2, $3, substr($4, 1, 160) }' "$CURRENT"
    } > "$OUT"
    echo "baseline created"
    exit 0
  fi

  grep -vxF -f "$SUPPRESSED" "$BASELINE" > "$BASELINE_EFFECTIVE" || true
  NEW_FINDINGS=$(comm -13 "$BASELINE_EFFECTIVE" "$CURRENT" || true)
  RESOLVED=$(comm -23 "$BASELINE_EFFECTIVE" "$CURRENT" || true)

  if [ -z "$NEW_FINDINGS" ] && [ -z "$RESOLVED" ]; then
    printf '__SILENT__' > "$OUT"
    echo "no delta vs baseline, __SILENT__"
  else
    {
      echo "# agnix config-lint 變化 — $DATE"
      echo ""
      if [ -n "$NEW_FINDINGS" ]; then
        echo "## ⚠️ 新 finding"
        echo ""
        echo "$NEW_FINDINGS" | awk -F'|' '{ printf "- [%s] %s `%s` — %s\n", $1, $2, $3, substr($4, 1, 160) }'
        echo ""
        echo "處置：error 級先修；warning 級判斷真偽，結構性誤報 → 加進 ~/.claude/.agnix.toml disabled_rules。"
        echo ""
      fi
      if [ -n "$RESOLVED" ]; then
        echo "## ✅ 已解除"
        echo ""
        echo "$RESOLVED" | awk -F'|' '{ printf "- [%s] %s `%s`\n", $1, $2, $3 }'
        echo ""
      fi
    } > "$OUT"
    echo "delta reported: new=$(echo "$NEW_FINDINGS" | grep -c . || true) resolved=$(echo "$RESOLVED" | grep -c . || true)"
  fi
  cp "$CURRENT" "$BASELINE"
} >> "$LOG" 2>&1
