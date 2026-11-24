#!/usr/bin/env bash
# Threat model. This gate stops drift: an honest but forgetful agent that edits
# an agent contract or this gate's own surface and commits it without approval.
# It does NOT stop deliberate evasion -- the agent runs as the same uid, so it
# can write the permit file, delete the sentinel, or commit from a shell this
# hook never sees. Anything that needs a human present is out of reach here, so
# do not describe this as a security boundary.
#
# 只對字面全文含小寫 commit 子串的命令用 Bash AST 區分入口與文字。
# 不執行輸入，不追外部 script、Git alias 或任意變數求值；範圍內不明入口
# 與解析失敗拒絕，不承諾完整 shell 語意或字面沒有 commit 的間接提交。
# 需要既有 Go 與已下載的釘版相依；hook 不下載套件，也不自行升級工具鏈。
#
# 另對字面全文含小寫 merge／pull／rebase 子串的命令做髒工作樹整合攔截：
# 為保護共用 checkout 的未收／暫存／未追蹤檔，髒工作樹只放行單一字面 ref 的
# `git merge --ff-only --no-autostash --no-overwrite-ignore`，且要可快轉、路徑無交集。
# 進行中衝突處置與說明旗標仍豁免（`--continue`、`--abort`、`--quit`、`--skip`、
# `--show-current-patch`、`--help`、`-h`）。只認常見 shell／Git 入口，判不出就拒絕。
# 不承諾完整 shell 語意、外部 script、Git alias 或檢查後的並行變更；ignored 檔交給 Git 保護。
#
# Locked surface lifecycle (see skills/gate-authoring/SKILL.md checklist 1):
#   bootstrap -- until this script exists in HEAD the gate allows and logs, so
#                the commit that introduces it is not blocked by itself.
#   update    -- a commit that stages a locked path needs a permit issued out of
#                band by the user, bound to the exact staged tree and single use:
#                  ! ~/.claude/hooks/agent-contract-gate-permit.sh issue
#   recovery  -- create hooks/.agent-contract-gate-disabled to allow everything,
#                or commit from a terminal outside Claude Code, which this hook
#                never observes. Both leave a trace: the sentinel is a file on
#                disk, the out-of-band commit is in the reflog.
# Every one of those three paths writes a line to logs/agent-contract-gate.jsonl.
#
# Evaluator integrity. 工作樹中的 gate、validator 或 parser 正在修改時，
# 先由 HEAD 的同組檔案接手，不能拿新判讀器配舊 gate，也不能讓壞 parser
# 先跳過保護。沒有能接手的 HEAD 時，staged locked 變更仍然拒絕。
# The decision to hand over is itself made by the dirty copy, so this is a drift
# guard with the same circularity as any self-check -- not stronger.
#
# Consequence for anyone fixing a bug in this gate: the handoff means the HEAD
# copy -- the one that still has the bug -- is what guards the very commit that
# fixes it. So a shape the old copy fails to parse will sail past while you are
# repairing exactly that parsing. On 2026-09-05 the subshell blind spot was
# fixed this way, and the fix only went through a real permit because the author
# deliberately avoided the subshell form when committing; nothing in this script
# forced that. If you are fixing detection here, commit in a shape the HEAD copy
# already handles, and check logs/agent-contract-gate.jsonl afterwards for an
# allow line -- no line at all means the gate never inspected your commit.
#
# Permit binding. A permit records the staged index entries (git ls-files
# --stage lines) of the locked paths, not the whole index tree, so another
# session staging unrelated files does not void it. It is consumed only after the commit passes every
# check; a failed validation leaves it for the retry. It records the session
# that issued it when CLAUDE_CODE_SESSION_ID was set there, and the gate refuses
# it from any other session; a permit issued without a session id binds to none.
set -u
set -o pipefail

# Appended to every "cannot safely inspect" denial so the agent that hit the
# wall sees the way through without having to find the memory note first
# (2026-09-22: 324 such denials in 30 days, most from subagent workers).
INSPECT_HINT='. Fix: in shared checkouts or repos with .claude/ contract changes run git add in a separate call before git commit; pass commit message as a literal -m string, -F <file>, or single-quoted -F - <<'\''EOF'\'' heredoc (no $(...) command substitution, no unquoted heredoc expansion, no eval), with at most one cd and one git -C target (no multi-repo git -C chaining).'

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
VALIDATOR=${AGENT_CONTRACT_GATE_VALIDATOR:-$SCRIPT_DIR/../scripts/agent-contract-validator.mjs}
SENTINEL=${AGENT_CONTRACT_GATE_SENTINEL:-$SCRIPT_DIR/.agent-contract-gate-disabled}
PERMIT_FILE=${AGENT_CONTRACT_GATE_PERMIT:-$SCRIPT_DIR/state/agent-contract-gate-permit}
AUDIT_LOG=${AGENT_CONTRACT_GATE_AUDIT:-$SCRIPT_DIR/../logs/agent-contract-gate.jsonl}

audit() {
  local decision=$1
  local reason=$2
  local detail=${3:-}
  local dir
  dir=$(dirname "$AUDIT_LOG")
  [ -d "$dir" ] || mkdir -p "$dir" 2>/dev/null || return 0
  printf '{"ts":"%s","decision":"%s","reason":"%s","detail":"%s"}\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$decision" "$reason" "$detail" >> "$AUDIT_LOG" 2>/dev/null || true
}

deny() {
  local reason=$1
  if command -v jq >/dev/null 2>&1 && jq -n --arg reason "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'; then
    return 0
  fi
  if command -v node >/dev/null 2>&1 && node --input-type=module -e '
const reason = process.argv[1]
process.stdout.write(JSON.stringify({hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:reason}}))
' "$reason"; then
    return 0
  fi
  printf '%s\n' "$reason" >&2
  return 2
}

PAYLOAD=$(cat) || {
  deny 'agent contract commit gate could not read hook input'
  exit $?
}

# Recovery path. Read the payload first so the caller never sees a broken pipe.
if [ -e "$SENTINEL" ]; then
  audit allow sentinel "$SENTINEL"
  printf 'agent contract commit gate is disabled by %s\n' "$SENTINEL" >&2
  exit 0
fi

json_value() {
  local field=$1
  if command -v jq >/dev/null 2>&1; then
    case "$field" in
      tool_name) printf '%s' "$PAYLOAD" | jq -r '.tool_name // "Bash"' ;;
      command) printf '%s' "$PAYLOAD" | jq -r '.tool_input.command // ""' ;;
      cwd) printf '%s' "$PAYLOAD" | jq -r '.cwd // ""' ;;
      session_id) printf '%s' "$PAYLOAD" | jq -r '.session_id // ""' ;;
      *) return 1 ;;
    esac
    return $?
  fi
  node --input-type=module -e '
import fs from "node:fs"
const payload = JSON.parse(fs.readFileSync(0, "utf8"))
const field = process.argv[1]
const value = field === "tool_name" ? payload.tool_name ?? "Bash" : field === "command" ? payload.tool_input?.command ?? "" : field === "cwd" ? payload.cwd ?? "" : field === "session_id" ? payload.session_id ?? "" : null
if (value === null) process.exit(1)
process.stdout.write(String(value))
' "$field" <<< "$PAYLOAD"
}

if ! TOOL_NAME=$(json_value tool_name 2>/dev/null); then
  deny 'agent contract commit gate could not parse hook input'
  exit $?
fi
[ "$TOOL_NAME" = "Bash" ] || exit 0

if ! COMMAND=$(json_value command 2>/dev/null); then
  deny 'agent contract commit gate could not parse the Bash command'
  exit $?
fi
# 不讓舊 HEAD 的判讀器把範圍外命令誤攔；含 commit 的自身更新仍交 HEAD。
case "$COMMAND" in
  *commit*|*merge*|*pull*|*rebase*) ;;
  *) exit 0 ;;
esac
TMP_BASE=${TMPDIR:-/tmp}
TMP=$(mktemp -d "${TMP_BASE%/}/agent-contract-gate.XXXXXX") || {
  deny 'agent contract commit gate could not create a temporary projection'
  exit $?
}
trap 'rm -r "$TMP"' EXIT

case "$COMMAND" in
  *merge*|*pull*|*rebase*)
    if ! INTEGRATION_BASE_CWD=$(json_value cwd 2>/dev/null); then
      deny 'agent contract gate could not parse the command cwd'
      exit $?
    fi
    [ -n "$INTEGRATION_BASE_CWD" ] || INTEGRATION_BASE_CWD=$(pwd)
    if ! INTEGRATION_BASE_CWD="$INTEGRATION_BASE_CWD" node --input-type=module -e '
import fs from "node:fs"
import path from "node:path"

const payload = JSON.parse(fs.readFileSync(0, "utf8"))
const command = String(payload.tool_input?.command ?? "")
const baseCwd = String(process.env.INTEGRATION_BASE_CWD || payload.cwd || process.cwd())
const home = String(process.env.HOME ?? "")
const envSelector = Boolean(
  process.env.GIT_INDEX_FILE || process.env.GIT_DIR || process.env.GIT_WORK_TREE || process.env.GIT_COMMON_DIR
)

const CONTROL_KEYWORDS = new Set([
  "if", "then", "elif", "else", "fi", "while", "until", "do", "done", "esac", "!", "time", "{", "}"
])
const SELECTOR_NAMES = new Set([
  "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"
])
const EXEMPT_FLAGS = new Set([
  "--continue", "--abort", "--quit", "--skip", "--show-current-patch", "--help", "-h"
])
const VALUE_LONG_OPTS = new Set([
  "--message", "--file", "--strategy", "--strategy-option", "--cleanup", "--into-name",
  "--upload-pack", "--negotiation-tip", "--server-option", "--depth", "--deepen",
  "--shallow-since", "--shallow-exclude", "--jobs", "--onto", "--exec", "--whitespace", "--empty"
])

