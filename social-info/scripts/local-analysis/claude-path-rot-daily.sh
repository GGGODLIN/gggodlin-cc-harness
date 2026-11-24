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
AGENT_HOME="${PATH_ROT_AGENT_HOME:-$HOME}"
WHITELIST="${PATH_ROT_WHITELIST:-$REPO_DIR/scripts/local-analysis/path-rot-whitelist.txt}"
mkdir -p "$OUT_DIR" "$LOG_DIR"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

log "═══ claude path rot check ($DATE) root=$CLAUDE_ROOT agent_home=$AGENT_HOME ═══"

RESULT=$(python3 - "$CLAUDE_ROOT" "$WHITELIST" "$AGENT_HOME" <<'PY'
import os, re, sys, glob, json

root, whitelist_path, agent_home = sys.argv[1], sys.argv[2], sys.argv[3]
home = os.path.expanduser("~")
agent_home_prefix = agent_home.rstrip("/")

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

# --- 跨 coding agent hook 設定與外掛斷頭檢查 ---
scanned_agent_files = 0
claude_rel_re = re.compile(r"^.*?/\.claude(?:-max|-team)?/(.*)$")
home_prefix_pat = (re.escape(agent_home_prefix) + r"/") if agent_home_prefix else r"/"
cmd_path_re = re.compile(r"(?<![A-Za-z0-9_./-])(?:~/|" + home_prefix_pat + r")[^\s'\"`;|&]+")

def is_safe_agent_file(path):
    if not os.path.isfile(path):
        return False
    real_p = os.path.realpath(path)
    real_home = os.path.realpath(agent_home)
    if not (real_p == real_home or real_p.startswith(real_home + os.sep)):
        return False
    return True

def find_first_line(lines, needles, fallback):
    for i, ln_text in enumerate(lines, 1):
        for nd in needles:
            if nd in ln_text:
                return i
    return fallback

def iter_hook_commands(node, key_path):
    if isinstance(node, dict):
        cmd_val = node.get("command")
        if isinstance(cmd_val, str):
            yield (f"{key_path}.command" if key_path else "command", cmd_val)
        elif isinstance(cmd_val, list):
            for idx, item in enumerate(cmd_val):
                if isinstance(item, str):
                    yield (f"{key_path}.command[{idx}]" if key_path else f"command[{idx}]", item)
        for k, v in node.items():
            if k == "command":
                continue
            child_path = f"{key_path}.{k}" if key_path else k
            yield from iter_hook_commands(v, child_path)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            yield from iter_hook_commands(item, f"{key_path}[{idx}]")

def check_json_hook_file(cfg_path, rel_cfg_path, hooks_subtree_only):
    global scanned_agent_files, checked
    if not is_safe_agent_file(cfg_path):
        return
    try:
        text = open(cfg_path, encoding="utf-8", errors="replace").read()
        data = json.loads(text)
    except Exception:
        return
    scanned_agent_files += 1
    if hooks_subtree_only:
        if not isinstance(data, dict) or not isinstance(data.get("hooks"), (dict, list)):
            return
        roots = [(data["hooks"], "hooks")]
    else:
        roots = [(data, "")]
    lines = text.split("\n")
    source = f"~/{rel_cfg_path}"
    for root_node, root_key in roots:
        for key_path, cmd in iter_hook_commands(root_node, root_key):
            cmd_norm = cmd.replace("${HOME}", agent_home_prefix).replace("$HOME", agent_home_prefix)
            for m in cmd_path_re.finditer(cmd_norm):
                raw = m.group(0).rstrip(".,;:)'\"")
                if any(c in raw for c in skip_chars) or placeholder_re.search(raw):
                    continue
                if raw.endswith("/"):
                    continue
                if raw.startswith("~/"):
                    rel_from_home = raw[2:]
                    tilde_path = raw
                    abs_path = (agent_home_prefix + "/" + rel_from_home) if agent_home_prefix else ("/" + rel_from_home)
                else:
                    rel_from_home = raw[len(agent_home_prefix) + 1:]
                    tilde_path = "~/" + rel_from_home
                    abs_path = raw
                if not rel_from_home:
                    continue
                cm = claude_rel_re.match(tilde_path)
                if cm and is_runtime(cm.group(1)):
                    continue
                if tilde_path.endswith("-state.json"):
                    continue
                dedup_key = (cfg_path, tilde_path)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                if tilde_path in whitelist or abs_path in whitelist:
                    continue
                checked += 1
                if not os.path.exists(abs_path):
                    needles = [
                        tilde_path,
                        "$HOME/" + rel_from_home,
                        "${HOME}/" + rel_from_home,
                        abs_path,
                    ]
                    loc = find_first_line(lines, needles, key_path)
                    broken.append((source, loc, tilde_path))

hooks_only_rel_paths = [
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".codex/hooks.json",
    ".codex/hooks/cc-hooks.json",
    ".gemini/settings.json",
    ".cursor/hooks.json",
    ".qwen/settings.json",
    ".openclaude/settings.json",
    ".commandcode/settings.json",
]
for rel_p in hooks_only_rel_paths:
    check_json_hook_file(os.path.join(agent_home, rel_p), rel_p, True)

full_hook_rel_paths = [".gemini/config/hooks.json"]
for glob_pat in (".copilot/hooks/*.json", ".grok/hooks/*.json"):
    for p in sorted(glob.glob(os.path.join(agent_home, glob_pat))):
        full_hook_rel_paths.append(os.path.relpath(p, agent_home))
for rel_p in full_hook_rel_paths:
    check_json_hook_file(os.path.join(agent_home, rel_p), rel_p, False)

# 外掛檔（.ts / .js）字串常值內隱藏目錄根檢查
js_token_re = re.compile(r"""//[^\n]*|/\*[\s\S]*?\*/|(['"`])((?:\\.|(?!\1)[^\\])*)\1""")
dotdir_re = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:~/|\$HOME/|\$\{HOME\}/|" + home_prefix_pat + r")(\.[A-Za-z0-9][A-Za-z0-9_.\-]*)(?:/|$|[^A-Za-z0-9_.\-])"
)
plugin_globs = (
    ".pi/agent/extensions/*.ts",
    ".pi/agent/extensions/*.js",
    ".config/opencode/plugins/*.ts",
    ".config/opencode/plugins/*.js",
    ".config/amp/plugins/*.ts",
    ".config/amp/plugins/*.js",
)
for glob_pat in plugin_globs:
    for p in sorted(glob.glob(os.path.join(agent_home, glob_pat))):
        if not is_safe_agent_file(p):
            continue
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        scanned_agent_files += 1
        rel_plugin = os.path.relpath(p, agent_home)
        source = f"~/{rel_plugin}"
        for tm in js_token_re.finditer(text):
            lit = tm.group(2)
            if lit is None:
                continue
            lineno = text.count("\n", 0, tm.start()) + 1
            for dm in dotdir_re.finditer(lit):
                dotdir = dm.group(1)
                if any(c in dotdir for c in skip_chars) or placeholder_re.search(dotdir):
                    continue
                tilde_dotdir = f"~/{dotdir}"
                abs_dotdir = os.path.join(agent_home, dotdir)
                dedup_key = (p, tilde_dotdir)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                if tilde_dotdir in whitelist or abs_dotdir in whitelist:
                    continue
                checked += 1
                if not os.path.exists(abs_dotdir):
                    broken.append((source, lineno, tilde_dotdir))

