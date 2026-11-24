#!/bin/bash
# 字串比對型設定解析器：不承諾完整 shell 語意，只認單行 KEY=VALUE 常見入口，認不出來或出現重複／行尾註解就 fail closed（exit 1）；測試與程式寫入請直接傳單純字面值。
set -u

KEY="${1:-}"
FILE="${2:-$(dirname "$0")/../model-routing.env}"

case "$KEY" in
  GEMINI_FLASH_MODEL|GEMINI_FLASH_MAGPIE_MODEL) ;;
  *) exit 2 ;;
esac
[ -f "$FILE" ] || exit 1

COUNT=$(/usr/bin/grep -Ec "^${KEY}=" "$FILE" 2>/dev/null || true)
[ "$COUNT" -eq 1 ] || exit 1

VALUE=$(/usr/bin/grep -E "^${KEY}=" "$FILE" | /usr/bin/cut -d= -f2-)
VALUE="${VALUE#"${VALUE%%[![:space:]]*}"}"
VALUE="${VALUE%"${VALUE##*[![:space:]]}"}"
if [[ ${#VALUE} -ge 2 && "$VALUE" == \"*\" ]]; then
  VALUE="${VALUE:1:${#VALUE}-2}"
elif [[ ${#VALUE} -ge 2 && "$VALUE" == \'*\' ]]; then
  VALUE="${VALUE:1:${#VALUE}-2}"
fi

case "$KEY" in
  GEMINI_FLASH_MODEL)
    [[ "$VALUE" =~ ^gemini-[0-9]+(\.[0-9]+)*-(flash|hydrogen)(-(extra-low|medium|low|high|xhigh))?$ ]] || exit 1
    ;;
  GEMINI_FLASH_MAGPIE_MODEL)
    [[ "$VALUE" =~ ^group/gemini-flash(:(none|minimal|low|medium|high|xhigh|max))?$ ]] || exit 1
    ;;
esac
printf '%s\n' "$VALUE"