function isSelectorName(name) {
  return SELECTOR_NAMES.has(name) || name.startsWith("GIT_CONFIG_KEY_") || name.startsWith("GIT_CONFIG_VALUE_")
}

const FF_REQUIRED_FLAGS = ["--ff-only", "--no-autostash", "--no-overwrite-ignore"]
const FF_ALLOWED_FLAGS = new Set([...FF_REQUIRED_FLAGS, "--no-edit", "--quiet", "-q", "--no-stat", "-n"])

function fastForwardTarget(args) {
  const flags = new Set()
  let target = ""
  for (const { value, dynamic, hasGlob, leadingTilde } of args) {
    if (!value || dynamic || hasGlob || leadingTilde) return ""
    if (value.startsWith("-")) {
      if (!FF_ALLOWED_FLAGS.has(value)) return ""
      flags.add(value)
    } else {
      if (target || value.toUpperCase() === "FETCH_HEAD") return ""
      target = value
    }
  }
  return FF_REQUIRED_FLAGS.every(flag => flags.has(flag)) ? target : ""
}

function findMatchingParen(src, openIdx) {
  let depth = 1
  let p = openIdx + 1
  while (p < src.length && depth > 0) {
    const c = src[p]
    if (c === "\\") { p += 2; continue }
    if (c === "\x27") {
      p++
      while (p < src.length && src[p] !== "\x27") p++
      p++
      continue
    }
    if (c === "$" && src[p + 1] === "\x27") {
      p += 2
      while (p < src.length && src[p] !== "\x27") {
        if (src[p] === "\\") p += 2; else p++
      }
      p++
      continue
    }
    if (c === "\"") {
      p++
      while (p < src.length && src[p] !== "\"") {
        if (src[p] === "\\") p += 2
        else if (src[p] === "$" && src[p + 1] === "(") p = findMatchingParen(src, p + 1)
        else p++
      }
      p++
      continue
    }
    if (c === "`") {
      p++
      while (p < src.length && src[p] !== "`") {
        if (src[p] === "\\") p += 2; else p++
      }
      p++
      continue
    }
    if (c === "#" && (p === openIdx + 1 || " \t\r\n;&|(".includes(src[p - 1]))) {
      while (p < src.length && src[p] !== "\n") p++
      continue
    }
    if (c === "(") { depth++; p++; continue }
    if (c === ")") { depth--; p++; continue }
    p++
  }
  return p
}

function readBacktick(src, openIdx) {
  let p = openIdx + 1
  let inner = ""
  while (p < src.length && src[p] !== "`") {
    if (src[p] === "\\" && p + 1 < src.length && "\\$`\n".includes(src[p + 1])) {
      if (src[p + 1] !== "\n") inner += src[p + 1]
      p += 2
      continue
    }
    inner += src[p]
    p++
  }
  if (p < src.length && src[p] === "`") p++
  return { inner, next: p }
}

const findings = []

function resolveDirWord(word, dirState) {
  if (!word || word.dynamic || word.hasGlob || word.value === "" || word.value.startsWith("-")) {
    return { dir: "", dynamic: true }
  }
  let target = word.value
  if (word.leadingTilde) {
    if (target === "~") {
      if (!home) return { dir: "", dynamic: true }
      target = home
    } else if (target.startsWith("~/")) {
      if (!home) return { dir: "", dynamic: true }
      target = home + target.slice(1)
    } else {
      return { dir: "", dynamic: true }
    }
  }
  if (path.isAbsolute(target)) return { dir: target, dynamic: false }
  if (dirState.dynamic || !dirState.dir) return { dir: "", dynamic: true }
  return { dir: path.resolve(dirState.dir, target), dynamic: false }
}

function scanExpansionText(text, dirState, depth) {
  let p = 0
  while (p < text.length) {
    const c = text[p]
    if (c === "\\") { p += 2; continue }
    if (c === "$" && text[p + 1] === "(") {
      if (text[p + 2] === "(") {
        const end = findMatchingParen(text, p + 1)
        scanExpansionText(text.slice(p + 3, Math.max(p + 3, end - 2)), dirState, depth + 1)
        p = end
        continue
      }
      const end = findMatchingParen(text, p + 1)
      scanScript(text.slice(p + 2, Math.max(p + 2, end - 1)), { ...dirState }, depth + 1)
      p = end
      continue
    }
    if (c === "$" && text[p + 1] === "{") {
      let b = 1, q = p + 2
      while (q < text.length && b > 0) {
        if (text[q] === "\\") { q += 2; continue }
        if (text[q] === "{") b++
        else if (text[q] === "}") b--
        q++
      }
      scanExpansionText(text.slice(p + 2, Math.max(p + 2, q - 1)), dirState, depth + 1)
      p = q
      continue
    }
    if (c === "`") {
      const bt = readBacktick(text, p)
      scanScript(bt.inner, { ...dirState }, depth + 1)
      p = bt.next
      continue
    }
    p++
  }
}

function inspectWords(words, dirState, inheritedSelector, depth) {
  if (depth > 8) {
    findings.push({ sub: "merge", kind: "dynamic", dir: "", target: "" })
    return dirState
  }
  let idx = 0
  while (idx < words.length && !words[idx].quoted && !words[idx].dynamic && CONTROL_KEYWORDS.has(words[idx].value)) {
    idx++
  }
  if (idx >= words.length) return dirState
  if (!words[idx].quoted && !words[idx].dynamic && (words[idx].value === "for" || words[idx].value === "case" || words[idx].value === "select")) {
    return dirState
  }
  let localSelector = inheritedSelector
  while (idx < words.length && words[idx].rawAssignName) {
    if (isSelectorName(words[idx].rawAssignName)) localSelector = true
    idx++
  }
  if (idx >= words.length) return dirState

  while (idx < words.length) {
    const exeWord = words[idx]
    if (exeWord.dynamic || exeWord.hasGlob) return dirState
    const exe = path.basename(exeWord.value)
    if (exe === "command" || exe === "builtin" || exe === "exec") {
      idx++
      if (idx < words.length && !words[idx].dynamic) {
        const opt = words[idx].value
        if (exe === "command" && (opt === "-v" || opt === "-V")) return dirState
        if (opt === "--" || (exe === "command" && opt === "-p")) idx++
      }
      continue
    }
    if (exe === "nohup") {
      idx++
      if (idx < words.length && words[idx].value === "--") idx++
      continue
    }
    if (exe === "env") {
      idx++
      while (idx < words.length) {
        const w = words[idx]
        if (w.rawAssignName) {
          if (isSelectorName(w.rawAssignName)) localSelector = true
          idx++
          continue
        }
        if (w.dynamic) return dirState
        if (w.value === "--") { idx++; break }
        if (w.value === "-i" || w.value === "--ignore-environment") { idx++; continue }
        if (w.value === "-u" || w.value === "--unset") { idx += 2; continue }
        if (w.value.startsWith("--unset=")) { idx++; continue }
        if (!w.value.startsWith("-") && w.value.includes("=")) {
          const eqName = w.value.slice(0, w.value.indexOf("="))
          if (isSelectorName(eqName)) localSelector = true
          idx++
          continue
        }
        break
      }
      continue
    }
    if (exe === "cd") {
      let arg = words[idx + 1]
      if (arg && !arg.dynamic && arg.value === "--") arg = words[idx + 2]
      if (!arg) {
        return home ? { dir: home, dynamic: false } : { dir: "", dynamic: true }
      }
      return resolveDirWord(arg, dirState)
    }
    if (exe === "sh" || exe === "bash" || exe === "zsh") {
      for (let k = idx + 1; k < words.length; k++) {
        const opt = words[k]
        if (opt.dynamic) return dirState
        const ov = opt.value
        if (ov === "-o" || ov === "+o" || ov === "-O" || ov === "+O") { k++; continue }
        if (ov === "--norc" || ov === "--noprofile") continue
        if (!ov.startsWith("-") || ov === "--") break
        if (!ov.startsWith("--") && ov.slice(1).includes("c")) {
          const scriptArg = words[k + 1]
          if (scriptArg && !scriptArg.dynamic && !scriptArg.hasGlob) {
            scanScript(scriptArg.value, { ...dirState }, depth + 1)
          }
          break
        }
      }
      return dirState
    }
    if (exe === "xargs") {
      let k = idx + 1
      let repl = ""
      while (k < words.length) {
        const opt = words[k]
        if (opt.dynamic) break
        const ov = opt.value
        if (ov === "--") { k++; break }
        if (!ov.startsWith("-") || ov === "-") break
        if (ov.startsWith("--")) {
          if (ov === "--max-args" || ov === "--max-procs" || ov === "--max-lines" || ov === "--eof") { k += 2; continue }
          if (ov === "--replace") { repl = "{}"; k++; continue }
          if (ov.startsWith("--replace=")) { repl = ov.slice("--replace=".length) || "{}"; k++; continue }
          k++
          continue
        }
        let consumedNext = false
        for (let c = 1; c < ov.length; c++) {
          const ch = ov[c]
          if ("EIRSJLnPs".includes(ch)) {
            let val = ""
            if (c + 1 < ov.length) val = ov.slice(c + 1)
            else if (k + 1 < words.length) { val = words[k + 1].value; consumedNext = true }
            if (ch === "I" || ch === "J") repl = val
            break
          }
          if (ch === "i") repl = c + 1 < ov.length ? ov.slice(c + 1) : "{}"
        }
        k += consumedNext ? 2 : 1
      }
      if (k < words.length) {
        const forwarded = words.slice(k).map(w => (
          repl && !w.dynamic && w.value.includes(repl) ? { ...w, dynamic: true } : w
        ))
        inspectWords(forwarded, { ...dirState }, localSelector, depth + 1)
      }
      return dirState
    }
    if (exe === "git") {
      let gitState = { ...dirState }
      let gitSelector = localSelector || envSelector
      let k = idx + 1
      while (k < words.length) {
        const w = words[k]
        if (w.dynamic || w.hasGlob) {
          if (w.rawPrefix.startsWith("-C")) { gitState = { dir: "", dynamic: true }; k++; continue }
          if (w.rawPrefix.startsWith("--git-dir") || w.rawPrefix.startsWith("--work-tree") || w.rawPrefix.startsWith("--config-env") || w.rawPrefix.startsWith("-c")) {
            gitSelector = true; k++; continue
          }
          return dirState
        }
        const v = w.value
        if (!v.startsWith("-")) break
        if (v === "--") { k++; break }
        if (v === "-h" || v === "--help" || v === "-v" || v === "--version" || v === "--html-path" || v === "--man-path" || v === "--info-path" || v === "--exec-path") {
          return dirState
        }
        if (v === "-C") {
          k++
          if (k >= words.length) return dirState
          gitState = resolveDirWord(words[k], gitState)
          k++
          continue
        }
        if (v.startsWith("-C") && v.length > 2) {
          gitState = resolveDirWord({ value: v.slice(2), dynamic: false, hasGlob: false, leadingTilde: w.rawPrefix.startsWith("-C~") }, gitState)
          k++
          continue
        }
        if (v === "--git-dir" || v === "--work-tree" || v === "--config-env") {
          gitSelector = true; k += 2; continue
        }
        if (v.startsWith("--git-dir=") || v.startsWith("--work-tree=") || v.startsWith("--config-env=") || v === "--bare") {
          gitSelector = true; k++; continue
        }
        if (v === "--namespace" || v === "--super-prefix") { k += 2; continue }
        if (v.startsWith("--namespace=") || v.startsWith("--super-prefix=") || v.startsWith("--exec-path=")) { k++; continue }
        if (v === "-c") {
          k++
          if (k < words.length) {
            const cfg = words[k]
            if (cfg.dynamic || /^(core\.worktree|core\.bare)=/i.test(cfg.value)) gitSelector = true
          }
          k++
          continue
        }
        if (v.startsWith("-c") && v.length > 2) {
          if (/^(core\.worktree|core\.bare)=/i.test(v.slice(2))) gitSelector = true
          k++
          continue
        }
        k++
      }
      const subWord = words[k]
      if (!subWord || subWord.dynamic || subWord.hasGlob) return dirState
      const sub = subWord.value
      if (sub !== "merge" && sub !== "pull" && sub !== "rebase") return dirState

      const valueShortChars = sub === "rebase" ? "xCsX" : "mFsXoj"
      let exempt = false
      const subArgs = words.slice(k + 1)
      for (let m = 0; m < subArgs.length; m++) {
        const aw = subArgs[m]
        if (aw.dynamic) continue
        const av = aw.value
        if (av === "--") break
        if (EXEMPT_FLAGS.has(av)) { exempt = true; break }
        if (av.startsWith("--")) {
          if (!av.includes("=") && VALUE_LONG_OPTS.has(av)) m++
          continue
        }
        if (av.startsWith("-") && av.length > 1) {
          for (let cIdx = 1; cIdx < av.length; cIdx++) {
            const ch = av[cIdx]
            if (ch === "h") { exempt = true; break }
            if (valueShortChars.includes(ch)) {
              if (cIdx === av.length - 1) m++
              break
            }
          }
          if (exempt) break
          continue
        }
      }
      if (!exempt) {
        const target = sub === "merge" ? fastForwardTarget(subArgs) : ""
        if (gitSelector) findings.push({ sub, kind: "selector", dir: "", target: "" })
        else if (gitState.dynamic || !gitState.dir) findings.push({ sub, kind: "dynamic", dir: "", target: "" })
        else findings.push({ sub, kind: "ok", dir: gitState.dir, target })
      }
      return dirState
    }
    return dirState
  }
  return dirState
}

