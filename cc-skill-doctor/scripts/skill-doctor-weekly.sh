#!/bin/bash
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:~/.local/bin:~/.nvm/versions/node/v24.8.0/bin"
export PATH

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$HOME/code/social-info"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$OUT_DIR" "$LOG_DIR"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="$OUT_DIR/$DATE-skill-doctor.md"
LOG="$LOG_DIR/local-analysis-skill-doctor-$DATE.log"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

log "═══ skill-doctor weekly-scan start ($DATE) ═══"

SKILLS_ROOT="$HOME/.claude/skills"
PREPASS_FINDINGS=()

# inline-code 路徑檢查的 suppress 名單：教學型 meta-skill 的 `scripts/...` 多為假想示例
# （2026-07-19 加：skill-creator 12 條示例路徑連續誤報；markdown link 形式不 suppress 照查）
INLINE_REF_SUPPRESS=("skill-creator")

extract_ref_paths() {
  local file="$1"
  local skill="$2"
  # 路徑尾的參數 / placeholder（如 `scripts/reconcile.sh <name>`）截掉再查存在
  grep -oE '\]\((references|scripts|assets)/[^)]+\)' "$file" 2>/dev/null | sed -E 's/^\]\(//; s/\)$//; s/ .*$//' || true
  local suppressed
  for suppressed in "${INLINE_REF_SUPPRESS[@]}"; do
    [ "$skill" = "$suppressed" ] && return 0
  done
  grep -oE '`(references|scripts|assets)/[^`]+`' "$file" 2>/dev/null | sed -E 's/^`//; s/`$//; s/ .*$//' || true
}

if [ -d "$SKILLS_ROOT" ]; then
  for skill_md in "$SKILLS_ROOT"/*/SKILL.md; do
    [ -f "$skill_md" ] || continue
    skill_dir="$(dirname "$skill_md")"
    skill_name="$(basename "$skill_dir")"

    while IFS= read -r ref_path; do
      [ -n "$ref_path" ] || continue
      if [ ! -e "$skill_dir/$ref_path" ]; then
        PREPASS_FINDINGS+=("$skill_name/SKILL.md: dead link '$ref_path' not found")
      fi
    done < <(extract_ref_paths "$skill_md" "$skill_name")

    fm_meta="$(awk '
      NR==1 {
        if ($0 != "---") { print "HASNAME=0"; print "HASDESC=0"; print "DESCLEN=0"; printed=1; exit }
        infm=1; next
      }
      infm && $0 == "---" { exit }
      infm {
        if ($0 ~ /^[A-Za-z_][A-Za-z0-9_-]*:/) {
          c = index($0, ":")
          key = substr($0, 1, c-1)
          val = substr($0, c+1)
          sub(/^[ \t]+/, "", val)
          haskeys[key]=1
          buf[key]=val
          cur=key
        } else if (cur != "") {
          buf[cur] = buf[cur] "\n" $0
        }
      }
      END {
        if (!printed) {
          print "HASNAME=" (("name" in haskeys) ? 1 : 0)
          print "HASDESC=" (("description" in haskeys) ? 1 : 0)
          print "DESCLEN=" length(buf["description"])
        }
      }
    ' "$skill_md")"

    hasname=1
    hasdesc=1
    desclen=0
    while IFS= read -r line; do
      case "$line" in
        HASNAME=*) hasname="${line#HASNAME=}" ;;
        HASDESC=*) hasdesc="${line#HASDESC=}" ;;
        DESCLEN=*) desclen="${line#DESCLEN=}" ;;
      esac
    done <<< "$fm_meta"

    if [ "$hasname" = "0" ]; then
      PREPASS_FINDINGS+=("$skill_name/SKILL.md: missing frontmatter field 'name'")
    fi
    # 工具產生檔（gws generate-skills 等）desc 長度不歸本機管——手改會被 regenerate 蓋掉
    # （2026-07-19 加：gws-docs/gws-gmail desc<40 連續誤報）；missing description 仍照報
    is_generated=0
    grep -q "gws generate-skills" "$skill_md" 2>/dev/null && is_generated=1

    if [ "$hasdesc" = "0" ]; then
      PREPASS_FINDINGS+=("$skill_name/SKILL.md: missing frontmatter field 'description'")
    elif [ "$is_generated" = "1" ]; then
      :
    else
      if [ "$desclen" -lt 40 ]; then
        PREPASS_FINDINGS+=("$skill_name/SKILL.md: description length ${desclen} chars (< 40, too short)")
      elif [ "$desclen" -gt 1200 ]; then
        PREPASS_FINDINGS+=("$skill_name/SKILL.md: description length ${desclen} chars (> 1200, too long)")
      fi
    fi
  done
fi

if [ "${#PREPASS_FINDINGS[@]}" -gt 0 ]; then
  log "pre-pass findings: ${#PREPASS_FINDINGS[@]}"
fi

if ! command -v node >/dev/null 2>&1; then
  log "ERROR: node not found in PATH"
  exit 1
fi

if [ "${#PREPASS_FINDINGS[@]}" -gt 0 ]; then
  {
    echo "## Deterministic pre-pass findings"
    echo
    for finding in "${PREPASS_FINDINGS[@]}"; do
      echo "- $finding"
    done
    echo
  } > "$OUT"
  node --experimental-strip-types "$SCRIPT_DIR/skill-doctor.ts" >> "$OUT" 2>>"$LOG"
else
  node --experimental-strip-types "$SCRIPT_DIR/skill-doctor.ts" > "$OUT" 2>>"$LOG"
fi
log "report written: $OUT ($(wc -l <"$OUT") lines, $(wc -c <"$OUT") bytes)"
log "═══ skill-doctor weekly-scan done ═══"
