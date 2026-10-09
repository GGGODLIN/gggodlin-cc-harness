#!/usr/bin/env bash
payload=$(cat 2>/dev/null) || exit 0
command -v jq >/dev/null 2>&1 || exit 0
fp=$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
[ -n "$fp" ] || exit 0
case "$fp" in
  */SKILL.md) ;;
  *) exit 0 ;;
esac
case "$fp" in
  */skills/*) ;;
  *) exit 0 ;;
esac
[ -f "$fp" ] || exit 0

desc_raw=$(awk '
  /^---[[:space:]]*$/ { fm++; if (fm==2) exit; next }
  fm==1 {
    if (cap==1) {
      if ($0 ~ /^[A-Za-z_][A-Za-z0-9_]*:[[:space:]]*/) { cap=0 }
      else { s=$0; sub(/^[[:space:]]+/,"",s); acc=acc " " s; next }
    }
    if (cap==0 && $0 ~ /^description:[[:space:]]*/) {
      v=$0; sub(/^description:[[:space:]]*/,"",v)
      if (v=="" || v ~ /^[|>][-+]?[[:space:]]*$/) { cap=1; acc="" }
      else { acc=v }
    }
  }
  END { print acc }
' "$fp" 2>/dev/null)

desc=$(printf '%s' "$desc_raw" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")
len=${#desc}

if [ -z "$desc" ] || [ "$len" -lt 40 ]; then
  printf 'SKILL.md description 未過硬性閘 (%s)：description 缺失或過短 (%s chars)。skill 靠 description 語意比對觸發，這長度保證觸發不了。寫法：Use when <具體場景> + 使用者真會打的關鍵詞 + 反向排除 (Do not use for…)。請補後重存。\n' "$fp" "$len" >&2
  exit 2
fi

# marker-based suppress（2026-07-25 加）：body 前 15 行的
#   <!-- desc-audit-suppress: <field>[,<field>] — <理由> -->
# 讓「已與使用者拍板的刻意留白」不再每次存檔重報。只豁免軟性建議，硬性閘（缺失 / <40 chars）永不豁免。
# 理由段 <10 字元視為格式合規但意圖不合規 → 不豁免、另行提示。
marker=$(awk '
  /^---[[:space:]]*$/ { fm++; if (fm==2) { body=1 }; next }
  body==1 { n++; if (n>15) exit; print }
' "$fp" 2>/dev/null | grep -oE '<!--[[:space:]]*desc-audit-suppress:[^>]*-->' | head -1)

sup_fields=""
if [ -n "$marker" ]; then
  sup_fields=$(printf '%s' "$marker" | grep -oE 'desc-audit-suppress:[[:space:]]*[a-z_,]+' | sed -E 's/.*:[[:space:]]*//')
  reason=$(printf '%s' "$marker" | sed -E 's/.*desc-audit-suppress:[[:space:]]*[a-z_,]+[[:space:]]*//; s/[[:space:]]*-->[[:space:]]*$//; s/^[—-][[:space:]]*//')
  if [ "${#reason}" -lt 10 ]; then
    sup_fields=""
    bad_marker=1
  fi
fi

suppressed() {
  case ",${sup_fields}," in
    *",all,"*|*",$1,"*) return 0 ;;
    *) return 1 ;;
  esac
}

warn=""
suppressed when_to_use || printf '%s' "$desc" | grep -qiE 'use (this|when)|use this skill|when (the )?user|用於|當[^，。]*時|觸發|trigger' || warn="${warn}\n- 缺具體觸發場景語式 (Use when… / 用於…)：抽象能力名詞堆疊語意比對不到"
suppressed when_not_to_use || printf '%s' "$desc" | grep -qiE "do not use|don'?t use|not for|skip (when|if)|use .* instead|不要用|不適用|避免|除非|except when|rather than" || warn="${warn}\n- 缺反向排除 (Do not use for… / 不要用在…)：最高槓桿，補了顯著降誤觸發、提升該觸發時命中"
if [ "$len" -gt 600 ] && ! suppressed length; then
  warn="${warn}\n- description >600 chars (${len})：疑灌水或多意圖，精簡或拆 skill"
fi
[ -n "${bad_marker:-}" ] && warn="${warn}\n- desc-audit-suppress marker 缺理由（理由需 ≥10 字元說明為何刻意留白）：本次不豁免"

if [ -n "$warn" ]; then
  printf 'SKILL.md description 軟性建議 (%s)，請改進或明說此 case 為何不需要、勿靜默略過：%b\n' "$fp" "$warn" >&2
  exit 2
fi
exit 0