function scanScript(src, startDir, depth) {
  if (depth > 8) {
    if (/\b(merge|pull|rebase)\b/.test(src)) findings.push({ sub: "merge", kind: "dynamic", dir: "", target: "" })
    return
  }
  let dirState = { ...startDir }
  const dirStack = []
  let words = []
  const pendingHeredocs = []
  let expectRedirectTarget = false
  let expectHeredocDelim = null
  let i = 0
  const n = src.length

  function flush() {
    if (words.length > 0) {
      dirState = inspectWords(words, dirState, false, depth)
      words = []
    }
    expectRedirectTarget = false
    expectHeredocDelim = null
  }

  function consumeHeredocs() {
    while (pendingHeredocs.length > 0 && i < n) {
      const h = pendingHeredocs.shift()
      while (i < n) {
        let lineEnd = src.indexOf("\n", i)
        if (lineEnd === -1) lineEnd = n
        let line = src.slice(i, lineEnd)
        if (line.endsWith("\r")) line = line.slice(0, -1)
        const checkLine = h.stripTabs ? line.replace(/^\t+/, "") : line
        i = lineEnd < n ? lineEnd + 1 : n
        if (checkLine === h.delim) break
        if (!h.quoted) scanExpansionText(line, dirState, depth + 1)
      }
    }
  }

  while (i < n) {
    const ch = src[i]
    if (ch === " " || ch === "\t" || ch === "\r") { i++; continue }
    if (ch === "\\" && src[i + 1] === "\n") { i += 2; continue }
    if (ch === "#" && !expectHeredocDelim) {
      while (i < n && src[i] !== "\n") i++
      continue
    }
    if (ch === "\n") {
      flush()
      i++
      if (pendingHeredocs.length > 0) consumeHeredocs()
      continue
    }
    if (ch === "(") {
      flush()
      dirStack.push({ ...dirState })
      i++
      continue
    }
    if (ch === ")") {
      flush()
      if (dirStack.length > 0) dirState = dirStack.pop()
      i++
      continue
    }
    if (ch === ";" || ch === "&" || ch === "|") {
      flush()
      if (src.slice(i, i + 3) === ";;&") i += 3
      else if (["&&", "||", ";;", ";&", "|&"].includes(src.slice(i, i + 2))) i += 2
      else i++
      continue
    }
    if (ch === "<" || ch === ">") {
      if (src.slice(i, i + 3) === "<<-") { expectHeredocDelim = { stripTabs: true }; i += 3; continue }
      if (src.slice(i, i + 3) === "<<<") { expectRedirectTarget = true; i += 3; continue }
      if (src.slice(i, i + 2) === "<<") { expectHeredocDelim = { stripTabs: false }; i += 2; continue }
      if (["<>", ">&", "<&", ">>", ">|"].includes(src.slice(i, i + 2))) { expectRedirectTarget = true; i += 2; continue }
      expectRedirectTarget = true
      i++
      continue
    }

    let value = ""
    let unquotedPrefix = ""
    let seenQuoteOrDynamic = false
    let quoted = false
    let dynamic = false
    let hasGlob = false

    while (i < n) {
      const c = src[i]
      if (" \t\r\n;&|()<>".includes(c)) break
      if (c === "\\") {
        if (src[i + 1] === "\n") { i += 2; continue }
        seenQuoteOrDynamic = true
        quoted = true
        if (i + 1 < n) { value += src[i + 1]; i += 2; continue }
        i++
        break
      }
      if (c === "\x27") {
        seenQuoteOrDynamic = true
        quoted = true
        i++
        while (i < n && src[i] !== "\x27") { value += src[i]; i++ }
        if (i < n) i++
        continue
      }
      if (c === "$" && src[i + 1] === "\x27") {
        seenQuoteOrDynamic = true
        quoted = true
        i += 2
        while (i < n && src[i] !== "\x27") {
          if (src[i] === "\\" && i + 1 < n) {
            const esc = src[i + 1]
            value += esc === "n" ? "\n" : esc === "t" ? "\t" : esc === "r" ? "\r" : esc
            i += 2
          } else {
            value += src[i]
            i++
          }
        }
        if (i < n) i++
        continue
      }
      if (c === "\"" || (c === "$" && src[i + 1] === "\"")) {
        seenQuoteOrDynamic = true
        quoted = true
        i += c === "$" ? 2 : 1
        while (i < n && src[i] !== "\"") {
          if (src[i] === "\\") {
            if (src[i + 1] === "\n") { i += 2; continue }
            if (i + 1 < n && "\"\\$`".includes(src[i + 1])) { value += src[i + 1]; i += 2; continue }
            value += src[i]
            i++
            continue
          }
          if (src[i] === "$" && src[i + 1] === "(") {
            dynamic = true
            if (src[i + 2] === "(") {
              const end = findMatchingParen(src, i + 1)
              scanExpansionText(src.slice(i + 3, Math.max(i + 3, end - 2)), dirState, depth + 1)
              i = end
              continue
            }
            const end = findMatchingParen(src, i + 1)
            scanScript(src.slice(i + 2, Math.max(i + 2, end - 1)), { ...dirState }, depth + 1)
            i = end
            continue
          }
          if (src[i] === "$" && src[i + 1] === "{") {
            dynamic = true
            let b = 1, q = i + 2
            while (q < n && b > 0) {
              if (src[q] === "\\") { q += 2; continue }
              if (src[q] === "{") b++
              else if (src[q] === "}") b--
              q++
            }
            scanExpansionText(src.slice(i + 2, Math.max(i + 2, q - 1)), dirState, depth + 1)
            i = q
            continue
          }
          if (src[i] === "$" && i + 1 < n && /[A-Za-z0-9_?#$!@*-]/.test(src[i + 1])) {
            dynamic = true
            if (/[A-Za-z_]/.test(src[i + 1])) {
              i += 2
              while (i < n && /[A-Za-z0-9_]/.test(src[i])) i++
            } else {
              i += 2
            }
            continue
          }
          if (src[i] === "`") {
            dynamic = true
            const bt = readBacktick(src, i)
            scanScript(bt.inner, { ...dirState }, depth + 1)
            i = bt.next
            continue
          }
          value += src[i]
          i++
        }
        if (i < n && src[i] === "\"") i++
        continue
      }
      if (c === "$") {
        if (src[i + 1] === "(") {
          seenQuoteOrDynamic = true
          dynamic = true
          if (src[i + 2] === "(") {
            const end = findMatchingParen(src, i + 1)
            scanExpansionText(src.slice(i + 3, Math.max(i + 3, end - 2)), dirState, depth + 1)
            i = end
            continue
          }
          const end = findMatchingParen(src, i + 1)
          scanScript(src.slice(i + 2, Math.max(i + 2, end - 1)), { ...dirState }, depth + 1)
          i = end
          continue
        }
        if (src[i + 1] === "{") {
          seenQuoteOrDynamic = true
          dynamic = true
          let b = 1, q = i + 2
          while (q < n && b > 0) {
            if (src[q] === "\\") { q += 2; continue }
            if (src[q] === "{") b++
            else if (src[q] === "}") b--
            q++
          }
          scanExpansionText(src.slice(i + 2, Math.max(i + 2, q - 1)), dirState, depth + 1)
          i = q
          continue
        }
        if (i + 1 < n && /[A-Za-z0-9_?#$!@*-]/.test(src[i + 1])) {
          seenQuoteOrDynamic = true
          dynamic = true
          if (/[A-Za-z_]/.test(src[i + 1])) {
            i += 2
            while (i < n && /[A-Za-z0-9_]/.test(src[i])) i++
          } else {
            i += 2
          }
          continue
        }
        if (!seenQuoteOrDynamic) unquotedPrefix += "$"
        value += "$"
        i++
        continue
      }
      if (c === "`") {
        seenQuoteOrDynamic = true
        dynamic = true
        const bt = readBacktick(src, i)
        scanScript(bt.inner, { ...dirState }, depth + 1)
        i = bt.next
        continue
      }
      if ("*?[]".includes(c)) hasGlob = true
      if (!seenQuoteOrDynamic) unquotedPrefix += c
      value += c
      i++
    }

    if (!quoted && !dynamic && /^\d+$/.test(value) && i < n && (src[i] === "<" || src[i] === ">")) {
      continue
    }
    if (expectHeredocDelim) {
      pendingHeredocs.push({ delim: value, stripTabs: expectHeredocDelim.stripTabs, quoted })
      expectHeredocDelim = null
      continue
    }
    if (expectRedirectTarget) {
      expectRedirectTarget = false
      continue
    }
    const assignMatch = unquotedPrefix.match(/^([A-Za-z_][A-Za-z0-9_]*)=/)
    words.push({
      value,
      quoted,
      dynamic,
      hasGlob,
      rawPrefix: unquotedPrefix,
      rawAssignName: assignMatch ? assignMatch[1] : null,
      leadingTilde: unquotedPrefix.startsWith("~")
    })
  }
  flush()
}

scanScript(command, { dir: baseCwd, dynamic: false }, 0)
for (const item of findings) {
  if ([item.sub, item.kind, item.dir, item.target].some(v => v.includes("\u0000"))) process.exit(1)
  process.stdout.write(`${item.sub}\u0000${item.kind}\u0000${item.dir}\u0000${item.target}\u0000`)
}
' <<< "$PAYLOAD" > "$TMP/integration-fields" 2> "$TMP/integration-error"; then
      deny 'agent contract gate failed to inspect git merge/pull/rebase command'
      exit $?
    fi
    while IFS= read -r -d '' INTEGRATION_SUBCMD; do
      IFS= read -r -d '' INTEGRATION_KIND || {
        deny 'agent contract gate received truncated integration inspection output'
        exit $?
      }
      IFS= read -r -d '' INTEGRATION_DIR || {
        deny 'agent contract gate received truncated integration directory output'
        exit $?
      }
      IFS= read -r -d '' INTEGRATION_TARGET || {
        deny 'agent contract gate received truncated integration target output'
        exit $?
      }
      if [ "$INTEGRATION_KIND" = "selector" ]; then
        audit deny "dirty-worktree-${INTEGRATION_SUBCMD}" "git-selector"
        deny "agent contract gate cannot verify worktree cleanliness for \`git ${INTEGRATION_SUBCMD}\` with a custom Git selector (GIT_DIR/GIT_WORK_TREE/core.worktree). Integrate via a temporary clean worktree instead (\`git -C <repo> worktree add --detach <temp-worktree> origin/<trunk>\`, run \`git -C <temp-worktree> ${INTEGRATION_SUBCMD} ...\`, push, then remove \`<temp-worktree>\`); in-progress --continue, --abort, --quit, and --skip remain allowed."
        exit $?
      fi
      if [ "$INTEGRATION_KIND" = "dynamic" ]; then
        audit deny "dirty-worktree-${INTEGRATION_SUBCMD}" "dynamic-target"
        deny "agent contract gate cannot verify worktree cleanliness for \`git ${INTEGRATION_SUBCMD}\` with a dynamic cd or git -C target. Pass a literal path to a clean worktree (\`git -C <clean-worktree> ${INTEGRATION_SUBCMD} ...\`) in its own Bash call; in-progress --continue, --abort, --quit, and --skip remain allowed."
        exit $?
      fi
      # One status snapshot avoids counting untracked paths twice within the hook deadline.
      # bash 3.2 mis-parses a heredoc inside $(...), so the helper writes to a file instead.
      python3 -I - "$INTEGRATION_DIR" "$INTEGRATION_TARGET" > "$TMP/integration-overlap" 2>/dev/null <<'PY'
import os, subprocess, sys

directory, target = sys.argv[1:3]
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}

def git(*args):
  return subprocess.run(["git", "-C", directory, *args], capture_output=True, env=env, timeout=3)

def decode(path):
  return path.decode("utf-8", "surrogateescape")

def parents(path):
  while "/" in path:
    path = path.rsplit("/", 1)[0]
    yield path

try:
  status = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
  status.check_returncode()
except (OSError, subprocess.SubprocessError):
  sys.exit(4)
if not status.stdout:
  sys.exit(0)
if not target:
  sys.exit(2)

try:
  ancestor = git("merge-base", "--is-ancestor", "HEAD", target)
  if ancestor.returncode == 1:
    sys.exit(3)
  ancestor.check_returncode()
  diff = git("diff", "--name-only", "--no-renames", "-z", "--no-relative", "HEAD.." + target, "--")
  diff.check_returncode()
except (OSError, subprocess.SubprocessError):
  sys.exit(2)

changed = {decode(p).casefold() for p in diff.stdout.split(b"\0") if p}
changed_parents = {parent for path in changed for parent in parents(path)}
dirty = set()
fields = iter(status.stdout.split(b"\0"))
for entry in fields:
  if not entry:
    break
  if len(entry) < 4:
    sys.exit(2)
  dirty.add(decode(entry[3:]))
  if entry[:1] in (b"R", b"C") or entry[1:2] in (b"R", b"C"):
    source = next(fields, b"")
    if not source:
      sys.exit(2)
    dirty.add(decode(source))

overlap = []
for path in sorted(dirty):
  folded = path.rstrip("/").casefold()
  if folded in changed or folded in changed_parents or any(parent in changed for parent in parents(folded)):
    overlap.append(path)
if overlap:
  print("\n".join(overlap))
  sys.exit(6)
sys.exit(5)
PY
      INTEGRATION_RC=$?
      INTEGRATION_HINT='In a dirty worktree the in-place exception requires a fast-forward with no path overlap: `git -C <repo> merge --ff-only --no-autostash --no-overwrite-ignore origin/<trunk>`. For a non-fast-forward or overlap, integrate via a temporary clean worktree instead (`git -C <repo> worktree add --detach <temp-worktree> origin/<trunk>`, merge and push from `<temp-worktree>`, then remove it).'
      case "$INTEGRATION_RC" in
        0) continue ;;
        5)
          audit allow 'dirty-worktree-merge-disjoint' "$INTEGRATION_DIR"
          continue
          ;;
        6)
          audit deny 'dirty-worktree-merge-overlap' "$INTEGRATION_DIR"
          INTEGRATION_OVERLAP=$(tr '\n' ' ' < "$TMP/integration-overlap")
          deny "agent contract gate blocked \`git merge ${INTEGRATION_TARGET}\` in dirty worktree ${INTEGRATION_DIR}: these uncommitted paths are also changed by the merge: ${INTEGRATION_OVERLAP% }. ${INTEGRATION_HINT}"
          ;;
        3)
          audit deny 'dirty-worktree-merge-not-fast-forward' "$INTEGRATION_DIR"
          deny "agent contract gate blocked \`git merge ${INTEGRATION_TARGET}\` in dirty worktree ${INTEGRATION_DIR}: HEAD is not an ancestor of the target, so this is not a fast-forward. ${INTEGRATION_HINT}"
          ;;
        4)
          audit deny "dirty-worktree-${INTEGRATION_SUBCMD}" "$INTEGRATION_DIR"
          deny "agent contract gate could not inspect \`git status --porcelain\` for \`git ${INTEGRATION_SUBCMD}\` in ${INTEGRATION_DIR}. ${INTEGRATION_HINT}"
          ;;
        *)
          audit deny "dirty-worktree-${INTEGRATION_SUBCMD}" "$INTEGRATION_DIR"
          deny "agent contract gate blocked \`git ${INTEGRATION_SUBCMD}\` in dirty worktree ${INTEGRATION_DIR}: the fast-forward exception could not be verified. ${INTEGRATION_HINT} In-progress \`--continue\`, \`--abort\`, \`--quit\`, and \`--skip\` remain allowed."
          ;;
      esac
      exit $?
    done < "$TMP/integration-fields"
    ;;
