#!/bin/bash
set -euo pipefail

src="$0"
while [ -L "$src" ]; do
  dir="$(cd -P "$(dirname "$src")" && pwd)"
  src="$(readlink "$src")"
  case "$src" in
    /*) ;;
    *) src="$dir/$src" ;;
  esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$src")" && pwd)"

cd /

PATH="${PATH:+$PATH:}/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$HOME/.local/bin:~/.nvm/versions/node/v24.8.0/bin"
export PATH

REPO_DIR="${SKILL_DOCTOR_REPO_DIR:-~/code/social-info}"
OUT_DIR="${SKILL_DOCTOR_OUT_DIR:-$REPO_DIR/reports/local-analysis}"
LOG_DIR="${SKILL_DOCTOR_LOG_DIR:-$REPO_DIR/logs}"

mkdir -p "$OUT_DIR" "$LOG_DIR"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="$OUT_DIR/$DATE-skill-doctor.md"
LOG="$LOG_DIR/local-analysis-skill-doctor-$DATE.log"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

log "═══ skill-doctor weekly-scan start ($DATE) ═══"

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SKILLS_ROOT="${SKILL_DOCTOR_SKILLS_ROOT:-$CLAUDE_DIR/skills}"
PREPASS_FINDINGS=()

# inline-code 路徑檢查的 suppress 名單：教學型 meta-skill 的 `scripts/...` 多為假想示例
# （2026-07-19 加：skill-creator 12 條示例路徑連續誤報；2026-10-27 補 software-factory；markdown link 形式不 suppress 照查）
INLINE_REF_SUPPRESS=("skill-creator" "software-factory")

extract_ref_paths() {
  local file="$1"
  local skill="$2"
  local skill_dir
  skill_dir="$(dirname "$file")"
  # 保留完整路徑（含空白與 #fragment/?query）交由存在性檢查先測完整路徑再 fallback；排除含 glob (*) 或佔位符 (<...>) 的模式
  grep -oE '\]\((references|scripts|assets)/[^)]+\)' "$file" 2>/dev/null | sed -E 's/^\]\(//; s/\)$//' | grep -vE '[*<>]' || true
  local suppressed
  for suppressed in "${INLINE_REF_SUPPRESS[@]}"; do
    [ "$skill" = "$suppressed" ] && return 0
  done
  while IFS= read -r inline_ref; do
    [ -n "$inline_ref" ] || continue
    # 若 skill 自身不含 scripts/ 目錄，或該 skill 是針對特定專案 repo 的操作指南（含 ~/Desktop/projects/），正文的 inline `scripts/...` 可指目標專案腳本
    if [[ "$inline_ref" == scripts/* ]] && { [ ! -d "$skill_dir/scripts" ] || grep -q "Desktop/projects/" "$file" 2>/dev/null; }; then
      continue
    fi
    printf '%s\n' "$inline_ref"
  done < <(grep -oE '`(references|scripts|assets)/[^`]+`' "$file" 2>/dev/null | sed -E 's/^`//; s/`$//' | grep -vE '[*<>]' || true)
}

if [ -d "$SKILLS_ROOT" ]; then
  for skill_md in "$SKILLS_ROOT"/*/SKILL.md; do
    [ -f "$skill_md" ] || continue
    skill_dir="$(dirname "$skill_md")"
    skill_name="$(basename "$skill_dir")"

    while IFS= read -r ref_path; do
      [ -n "$ref_path" ] || continue
      clean_ref="${ref_path%%[#?]*}"
      if [ -e "$skill_dir/$clean_ref" ] || [ -e "$CLAUDE_DIR/vendor/$skill_name/$skill_name/$clean_ref" ]; then
        continue
      fi
      head_ref="${clean_ref%% *}"
      if [ "$head_ref" != "$clean_ref" ] && { [ -e "$skill_dir/$head_ref" ] || [ -e "$CLAUDE_DIR/vendor/$skill_name/$skill_name/$head_ref" ]; }; then
        continue
      fi
      PREPASS_FINDINGS+=("$skill_name/SKILL.md: dead link '$head_ref' not found")
    done < <(extract_ref_paths "$skill_md" "$skill_name")

    fm_meta="$(LC_ALL=C awk '
      function ltrim(s) { sub(/^[ \t\n]+/, "", s); return s }
      function rtrim(s) { sub(/[ \t\n]+$/, "", s); return s }
      function trim(s) { return rtrim(ltrim(s)) }
      function unquote(s,    n, c1, c2) {
        n = length(s)
        if (n >= 2) {
          c1 = substr(s, 1, 1)
          c2 = substr(s, n, 1)
          if ((c1 == "\"" && c2 == "\"") || (c1 == "\047" && c2 == "\047")) {
            return substr(s, 2, n - 2)
          }
        }
        return s
      }
      function finalize_key(k,    i, n, line, out, min_ind, ind, tmp, para) {
        if (k == "") return ""
        n = line_count[k] + 0
        if (n == 0) return ""
        if (key_mode[k] == "plain") {
          out = ""
          for (i = 1; i <= n; i++) {
            tmp = trim(key_lines[k, i])
            if (tmp != "") {
              out = (out == "" ? tmp : out " " tmp)
            }
          }
          return trim(unquote(trim(out)))
        }
        min_ind = -1
        for (i = 1; i <= n; i++) {
          line = key_lines[k, i]
          tmp = line
          gsub(/^[ \t]+/, "", tmp)
          if (tmp != "") {
            match(line, /^[ \t]*/)
            ind = RLENGTH
            if (min_ind < 0 || ind < min_ind) min_ind = ind
          }
        }
        if (min_ind < 0) min_ind = 0
        if (key_mode[k] == "literal") {
          out = ""
          for (i = 1; i <= n; i++) {
            line = key_lines[k, i]
            tmp = (length(line) >= min_ind ? substr(line, min_ind + 1) : "")
            out = (i == 1 ? tmp : out "\n" tmp)
          }
          return trim(out)
        }
        out = ""
        para = ""
        for (i = 1; i <= n; i++) {
          line = key_lines[k, i]
          tmp = trim(length(line) >= min_ind ? substr(line, min_ind + 1) : "")
          if (tmp == "") {
            if (para != "") {
              out = (out == "" ? para : out "\n" para)
              para = ""
            }
          } else {
            para = (para == "" ? tmp : para " " tmp)
          }
        }
        if (para != "") out = (out == "" ? para : out "\n" para)
        return trim(out)
      }
      NR == 1 {
        if (substr($0, 1, 3) == sprintf("%c%c%c", 239, 187, 191)) {
          $0 = substr($0, 4)
        }
      }
      {
        sub(/\r$/, "")
      }
      NR == 1 {
        if ($0 !~ /^---[ \t]*$/) {
          bad_open = 1
          exit
        }
        infm = 1
        next
      }
      infm && $0 ~ /^---[ \t]*$/ {
        closed = 1
        exit
      }
      infm {
        if ($0 ~ /^[A-Za-z_][A-Za-z0-9_-]*:([ \t]+.*|[ \t]*)$/) {
          c = index($0, ":")
          key = substr($0, 1, c - 1)
          val = substr($0, c + 1)
          sub(/^[ \t]+/, "", val)
          sub(/[ \t]+$/, "", val)
          cur = key
          line_count[cur] = 0
          if (val ~ /^[|>]([+-]?[0-9]*|[0-9]*[+-]?)([ \t]+#.*)?$/) {
            key_mode[cur] = (substr(val, 1, 1) == "|" ? "literal" : "folded")
          } else {
            key_mode[cur] = "plain"
            if (val != "") {
              line_count[cur] = 1
              key_lines[cur, 1] = val
            }
          }
        } else if (cur != "") {
          if (key_mode[cur] == "plain" && $0 ~ /^[ \t]*#/) next
          line_count[cur]++
          key_lines[cur, line_count[cur]] = $0
        }
      }
      END {
        if (bad_open || !closed) {
          printf "HASNAME=0 HASDESC=0\n"
          exit
        }
        nm = finalize_key("name")
        ds = finalize_key("description")
        printf "HASNAME=%d HASDESC=%d\n%s", (nm != "" ? 1 : 0), (ds != "" ? 1 : 0), ds
      }
    ' "$skill_md")"

    fm_header="${fm_meta%%$'\n'*}"
    if [ "$fm_meta" = "$fm_header" ]; then
      fm_desc=""
    else
      fm_desc="${fm_meta#*$'\n'}"
    fi

    hasname=0
    hasdesc=0
    case "$fm_header" in
      *HASNAME=1*) hasname=1 ;;
    esac
    case "$fm_header" in
      *HASDESC=1*) hasdesc=1 ;;
    esac
    if [ "$hasdesc" = "1" ] && [ -n "$fm_desc" ]; then
      desclen="$(printf '%s' "$fm_desc" | LC_ALL=en_US.UTF-8 wc -m | tr -d '[:space:]')"
    else
      desclen=0
    fi

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