# .hermes/config.yaml plugins.enabled 檢查
hermes_cfg = os.path.join(agent_home, ".hermes", "config.yaml")
if is_safe_agent_file(hermes_cfg):
    try:
        htext = open(hermes_cfg, encoding="utf-8", errors="replace").read()
    except Exception:
        htext = None
    if htext is not None:
        scanned_agent_files += 1
        in_plugins = False
        plugins_indent = -1
        in_enabled = False
        enabled_indent = -1
        hermes_enabled = []

        def strip_yaml_comment(s):
            in_q = None
            for idx, ch in enumerate(s):
                if ch in ("'", '"'):
                    if in_q is None:
                        in_q = ch
                    elif in_q == ch:
                        in_q = None
                elif ch == "#" and in_q is None:
                    return s[:idx]
            return s

        for lineno, raw_line in enumerate(htext.split("\n"), 1):
            clean = strip_yaml_comment(raw_line).rstrip()
            if not clean.strip():
                continue
            indent = len(clean) - len(clean.lstrip(" "))
            stripped = clean.strip()

            if in_plugins and indent <= plugins_indent and not stripped.startswith("-"):
                in_plugins = False
                in_enabled = False

            if not in_plugins:
                if re.match(r"^plugins\s*:", stripped):
                    in_plugins = True
                    plugins_indent = indent
                    in_enabled = False
                continue

            if in_enabled:
                if indent < enabled_indent or (indent == enabled_indent and not stripped.startswith("-")):
                    in_enabled = False
                elif stripped.startswith("-"):
                    item = stripped[1:].strip().strip("'\"")
                    if item:
                        hermes_enabled.append((lineno, item))
                    continue

            em = re.match(r"^enabled\s*:\s*(.*)$", stripped)
            if em:
                rest = em.group(1).strip()
                if rest.startswith("[") and rest.endswith("]"):
                    for part in rest[1:-1].split(","):
                        item = part.strip().strip("'\"")
                        if item:
                            hermes_enabled.append((lineno, item))
                    in_enabled = False
                elif rest == "":
                    in_enabled = True
                    enabled_indent = indent
                else:
                    in_enabled = False

        for lineno, plugin_name in hermes_enabled:
            if not plugin_name or "/" in plugin_name or ".." in plugin_name or any(c in plugin_name for c in skip_chars):
                continue
            tilde_plugin = f"~/.hermes/plugins/{plugin_name}"
            abs_plugin = os.path.join(agent_home, ".hermes", "plugins", plugin_name)
            dedup_key = (hermes_cfg, tilde_plugin)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            if tilde_plugin in whitelist or abs_plugin in whitelist:
                continue
            checked += 1
            if not os.path.exists(abs_plugin):
                broken.append(("~/.hermes/config.yaml", lineno, tilde_plugin))

print(json.dumps({"files": len(scan_files) + scanned_agent_files, "checked": checked, "broken": broken}, ensure_ascii=False))
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
  echo "**目標**：\`CLAUDE.md\` / \`rules/\` / \`skills/*/SKILL.md\` / \`commands/\` / \`agents/\` / \`references/\` 內以 \`~/.claude/\` 或絕對路徑寫死的檔案引用，以及跨 coding agent hook 設定（\`~/.claude/settings*.json\`、\`~/.codex/\`、\`~/.gemini/\`、\`~/.cursor/\`、\`~/.qwen/\`、\`~/.openclaude/\`、\`~/.commandcode/\`、\`~/.copilot/hooks/\`、\`~/.grok/hooks/\`）與外掛引用（\`.pi\` / \`opencode\` / \`amp\` / \`.hermes\`），逐一驗證仍存在。只報告不修改；含 glob／變數的路徑跳過；白名單：\`$WHITELIST\`。"
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
