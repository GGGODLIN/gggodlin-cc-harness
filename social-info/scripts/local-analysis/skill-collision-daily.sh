#!/bin/bash
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:~/.local/bin:/opt/homebrew/bin"
export PATH

REPO_DIR="$HOME/code/social-info"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="$REPO_DIR/logs"
CHECKER="${SKILL_COLLISION_CHECKER:-$HOME/.claude/scripts/skill-collision-check.js}"
BASELINE="${SKILL_COLLISION_BASELINE:-$OUT_DIR/.skill-collision-baseline}"

mkdir -p "$OUT_DIR" "$LOG_DIR"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="${SKILL_COLLISION_OUT:-$OUT_DIR/$DATE-skill-collision.md}"
LOG="${SKILL_COLLISION_LOG:-$LOG_DIR/local-analysis-skill-collision-$DATE.log}"

{
  echo "=== skill-collision daily started: $(date) ==="

  CURRENT=$(mktemp)
  CURRENT_KEYS=$(mktemp)
  BASELINE_KEYS=$(mktemp)
  trap 'rc=$?; rm -f "$CURRENT" "$CURRENT_KEYS" "$BASELINE_KEYS"; exit $rc' EXIT
  if [ -n "${SKILL_COLLISION_CURRENT_INPUT:-}" ]; then
    sort "$SKILL_COLLISION_CURRENT_INPUT" > "$CURRENT"
  else
    node "$CHECKER" --pairs-only | sort > "$CURRENT"
  fi
  cut -d'|' -f1-2 "$CURRENT" | sort -u > "$CURRENT_KEYS"

  if [ ! -f "$BASELINE" ]; then
    cp "$CURRENT" "$BASELINE"
    {
      echo "# Skill collision baseline 建立 — $DATE"
      echo ""
      echo "首跑，已存 baseline（$(wc -l < "$CURRENT" | tr -d ' ') pair）。全量清單："
      echo ""
      node "$CHECKER"
    } > "$OUT"
    echo "baseline created"
    exit 0
  fi

  cut -d'|' -f1-2 "$BASELINE" | sort -u > "$BASELINE_KEYS"
  NEW_PAIR_KEYS=$(comm -13 "$BASELINE_KEYS" "$CURRENT_KEYS" || true)
  RESOLVED_PAIR_KEYS=$(comm -23 "$BASELINE_KEYS" "$CURRENT_KEYS" || true)
  SEVERITY_CHANGES=$(awk -F'|' 'NR==FNR { previous[$1 FS $2]=$3; next } { key=$1 FS $2; if (key in previous && (previous[key] >= 0.75) != ($3 >= 0.75)) print $1 FS $2 FS previous[key] FS $3 }' "$BASELINE" "$CURRENT")

  if [ -z "$NEW_PAIR_KEYS" ] && [ -z "$RESOLVED_PAIR_KEYS" ] && [ -z "$SEVERITY_CHANGES" ]; then
    cp "$CURRENT" "$BASELINE"
    printf '__SILENT__' > "$OUT"
    echo "no actionable delta vs baseline, __SILENT__"
  else
    {
      echo "# Skill description 碰撞變化 — $DATE"
      echo ""
      if [ -n "$NEW_PAIR_KEYS" ]; then
        echo "## ⚠️ 新出現的相似 pair（skill 路由擇一衝突候選）"
        echo ""
        printf '%s\n' "$NEW_PAIR_KEYS" | awk -F'|' 'NR==FNR { score[$1 FS $2]=$3; next } NF >= 2 { printf "- %s ↔ %s（%.0f%%）\n", $1, $2, score[$1 FS $2]*100 }' "$CURRENT" -
        echo ""
        echo "處置：檢查兩者 description 的觸發面是否真的互搶；是 → 補反向排除或收窄措辭。"
        echo ""
      fi
      if [ -n "$SEVERITY_CHANGES" ]; then
        echo "## ⚠️ 相似度跨級"
        echo ""
        printf '%s\n' "$SEVERITY_CHANGES" | awk -F'|' '{ old_level=$3 >= 0.75 ? "collision" : "overlap"; new_level=$4 >= 0.75 ? "collision" : "overlap"; printf "- %s ↔ %s：%s %.0f%% → %s %.0f%%\n", $1, $2, old_level, $3*100, new_level, $4*100 }'
        echo ""
      fi
      if [ -n "$RESOLVED_PAIR_KEYS" ]; then
        echo "## ✅ 已解除的 pair"
        echo ""
        printf '%s\n' "$RESOLVED_PAIR_KEYS" | awk -F'|' 'NF >= 2 { printf "- %s ↔ %s\n", $1, $2 }'
        echo ""
      fi
    } > "$OUT"
    cp "$CURRENT" "$BASELINE"
    echo "delta reported: new=$(printf '%s\n' "$NEW_PAIR_KEYS" | grep -c . || true) severity=$(printf '%s\n' "$SEVERITY_CHANGES" | grep -c . || true) resolved=$(printf '%s\n' "$RESOLVED_PAIR_KEYS" | grep -c . || true)"
  fi
} >> "$LOG" 2>&1