esac

case "$COMMAND" in
  *commit*) ;;
  *) exit 0 ;;
esac

# 在判讀前接手，避免修改中的 parser 先回「沒有提交」而跳過 HEAD 保護。
LOCK_ROOT=${AGENT_CONTRACT_GATE_LOCK_ROOT:-$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd -P)}
EVALUATOR_DIRTY=
EVALUATOR_DIRTY_REASON=
if [ -n "$LOCK_ROOT" ] && git -C "$LOCK_ROOT" rev-parse --show-toplevel >/dev/null 2>&1; then
  for EVALUATOR_PATH in hooks/agent-contract-validator-gate.sh scripts/agent-contract-validator.mjs scripts/agent-contract-command/main.go scripts/agent-contract-command/go.mod scripts/agent-contract-command/go.sum; do
    if git -C "$LOCK_ROOT" cat-file -e "HEAD:$EVALUATOR_PATH" 2>/dev/null && ! git -C "$LOCK_ROOT" diff --quiet HEAD -- "$EVALUATOR_PATH" >/dev/null 2>&1; then
      EVALUATOR_DIRTY="$EVALUATOR_DIRTY${EVALUATOR_DIRTY:+ }$EVALUATOR_PATH"
    fi
  done
fi
if [ -n "$EVALUATOR_DIRTY" ] && [ "${AGENT_CONTRACT_GATE_REEXEC:-}" != 1 ]; then
  HEAD_ROOT="$TMP/head"
  HEAD_GATE="$HEAD_ROOT/hooks/agent-contract-validator-gate.sh"
  HEAD_VALIDATOR="$HEAD_ROOT/scripts/agent-contract-validator.mjs"
  HEAD_READY=1
  mkdir -p "$HEAD_ROOT/hooks" "$HEAD_ROOT/scripts/agent-contract-command" || HEAD_READY=0
  git -C "$LOCK_ROOT" show HEAD:hooks/agent-contract-validator-gate.sh > "$HEAD_GATE" 2>/dev/null || HEAD_READY=0
  git -C "$LOCK_ROOT" show HEAD:scripts/agent-contract-validator.mjs > "$HEAD_VALIDATOR" 2>/dev/null || HEAD_READY=0
  grep -q 'AGENT_CONTRACT_GATE_REEXEC' "$HEAD_GATE" || HEAD_READY=0
  if git -C "$LOCK_ROOT" cat-file -e HEAD:scripts/agent-contract-command/main.go 2>/dev/null; then
    for PARSER_FILE in main.go go.mod go.sum; do
      git -C "$LOCK_ROOT" show "HEAD:scripts/agent-contract-command/$PARSER_FILE" > "$HEAD_ROOT/scripts/agent-contract-command/$PARSER_FILE" 2>/dev/null || HEAD_READY=0
    done
  fi
  if [ "$HEAD_READY" -eq 1 ]; then
    audit reexec head-evaluator "$EVALUATOR_DIRTY"
    printf '%s' "$PAYLOAD" | AGENT_CONTRACT_GATE_REEXEC=1 \
      AGENT_CONTRACT_GATE_LOCK_ROOT="$LOCK_ROOT" \
      AGENT_CONTRACT_GATE_VALIDATOR="$HEAD_VALIDATOR" \
      AGENT_CONTRACT_GATE_SENTINEL="$SENTINEL" \
      AGENT_CONTRACT_GATE_PERMIT="$PERMIT_FILE" \
      AGENT_CONTRACT_GATE_AUDIT="$AUDIT_LOG" \
      bash "$HEAD_GATE"
    exit $?
  fi
  EVALUATOR_DIRTY_REASON="the running agent contract gate differs from HEAD ($EVALUATOR_DIRTY) and the committed copy cannot take over"