TMP_OUT="$(mktemp "${OUT}.tmp.XXXXXX")"
TMP_NODE_OUT="$(mktemp "${OUT}.node.tmp.XXXXXX")"
cleanup() {
  rm -f "${TMP_OUT:-}" "${TMP_NODE_OUT:-}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

rc=0
node --experimental-strip-types "$SCRIPT_DIR/skill-doctor.ts" > "$TMP_NODE_OUT" 2>>"$LOG" || rc=$?
if [ "$rc" -ne 0 ]; then
  log "ERROR: skill-doctor.ts exited with $rc"
  exit "$rc"
fi
if [ ! -s "$TMP_NODE_OUT" ]; then
  log "ERROR: skill-doctor.ts produced empty output"
  exit 1
fi

{
  if [ "${#PREPASS_FINDINGS[@]}" -gt 0 ]; then
    echo "## Deterministic pre-pass findings"
    echo
    for finding in "${PREPASS_FINDINGS[@]}"; do
      echo "- $finding"
    done
    echo
  fi
  cat "$TMP_NODE_OUT"
} > "$TMP_OUT"

mv "$TMP_OUT" "$OUT"
log "report written: $OUT ($(wc -l <"$OUT") lines, $(wc -c <"$OUT") bytes)"
log "═══ skill-doctor weekly-scan done ═══"
