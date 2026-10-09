#!/usr/bin/env bash
# skill-description-gate.test.sh — gate 改動回歸 fixture（2026-07-25 建，配 marker-based suppress）
# 照 gate-authoring checklist #3：known-good / known-bad / 邊界各一，外加 marker 濫用與硬閘不可豁免。
# 用法：bash ~/.claude/hooks/skill-description-gate.test.sh

set -uo pipefail
HOOK="$HOME/.claude/hooks/skill-description-gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

mk() { # mk <name> <body-file-content>
  local d="$TMP/skills/$1"
  mkdir -p "$d"
  cat > "$d/SKILL.md"
  printf '%s/SKILL.md' "$d"
}

run() { # run <path> -> prints "exit|stderr"
  local out rc
  out=$(printf '{"tool_input":{"file_path":"%s"}}' "$1" | bash "$HOOK" 2>&1 >/dev/null)
  rc=$?
  printf '%s\n%s' "$rc" "$out"
}

check() { # check <label> <path> <expect_rc> <expect_substr_or_empty> <forbid_substr_or_empty>
  local label=$1 path=$2 want_rc=$3 want=$4 forbid=$5
  local res rc out
  res=$(run "$path"); rc=${res%%$'\n'*}; out=${res#*$'\n'}
  local ok=1
  [ "$rc" = "$want_rc" ] || ok=0
  [ -n "$want" ] && { printf '%s' "$out" | grep -qF "$want" || ok=0; }
  [ -n "$forbid" ] && { printf '%s' "$out" | grep -qF "$forbid" && ok=0; }
  if [ "$ok" = 1 ]; then
    printf '✅ %s (exit=%s)\n' "$label" "$rc"; pass=$((pass+1))
  else
    printf '❌ %s — exit=%s (want %s)\n   out: %s\n' "$label" "$rc" "$want_rc" "$out"; fail=$((fail+1))
  fi
}

# 1. known-good：觸發場景 + 反向排除都齊 → 放行
GOOD=$(mk good <<'EOF'
---
name: good
description: Use when the user pastes a video URL (YouTube / Bilibili) and wants a summary. Trigger phrases 研究這支影片. Do not use for video editing or subtitle extraction.
---

# Good
EOF
)
check "known-good：描述完整 → 放行" "$GOOD" 0 "" "缺反向排除"

# 2. known-bad：缺反向排除、無 marker → 攔
BAD=$(mk bad <<'EOF'
---
name: bad
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes.
---

# Bad
EOF
)
check "known-bad：缺反向排除且無 marker → 攔" "$BAD" 2 "缺反向排除" ""

# 3. 邊界：同樣缺反向排除，但有合法 marker → 放行
MARKED=$(mk marked <<'EOF'
---
name: marked
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes.
---

# Marked

<!-- desc-audit-suppress: when_not_to_use — 2026-07-10 拍板刻意移除，觸發面對齊 plugin 版避免自我設限 -->
EOF
)
check "邊界：合法 marker 豁免該維度 → 放行" "$MARKED" 0 "" "缺反向排除"

# 4. marker 濫用：理由過短 → 不豁免，且額外提示
SHORT=$(mk shortreason <<'EOF'
---
name: shortreason
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes.
---

# ShortReason

<!-- desc-audit-suppress: when_not_to_use — 不用 -->
EOF
)
check "marker 濫用：理由 <10 字元 → 不豁免" "$SHORT" 2 "marker 缺理由" ""

# 5. 硬性閘不可豁免：marker all 也擋不住 <40 chars
HARD=$(mk hardgate <<'EOF'
---
name: hardgate
description: Does stuff.
---

# HardGate

<!-- desc-audit-suppress: all — 想整支消音，硬閘應該仍然要擋住這個 case -->
EOF
)
check "硬閘：marker all 也不能豁免 <40 chars" "$HARD" 2 "未過硬性閘" ""

# 6. marker 只豁免它明列的 field：另一維度照常報
PARTIAL=$(mk partial <<'EOF'
---
name: partial
description: A toolkit that handles and manages various theme styling operations for artifacts generally.
---

# Partial

<!-- desc-audit-suppress: when_not_to_use — 這支只豁免反向排除，觸發場景維度應該照常被報出來 -->
EOF
)
check "marker 只豁免明列 field：觸發場景照常報" "$PARTIAL" 2 "缺具體觸發場景" "缺反向排除"

printf '\n%s\n' "----"
if [ "$fail" -eq 0 ]; then printf '🎉 ALL PASS (%d)\n' "$pass"; exit 0; fi
printf '💥 %d pass / %d fail\n' "$pass" "$fail"; exit 1