fi

# 判讀器只讀命令結構；相依缺失或壞回件不能冒充「沒有提交」。
PARSER_DIR="$SCRIPT_DIR/../scripts/agent-contract-command"
if ! node --input-type=module -e '
import fs from "node:fs"
const input = JSON.parse(fs.readFileSync(0, "utf8"))
process.stdout.write(JSON.stringify({command: input.tool_input?.command ?? ""}))
' <<< "$PAYLOAD" > "$TMP/parser-input.json" 2> "$TMP/parser-error" \
  || ! (cd "$PARSER_DIR" && GOTOOLCHAIN=local GOWORK=off GOFLAGS= GOPROXY=off GOSUMDB=off go run -mod=readonly main.go) \
    < "$TMP/parser-input.json" > "$TMP/parser-result.json" 2>> "$TMP/parser-error"; then
  deny "agent contract commit gate command parser failed or is unavailable; restore its pinned dependencies before retrying$INSPECT_HINT"
  exit $?
fi
if ! node --input-type=module -e '
import fs from "node:fs"
const result = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const strings = [result.denial, result.cd_target, result.git_c_target]
if (typeof result.has_commit !== "boolean" || typeof result.auto_stage !== "boolean" ||
    typeof result.only_commit !== "boolean" ||
    !strings.every(value => value === null || typeof value === "string") ||
    !Array.isArray(result.pathspecs) || !result.pathspecs.every(value => typeof value === "string")) process.exit(1)
const fields = [String(result.has_commit), ...strings.map(value => value ?? ""), String(result.auto_stage), String(result.only_commit), ...result.pathspecs]
if (fields.some(value => value.includes("\u0000"))) process.exit(1)
process.stdout.write(fields.join("\u0000") + "\u0000")
' "$TMP/parser-result.json" > "$TMP/parser-fields" 2>> "$TMP/parser-error"; then
  deny 'agent contract commit gate command parser returned an invalid result'
  exit $?
fi
{
  IFS= read -r -d '' HAS_COMMIT
  IFS= read -r -d '' PARSER_DENIAL
  IFS= read -r -d '' CD_TARGET
  IFS= read -r -d '' GIT_C_TARGET
  IFS= read -r -d '' AUTO_STAGE
  IFS= read -r -d '' ONLY_COMMIT
  PATHSPEC_TOKENS=()
  while IFS= read -r -d '' PATHSPEC_TOKEN; do
    PATHSPEC_TOKENS+=("$PATHSPEC_TOKEN")
  done
} < "$TMP/parser-fields"
if [ -n "$PARSER_DENIAL" ]; then
  if [ "$HAS_COMMIT" = true ]; then
    deny "agent contract commit gate cannot safely inspect $PARSER_DENIAL$INSPECT_HINT"
  else
    deny "agent contract commit gate cannot safely inspect $PARSER_DENIAL (non-commit command; avoid dynamic shell syntax or pass explicit paths)"
  fi
  exit $?
fi
[ "$HAS_COMMIT" = true ] || exit 0
if [ -n "${GIT_INDEX_FILE:-}" ] || [ -n "${GIT_DIR:-}" ] || [ -n "${GIT_WORK_TREE:-}" ]; then
  deny "agent contract commit gate cannot safely inspect a command-local Git selector$INSPECT_HINT"
  exit $?
fi

if ! CWD=$(json_value cwd 2>/dev/null); then
  deny 'agent contract commit gate could not parse the command cwd'
  exit $?
