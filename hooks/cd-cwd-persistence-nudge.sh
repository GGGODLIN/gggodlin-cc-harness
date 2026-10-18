#!/bin/bash
# PreToolUse Bash hook — Bash tool cwd 跨 call 持久化提示
# 偵測：相對 cd（`cd subdir`、不含絕對路徑 / subshell）→ 注入提醒
# 設計：取代 CLAUDE.md cwd 規矩（事件級觸發、不增 always-on context tax）
# 提示型：字串比對只認常見入口，認不出來就放行（不提醒）。
# 不評估、不執行 command，也不展開 ~user。
# Disable: touch ~/.claude/hooks/.cd-cwd-disabled
set -uo pipefail

SENTINEL="$HOME/.claude/hooks/.cd-cwd-disabled"
[ -f "$SENTINEL" ] && exit 0

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)

# 只認完整根目錄形狀。~unresolved user 不推論，仍走相對 cd 提醒。
is_home_root_cd() {
  local rest="$1"
  case "$rest" in
    "" | [\;\&\|]*) return 0 ;;
  esac
  case "$rest" in
    [$' \t']*) return 0 ;;
  esac
  return 1
}

cd_target_is_absolute() {
  local target="$1"
  local quote="" inner

  case "$target" in
    \"*) quote='"' ;;
    \'*) quote="'" ;;
  esac
  if [ -n "$quote" ]; then
    inner=${target#?}
    case "$inner" in
      *"$quote"*) target=${inner%%"$quote"*} ;;
      *) return 1 ;;
    esac
  else
    target=${target%%[[:space:]]*}
    target=${target%%\;*}
    target=${target%%\&*}
    target=${target%%\|*}
  fi

  case "$target" in
    /*) return 0 ;;
  esac
  # 引號內的 tilde 不展開；single quote 也讓 HOME 成為字面相對路徑。
  if [ -z "$quote" ]; then
    case "$target" in
      "~"|"~/"*) return 0 ;;
    esac
  fi
  if [ "$quote" != "'" ]; then
    case "$target" in
      '$HOME'|'${HOME}'|'$HOME/'*|'${HOME}/'*) return 0 ;;
    esac
  fi
  return 1
}

# Fast path: 沒命中的全部 exit 0、不延遲一般 Bash call
case "$cmd" in
  "("*) exit 0 ;;          # subshell 已用 `(cd ... && ...)`、不提示
  "cd /"*) exit 0 ;;       # 絕對路徑 cd（含 cd /tmp / cd $HOME 展開後等）
  "cd "*) ;;               # 可能是相對 cd，或尚未展開的家目錄根
  *) exit 0 ;;             # 其他命令、不提示
esac

cd_rest=${cmd#cd }
cd_rest=${cd_rest#"${cd_rest%%[![:space:]]*}"}
if is_home_root_cd "$cd_rest" || cd_target_is_absolute "$cd_rest"; then
  exit 0
fi

MSG="[本機自寫 hook ~/.claude/hooks/cd-cwd-persistence-nudge.sh] 偵測到相對 \`cd <subdir>\`。Bash tool cwd 跨 call 持久化、不會自動回 root —— 後續 Bash 若用 repo-root 相對路徑（特別 \`git add\` / \`git diff\` / \`git restore\`）會 exit 128 路徑重複。預防三選一：(a) subshell 包：\`(cd subdir && cmd)\` 結束自動回原 cwd；(b) 下個 Bash 顯式 \`cd \$REPO_ROOT && ...\`；(c) typecheck/build 類用 \`--project <path>\` flag 取代 \`cd subdir\`。"

jq -n --arg ctx "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$ctx}}'
exit 0