fi
[ -n "$CWD" ] || CWD=$(pwd)
if [ -n "$CD_TARGET" ]; then
  CD_TARGET="${CD_TARGET/#\~/$HOME}"
  case "$CD_TARGET" in
    /*) ;;
    *) CD_TARGET="$CWD/$CD_TARGET" ;;
  esac
  if [ ! -d "$CD_TARGET" ]; then
    deny "agent contract commit gate could not resolve cd target: $CD_TARGET"
    exit $?
  fi
  CWD="$CD_TARGET"
fi
if [ -n "$GIT_C_TARGET" ]; then
  GIT_C_TARGET="${GIT_C_TARGET/#\~/$HOME}"
  case "$GIT_C_TARGET" in
    /*) ;;
    *) GIT_C_TARGET="$CWD/$GIT_C_TARGET" ;;
  esac
  if [ ! -d "$GIT_C_TARGET" ]; then
    deny "agent contract commit gate could not resolve git -C target: $GIT_C_TARGET"
    exit $?
  fi
  CWD="$GIT_C_TARGET"
fi

if ! REPO=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null); then
  deny 'agent contract commit gate could not resolve the repository for git commit'
  exit $?
fi

canonical_dir() {
  (cd "$1" 2>/dev/null && pwd -P)
}

GLOBAL_ROOT=${CLAUDE_CONFIG_DIR:-$HOME/.claude}
if ! GLOBAL_ROOT=$(canonical_dir "$GLOBAL_ROOT"); then
  deny "agent contract commit gate could not resolve global root: $GLOBAL_ROOT"
  exit $?
fi
# CLAUDE_CONFIG_DIR can be a real directory whose entries symlink into another
# config tree (~/.claude-max/hooks -> ~/.claude/hooks). canonical_dir stops at
# the outer directory, so the real config repo would be classified as foreign
# and every locked-surface check below would be skipped. Resolving through a
# known symlinked entry recovers the tree the config actually lives in. Only
# that second root is added -- never a guess like $HOME/.claude -- so a fixture
# pointing CLAUDE_CONFIG_DIR elsewhere still isolates from the real repo.
# Resolve through the entry itself, not "$GLOBAL_ROOT/hooks/.." -- cd handles ..
# logically and would walk straight back to the outer directory without ever
# following the link.
GLOBAL_ROOTS="$GLOBAL_ROOT"
LINKED_HOOKS=$(canonical_dir "$GLOBAL_ROOT/hooks" 2>/dev/null || true)
if [ -n "$LINKED_HOOKS" ]; then
  LINKED_ROOT=$(dirname "$LINKED_HOOKS")
  if [ "$LINKED_ROOT" != "$GLOBAL_ROOT" ]; then
    GLOBAL_ROOTS="$GLOBAL_ROOTS $LINKED_ROOT"
  fi
fi
is_global_root() {
  [ -n "$1" ] || return 1
  case " $GLOBAL_ROOTS " in
    *" $1 "*) return 0 ;;
  esac
  return 1
}
if ! REPO_CANONICAL=$(canonical_dir "$REPO"); then
  deny "agent contract commit gate could not resolve repository root: $REPO"
  exit $?
fi
GIT_COMMON_DIR=$(git -C "$REPO" rev-parse --git-common-dir 2>/dev/null || true)
COMMON_ROOT=
if [ -n "$GIT_COMMON_DIR" ]; then
  case "$GIT_COMMON_DIR" in
    /*) ;;
    *) GIT_COMMON_DIR="$REPO/$GIT_COMMON_DIR" ;;
  esac
  COMMON_ROOT=$(canonical_dir "$GIT_COMMON_DIR/.." 2>/dev/null || true)
fi
if is_global_root "$REPO_CANONICAL" || is_global_root "$COMMON_ROOT"; then
  GLOBAL_REPO=1
else
  GLOBAL_REPO=0
fi

has_controlled_surface() {
  if [ "$GLOBAL_REPO" -eq 1 ]; then
    case "$1" in
      agents/*|skills/*|commands/*|workflows/*|references/subagent-routing.md|settings*.json|hooks/T2-routing-gate*|hooks/review-spec-yagni-permit.py|hooks/review-spec-yagni-permit.test.py|scripts/agent-contract-validator.mjs|scripts/agent-contract-command/*|hooks/agent-contract-validator-gate.sh|hooks/agent-contract-validator-gate.test.sh|hooks/agent-contract-gate-permit.sh)
        return 0
        ;;
    esac
  fi
  case "$1" in
    .claude/agents/*|.claude/skills/*|.claude/commands/*|.claude/workflows/*|.claude/references/subagent-routing.md|.claude/settings*.json|.claude/hooks/T2-routing-gate*|.claude/hooks/review-spec-yagni-permit.py|.claude/hooks/review-spec-yagni-permit.test.py|.claude/scripts/agent-contract-validator.mjs|.claude/scripts/agent-contract-command/*|.claude/hooks/agent-contract-validator-gate.sh|.claude/hooks/agent-contract-validator-gate.test.sh|.claude/hooks/agent-contract-gate-permit.sh)
      return 0
      ;;
  esac
  return 1
}

is_locked_surface() {
  if [ "$GLOBAL_REPO" -eq 1 ]; then
    case "$1" in
      hooks/T2-routing-gate*|hooks/review-spec-yagni-permit.py|hooks/review-spec-yagni-permit.test.py|scripts/agent-contract-validator.mjs|scripts/agent-contract-command/*|hooks/agent-contract-validator-gate.sh|hooks/agent-contract-validator-gate.test.sh|hooks/agent-contract-gate-permit.sh)
        return 0
        ;;
    esac
  fi
  case "$1" in
    .claude/hooks/T2-routing-gate*|.claude/hooks/review-spec-yagni-permit.py|.claude/hooks/review-spec-yagni-permit.test.py|.claude/scripts/agent-contract-validator.mjs|.claude/scripts/agent-contract-command/*|.claude/hooks/agent-contract-validator-gate.sh|.claude/hooks/agent-contract-validator-gate.test.sh|.claude/hooks/agent-contract-gate-permit.sh)
      return 0
      ;;
  esac
  return 1
}

settings_registration_present() {
  if [ ! -f "$PROJECTION/settings.json" ]; then
    return 1
  fi
  if command -v jq >/dev/null 2>&1; then
    jq -e '[.hooks.PreToolUse[]? | select(.matcher == "Bash") | .hooks[]?.command? | select(. == "~/.claude/hooks/agent-contract-validator-gate.sh")] | any' "$PROJECTION/settings.json" >/dev/null 2>&1
    return $?
  fi
  node --input-type=module -e '
import fs from "node:fs"
const value = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
const commands = (value.hooks?.PreToolUse ?? []).filter(item => item.matcher === "Bash").flatMap(item => item.hooks ?? []).map(item => item.command ?? "")
if (!commands.some(command => command === "~/.claude/hooks/agent-contract-validator-gate.sh")) process.exit(1)
' "$PROJECTION/settings.json"
}

run_validator_on_projection() {
  VALIDATED_GLOBAL="$GLOBAL_ROOT"
  VALIDATED_REPO="$PROJECTION"
  if [ "$GLOBAL_REPO" -eq 1 ]; then
    VALIDATED_GLOBAL="$PROJECTION"
  fi

  [ -f "$VALIDATOR" ] || {
    deny "agent contract validator is unavailable at $VALIDATOR"
    exit $?
  }

  # Projection holds only Git-tracked/candidate files; pass untracked runtime MCP
  # registries (.claude.json under resolved global config roots) so settings.json
  # MCP allow rules validate against servers actually enabled on this machine.
  MCP_ARGS=()
  if [ "$GLOBAL_REPO" -eq 1 ]; then
    EXTRA_MCP=0
    for candidate_root in $GLOBAL_ROOTS; do
      if [ -f "$candidate_root/.claude.json" ]; then
        EXTRA_MCP=1
      fi
    done
    if [ "$EXTRA_MCP" -eq 1 ]; then
      if [ -f "$PROJECTION/.claude.json" ]; then
        MCP_ARGS+=(--mcp-config "$PROJECTION/.claude.json")
      fi
      for candidate_root in $GLOBAL_ROOTS; do
        if [ -f "$candidate_root/.claude.json" ]; then
          MCP_ARGS+=(--mcp-config "$candidate_root/.claude.json")
        fi
      done
      if [ -f "$HOME/.claude.json" ]; then
        MCP_ARGS+=(--mcp-config "$HOME/.claude.json")
      fi
    fi
  fi

  RESULT="$TMP/validator-result"
  if [ "${#MCP_ARGS[@]}" -gt 0 ]; then
    node "$VALIDATOR" --global-root "$VALIDATED_GLOBAL" --repo-root "$VALIDATED_REPO" "${MCP_ARGS[@]}" > "$RESULT" 2>&1
  else
    node "$VALIDATOR" --global-root "$VALIDATED_GLOBAL" --repo-root "$VALIDATED_REPO" > "$RESULT" 2>&1
  fi
  VALIDATOR_STATUS=$?
  REASON=$(<"$RESULT")
  map_diagnostics() {
    local mapped
    mapped=$(node --input-type=module -e '
import fs from "node:fs"
const [file, projection, repo] = process.argv.slice(1)
const value = JSON.parse(fs.readFileSync(file, "utf8"))
const mapPath = path => path === projection || path.startsWith(`${projection}/`) ? `${repo}${path.slice(projection.length)}` : path
const rewrite = input => {
  if (Array.isArray(input)) return input.map(rewrite)
  if (!input || typeof input !== "object") return input
  return Object.fromEntries(Object.entries(input).map(([key, item]) => [key, (key === "path" || key === "file") && typeof item === "string" ? mapPath(item) : rewrite(item)]))
}
process.stdout.write(JSON.stringify(rewrite(value), null, 2))
' "$RESULT" "$PROJECTION" "$REPO" 2>/dev/null) || mapped=
    [ -n "$mapped" ] && REASON="$mapped"
  }
  if [ "$VALIDATOR_STATUS" -ne 0 ]; then
    map_diagnostics
    [ -n "$REASON" ] || REASON="agent contract validator exited with status $VALIDATOR_STATUS"
    deny "$REASON"
    exit $?
  fi
  validator_passes() {
    if command -v jq >/dev/null 2>&1; then
      jq -e '(.status == "pass") and (.valid == true) and ((.summary.errors // 1) == 0)' "$RESULT" >/dev/null 2>&1
      return $?
    fi
    node --input-type=module -e '
import fs from "node:fs"
const value = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
if (!(value.status === "pass" && value.valid === true && (value.summary?.errors ?? 1) === 0)) process.exit(1)
' "$RESULT"
  }
  if ! validator_passes; then
    map_diagnostics
    [ -n "$REASON" ] || REASON='agent contract validator returned an invalid pass result'
    deny "$REASON"
    exit $?
  fi
}

# Strict `git commit --only -- <literal files>` bypasses the shared `.git/index`
# so parallel sessions do not collide on staged_foreign entries. Locked surfaces
# stay on the staged-index permit flow; controlled surfaces are validated via an
# isolated temporary index built from HEAD plus the named working-tree files.
if [ "$ONLY_COMMIT" = true ]; then
  if ! CWD_CANONICAL=$(canonical_dir "$CWD"); then
    deny "agent contract commit gate could not resolve command directory for --only commit: $CWD"
    exit $?
  fi
  ONLY_ERR="$TMP/only-resolve.err"
  if ! python3 -I - "$REPO_CANONICAL" "$CWD_CANONICAL" ${PATHSPEC_TOKENS[@]+"${PATHSPEC_TOKENS[@]}"} > "$TMP/only-paths" 2>"$ONLY_ERR" <<'PY'
import os, subprocess, sys

repo, cwd = sys.argv[1], sys.argv[2]
tokens = sys.argv[3:]
if not tokens:
  sys.stderr.write("missing pathspecs")
  sys.exit(1)

repo_real = os.path.realpath(repo)
cwd_real = os.path.realpath(cwd)
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
head_ok = subprocess.run(["git", "-C", repo_real, "rev-parse", "--verify", "HEAD"], capture_output=True, env=env, timeout=3).returncode == 0

seen = set()
resolved = []
for tok in tokens:
  if not tok or tok.startswith(":"):
    sys.stderr.write(f"unsupported pathspec magic: {tok}")
    sys.exit(1)
  if any(ch in tok for ch in "*?[\\"):
    sys.stderr.write(f"glob or escape pathspec not allowed: {tok}")
    sys.exit(1)
  joined = tok if os.path.isabs(tok) else os.path.join(cwd_real, tok)
  norm = os.path.normpath(joined)
  try:
    rel = os.path.relpath(norm, repo_real)
  except ValueError:
    sys.stderr.write(f"path outside repository: {tok}")
    sys.exit(1)
  if rel in ("", ".") or rel == ".." or rel.startswith("../") or rel.startswith("/") or rel == ".git" or rel.startswith(".git/"):
    sys.stderr.write(f"path outside repository tree: {tok}")
    sys.exit(1)
  rel_posix = rel.replace(os.sep, "/")
  target = os.path.join(repo_real, rel)
  # Reject symlinks anywhere along the path inside the repo so a link cannot
  # redirect validation or commit outside the repository tree.
  walk = repo_real
  for part in rel_posix.split("/"):
    walk = os.path.join(walk, part)
    if os.path.islink(walk):
      sys.stderr.write(f"symlink path not allowed in --only commit: {rel_posix}")
      sys.exit(1)
  if os.path.isdir(target):
    sys.stderr.write(f"directory pathspec not allowed in --only commit: {rel_posix}")
    sys.exit(1)
  if head_ok:
    tree_check = subprocess.run(
      ["git", "-C", repo_real, "ls-tree", "-d", "HEAD", "--", f":(literal){rel_posix}"],
      capture_output=True, text=True, env=env, timeout=3,
    )
    if tree_check.returncode != 0 or tree_check.stdout.strip():
      sys.stderr.write(f"HEAD directory pathspec not allowed in --only commit: {rel_posix}")
      sys.exit(1)
  exists_wt = os.path.isfile(target)
  exists_head = False
  if head_ok:
    exists_head = subprocess.run(
      ["git", "-C", repo_real, "cat-file", "-e", f"HEAD:{rel_posix}"],
      capture_output=True, env=env, timeout=3,
    ).returncode == 0
  if not exists_wt and not exists_head:
    sys.stderr.write(f"path missing in both working tree and HEAD: {rel_posix}")
    sys.exit(1)
  # Do not let --only overwrite an existing staged version of the same path in
  # the shared index (e.g. another session staged a different snapshot). An
  # intent-to-add entry has index status ' ' (' A'), which remains allowed.
  st = subprocess.run(
    ["git", "-C", repo_real, "status", "--porcelain=v1", "-z", "--", f":(literal){rel_posix}"],
    capture_output=True, env=env, timeout=3,
  )
  if st.returncode != 0:
    sys.stderr.write(f"could not inspect shared index status for {rel_posix}")
    sys.exit(1)
  for entry in st.stdout.split(b"\0"):
    if len(entry) >= 4 and entry[:1] not in (b" ", b"?"):
      sys.stderr.write(f"path already staged in shared index: {rel_posix}")
      sys.exit(1)
  if rel_posix not in seen:
    seen.add(rel_posix)
    resolved.append(rel_posix)

sys.stdout.buffer.write(b"".join(p.encode("utf-8") + b"\0" for p in resolved))
PY
  then
    ONLY_REASON=$(cat "$ONLY_ERR" 2>/dev/null || echo "unverifiable pathspec")
    audit deny only-pathspec "$ONLY_REASON"
    deny "agent contract commit gate cannot safely inspect --only commit ($ONLY_REASON); stage files with git add and run git commit without pathspec"
    exit $?
  fi

  ONLY_REL_PATHS=()
  while IFS= read -r -d '' ONLY_REL; do
    ONLY_REL_PATHS+=("$ONLY_REL")
    if is_locked_surface "$ONLY_REL"; then
      audit deny pathspec "$ONLY_REL"
      deny "agent contract commit gate does not allow --only pathspec commits for locked surface $ONLY_REL; stage it with git add, issue a permit, then run git commit without pathspec"
      exit $?
    fi
  done < "$TMP/only-paths"

  if ! git -C "$REPO_CANONICAL" rev-parse --verify HEAD >/dev/null 2>&1; then
    audit deny only-unborn "$REPO_CANONICAL"
    deny 'agent contract commit gate cannot inspect --only commit on an unborn HEAD; stage with git add and run git commit without pathspec'
    exit $?
  fi

  ONLY_INDEX="$TMP/only.index"
  if ! GIT_INDEX_FILE="$ONLY_INDEX" git -C "$REPO_CANONICAL" read-tree HEAD >/dev/null 2>&1; then
    deny 'agent contract commit gate could not build temporary HEAD index for --only validation'
    exit $?
  fi
  for ONLY_REL in "${ONLY_REL_PATHS[@]}"; do
    if [ -f "$REPO_CANONICAL/$ONLY_REL" ] && [ ! -L "$REPO_CANONICAL/$ONLY_REL" ]; then
      if ! GIT_INDEX_FILE="$ONLY_INDEX" git -C "$REPO_CANONICAL" add -- ":(literal)$ONLY_REL" >/dev/null 2>&1; then
        deny "agent contract commit gate could not stage $ONLY_REL in temporary index for --only validation"
        exit $?
      fi
    elif [ ! -e "$REPO_CANONICAL/$ONLY_REL" ] && [ ! -L "$REPO_CANONICAL/$ONLY_REL" ]; then
      if ! GIT_INDEX_FILE="$ONLY_INDEX" git -C "$REPO_CANONICAL" rm --cached --ignore-unmatch -q -- ":(literal)$ONLY_REL" >/dev/null 2>&1; then
        deny "agent contract commit gate could not record deletion of $ONLY_REL in temporary index for --only validation"
        exit $?
      fi
    else
      deny "agent contract commit gate encountered unsupported file type for --only path $ONLY_REL"
      exit $?
    fi
  done

  # Classify the full candidate tree diff against HEAD, not only the literal
  # pathspecs: replacing a tracked file with a directory and committing a child
  # implicitly deletes the parent path, which may be locked or controlled.
  ONLY_DIFF_FILE="$TMP/only-diff-paths"
  if ! GIT_INDEX_FILE="$ONLY_INDEX" git -C "$REPO_CANONICAL" diff --cached --name-only --no-renames -z HEAD > "$ONLY_DIFF_FILE" 2>/dev/null; then
    deny 'agent contract commit gate could not compute candidate diff for --only validation'
    exit $?
  fi

  ONLY_MATCHED=0
  ONLY_SETTINGS_TOUCHED=0
  while IFS= read -r -d '' ONLY_DIFF_PATH; do
    if is_locked_surface "$ONLY_DIFF_PATH"; then
      audit deny pathspec "$ONLY_DIFF_PATH"
      deny "agent contract commit gate does not allow --only pathspec commits affecting locked surface $ONLY_DIFF_PATH; stage with git add, issue a permit, then run git commit without pathspec"
      exit $?
    fi
    if has_controlled_surface "$ONLY_DIFF_PATH"; then
      ONLY_MATCHED=1
    fi
    if [ "$GLOBAL_REPO" -eq 1 ] && [ "$ONLY_DIFF_PATH" = "settings.json" ]; then
      ONLY_SETTINGS_TOUCHED=1
    fi
  done < "$ONLY_DIFF_FILE"
  for ONLY_REL in "${ONLY_REL_PATHS[@]}"; do
    if has_controlled_surface "$ONLY_REL"; then
      ONLY_MATCHED=1
    fi
    if [ "$GLOBAL_REPO" -eq 1 ] && [ "$ONLY_REL" = "settings.json" ]; then
      ONLY_SETTINGS_TOUCHED=1
    fi
  done

  if [ "$ONLY_MATCHED" -eq 0 ]; then
    exit 0
  fi

  PROJECTION="$TMP/projection"
  mkdir -p "$PROJECTION"
  if ! GIT_INDEX_FILE="$ONLY_INDEX" git -C "$REPO_CANONICAL" checkout-index --all --prefix="$PROJECTION/" >/dev/null 2>&1; then
    deny 'agent contract commit gate could not project temporary index for --only validation'
    exit $?
  fi

  run_validator_on_projection

  if [ "$GLOBAL_REPO" -eq 1 ] && [ "$ONLY_SETTINGS_TOUCHED" -eq 1 ] && ! settings_registration_present; then
    deny 'locked agent contract gate registration is missing from settings.json in --only commit'
    exit $?
  fi

  for ONLY_REL in "${ONLY_REL_PATHS[@]}"; do
    if [ -f "$PROJECTION/$ONLY_REL" ]; then
      if [ ! -f "$REPO_CANONICAL/$ONLY_REL" ] || [ -L "$REPO_CANONICAL/$ONLY_REL" ] || ! cmp -s "$PROJECTION/$ONLY_REL" "$REPO_CANONICAL/$ONLY_REL"; then
        deny "agent contract commit gate detected a working-tree change during --only validation: $ONLY_REL"
        exit $?
      fi
    else
      if [ -e "$REPO_CANONICAL/$ONLY_REL" ] || [ -L "$REPO_CANONICAL/$ONLY_REL" ]; then
        deny "agent contract commit gate detected a working-tree change during --only validation: $ONLY_REL"
        exit $?
      fi
    fi
  done

  audit allow only-commit "$REPO_CANONICAL"
  exit 0
fi

# Bootstrap is decided at the locked-surface check further down, not here. Asking
# "is the gate in HEAD?" globally would answer no for every project repo that has
# never adopted it, and allow-all is the wrong answer there. The question that
# matters is narrower: is *this* commit the one introducing the locked file it
# stages? That is asked in path_absent_from_head once the staged paths are known.

STATUS_FILE="$TMP/staged-status"
if ! git -C "$REPO" diff --cached --name-status -z > "$STATUS_FILE" 2>/dev/null; then
  deny 'agent contract commit gate could not inspect the staged index'
  exit $?
fi
WRITE_TREE_ERR="$TMP/write-tree.err"
if ! INDEX_TREE=$(git -C "$REPO" write-tree 2>"$WRITE_TREE_ERR"); then
  if grep -qi 'index\.lock' "$WRITE_TREE_ERR"; then
    deny 'agent contract commit gate could not snapshot the staged index: stale .git/index.lock detected; check for running git processes and remove the lock file if orphaned'
  else
    deny 'agent contract commit gate could not snapshot the staged index'
  fi
  exit $?
fi

MATCHED=0
LOCKED_PATH=
LOCKED_PATHS=
SETTINGS_TOUCHED=0
mark_path() {
  local path=$1
  if has_controlled_surface "$path"; then
    MATCHED=1
  fi
  if [ "$GLOBAL_REPO" -eq 1 ] && [ "$path" = "settings.json" ]; then
    SETTINGS_TOUCHED=1
  fi
  # Record every locked path, not just the first. The bootstrap exemption is
  # decided per path, so keeping only the first lets a commit that introduces a
  # new locked file carry a change to an existing one through on its exemption.
  if is_locked_surface "$path"; then
    LOCKED_PATHS="$LOCKED_PATHS$path
"
    [ -n "$LOCKED_PATH" ] || LOCKED_PATH=$path
  fi
}

while IFS= read -r -d '' STATUS; do
  case "$STATUS" in
    R*|C*)
      IFS= read -r -d '' OLD_PATH || {
        deny 'agent contract commit gate could not parse a staged rename'
        exit $?
      }
      IFS= read -r -d '' NEW_PATH || {
        deny 'agent contract commit gate could not parse a staged rename target'
        exit $?
      }
      mark_path "$OLD_PATH"
      mark_path "$NEW_PATH"
      ;;
    *)
      IFS= read -r -d '' PATH_VALUE || {
        deny 'agent contract commit gate could not parse a staged path'
        exit $?
      }
      mark_path "$PATH_VALUE"
      ;;
  esac
done < "$STATUS_FILE"

if [ "$AUTO_STAGE" = true ]; then
  POTENTIAL_FILE="$TMP/potential-paths"
  if ! {
    git -C "$REPO" diff --cached --name-only
    git -C "$REPO" diff --name-only
    git -C "$REPO" ls-files --others --exclude-standard
  } > "$POTENTIAL_FILE" 2>/dev/null; then
    deny 'agent contract commit gate could not inspect possible post-add paths'
    exit $?
  fi
  while IFS= read -r POTENTIAL_PATH; do
    [ -n "$POTENTIAL_PATH" ] || continue
    if has_controlled_surface "$POTENTIAL_PATH"; then
      deny "agent contract commit gate cannot safely inspect the post-add index for controlled path $POTENTIAL_PATH; run git add first, then run git commit"
      exit $?
    fi
  done < "$POTENTIAL_FILE"
fi

# pathspec 取工作樹內容，不能沿用 staged index 的驗證與 permit。
for PATHSPEC_TOKEN in ${PATHSPEC_TOKENS[@]+"${PATHSPEC_TOKENS[@]}"}; do
  PATHSPEC_REL=${PATHSPEC_TOKEN#"$REPO"/}
  PATHSPEC_REL=${PATHSPEC_REL#./}
  if has_controlled_surface "$PATHSPEC_REL"; then
    audit deny pathspec "$PATHSPEC_REL"
    deny "agent contract commit gate cannot safely inspect a pathspec commit naming controlled path $PATHSPEC_REL; stage it with git add, then run git commit without pathspec"
    exit $?
  fi
done

[ "$MATCHED" -eq 1 ] || exit 0

if [ -n "$EVALUATOR_DIRTY_REASON" ] && [ -n "$LOCKED_PATH" ]; then
  audit deny unstaged-locked "$EVALUATOR_DIRTY"
  deny "$EVALUATOR_DIRTY_REASON, so a commit that stages a locked path ($LOCKED_PATH) has no trustworthy judge. Ask the session editing $EVALUATOR_DIRTY to commit or revert it, commit without the locked path, or disable the gate with $SENTINEL"
  exit $?
fi

# Update path. A commit that stages a locked path needs a permit issued out of
# band by the user. The permit records the exact locked index entries it
# authorises and the gate compares them for equality, so it cannot be carried
# over to different content, and it is consumed on use. The
# marker is a reference to that permit, never the permit itself -- a value the
# commit carries about itself would be self-scored.
path_absent_from_head() {
  git -C "$REPO" cat-file -e "HEAD:$1" 2>/dev/null && return 1
  return 0
}

# Bootstrap path: a commit that only introduces locked files has nothing yet to
# protect and no earlier commit that could have carried a permit. The exemption
# is self-limiting -- it stops applying to a file the moment it reaches HEAD --
# and it is all-or-nothing: one staged locked path that HEAD already knows makes
# the whole commit need a permit, so a new file cannot escort a change to an old
# one through.
if [ -n "$LOCKED_PATH" ]; then
  LOCKED_IN_HEAD=
  while IFS= read -r locked; do
    [ -n "$locked" ] || continue
    if ! path_absent_from_head "$locked"; then
      LOCKED_IN_HEAD=$locked
      break
    fi
  done <<EOF
$LOCKED_PATHS
EOF
  if [ -z "$LOCKED_IN_HEAD" ]; then
    audit allow bootstrap "$LOCKED_PATH"
    LOCKED_PATH=
  else
    LOCKED_PATH=$LOCKED_IN_HEAD
  fi
fi

locked_entries() {
  git -C "$1" ls-files --stage -- 'hooks/T2-routing-gate*' hooks/review-spec-yagni-permit.py hooks/review-spec-yagni-permit.test.py scripts/agent-contract-validator.mjs 'scripts/agent-contract-command/*' hooks/agent-contract-validator-gate.sh hooks/agent-contract-validator-gate.test.sh hooks/agent-contract-gate-permit.sh '.claude/hooks/T2-routing-gate*' .claude/hooks/review-spec-yagni-permit.py .claude/hooks/review-spec-yagni-permit.test.py .claude/scripts/agent-contract-validator.mjs '.claude/scripts/agent-contract-command/*' .claude/hooks/agent-contract-validator-gate.sh .claude/hooks/agent-contract-validator-gate.test.sh .claude/hooks/agent-contract-gate-permit.sh 2>/dev/null | LC_ALL=C sort
}

if [ -n "$LOCKED_PATH" ]; then
  PERMIT_OK=0
  PERMIT_REASON='no permit'
  if [ -f "$PERMIT_FILE" ]; then
    PERMIT_EXPIRES=$(awk 'NR==1{print $1}' "$PERMIT_FILE" 2>/dev/null || true)
    PERMIT_SESSION=$(awk 'NR==1{print $2}' "$PERMIT_FILE" 2>/dev/null || true)
    PERMIT_ENTRIES=$(tail -n +2 "$PERMIT_FILE" 2>/dev/null || true)
    SESSION_ID=$(json_value session_id 2>/dev/null || true)
    STAGED_ENTRIES=$(locked_entries "$REPO")
    NOW=$(date -u '+%s')
    if ! printf '%s\n' "$PERMIT_EXPIRES" | grep -Eq '^[0-9]+$' || [ -z "$PERMIT_ENTRIES" ]; then
      PERMIT_REASON='permit is malformed'
    elif ! [ "$PERMIT_EXPIRES" -gt "$NOW" ] 2>/dev/null; then
      PERMIT_REASON='permit has expired'
    elif [ -z "$STAGED_ENTRIES" ] || [ "$PERMIT_ENTRIES" != "$STAGED_ENTRIES" ]; then
      PERMIT_REASON='permit was issued for different locked content'
    elif [ -n "$PERMIT_SESSION" ] && [ "$PERMIT_SESSION" != '-' ] && [ -n "$SESSION_ID" ] && [ "$PERMIT_SESSION" != "$SESSION_ID" ]; then
      PERMIT_REASON='permit was issued in another session'
    else
      PERMIT_OK=1
    fi
  fi
  if [ "$PERMIT_OK" -ne 1 ]; then
    audit deny locked-no-permit "$LOCKED_PATH"
    deny "locked agent contract gate surface needs a permit to change: $LOCKED_PATH ($PERMIT_REASON). Ask the user to run: ! ~/.claude/hooks/agent-contract-gate-permit.sh issue -- then run git commit by itself (git add is a separate command; do not restage after the permit is issued). The permit is consumed only when the commit passes every check, so a failed validation keeps it for the retry"
    exit $?
  fi
fi

PROJECTION="$TMP/projection"
mkdir -p "$PROJECTION"
if ! git -C "$REPO" checkout-index --all --prefix="$PROJECTION/" >/dev/null 2>&1; then
  deny 'agent contract commit gate could not project the staged index'
  exit $?
fi

run_validator_on_projection

if ! CURRENT_INDEX_TREE=$(git -C "$REPO" write-tree 2>/dev/null); then
  deny 'agent contract commit gate could not recheck the staged index'
  exit $?
fi
if [ "$CURRENT_INDEX_TREE" != "$INDEX_TREE" ]; then
  deny 'agent contract commit gate detected a staged index change during validation'
  exit $?
fi
if [ "$GLOBAL_REPO" -eq 1 ] && [ "$SETTINGS_TOUCHED" -eq 1 ] && ! settings_registration_present; then
  deny 'locked agent contract gate registration is missing from staged settings.json'
  exit $?
fi
if [ -n "$LOCKED_PATH" ]; then
  rm -f "$PERMIT_FILE" 2>/dev/null || true
  audit allow locked-permit "$LOCKED_PATH"
fi
exit 0
