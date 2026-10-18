#!/bin/bash
# 記憶引用的 hook／script／local-bin 工具「接線」檢查：一行一筆
#   <MISSING|UNWIRED|OK> <ref> ← <memory file>:<line>
# 任何內部失敗只印 WIRED-CHECK-UNAVAILABLE 並非零退出，讓 memory channel 能寫「本輪未查」，
# 而不是把半套結果當成「乾淨」。
# UNWIRED 只是候選：「檔名沒出現在設定」不等於退役，channel 要再做 ledger cross-check。
set -uo pipefail

UNAVAILABLE='WIRED-CHECK-UNAVAILABLE'
unavailable() {
  printf '%s\n' "$UNAVAILABLE"
  [ $# -gt 0 ] && printf 'memory-wired-audit: %s\n' "$*" >&2
  exit 3
}

# 唯一正式呼叫端（commands/memory-audit.md H-2）不帶參數；fixture 只需要換根目錄，所以只留兩個環境變數。
root="${WIRED_ROOT:-$HOME/.claude}"
memory_dir="$root/memory"
hooks_dir="$root/hooks"
commands_dir="$root/commands"
skills_dir="$root/skills"
scripts_dir="$root/scripts"
bin_dir="${WIRED_BIN_DIR:-$HOME/.local/bin}"
settings_files=("$root/settings.json" "$root/settings.local.json")
[ $# -eq 0 ] || unavailable "takes no arguments; set WIRED_ROOT / WIRED_BIN_DIR instead"

# 根目錄指錯時結果全是 MISSING／UNWIRED，比沒跑更誤導，所以一律當內部失敗。
for d in "$memory_dir" "$hooks_dir" "$commands_dir" "$skills_dir" "$scripts_dir" "$bin_dir"; do
  [ -d "$d" ] || unavailable "directory not found: $d"
done
existing_settings=()
for f in "${settings_files[@]}"; do
  [ -f "$f" ] && existing_settings+=("$f")
done
[ ${#existing_settings[@]} -gt 0 ] || unavailable "no settings file found: ${settings_files[*]}"

# heredoc 不放進 $(...)：bash 會在命令替換裡解析 Python 字串中的反引號而炸掉。
read -r -d '' py_code <<'PY'
import os
import re
import sys

memory_dir, hooks_dir, commands_dir, skills_dir, scripts_dir, bin_dir = sys.argv[1:7]
settings = sys.argv[7:]

NAME = r"[A-Za-z0-9._-]+"
PREFIX = r"(?:(?:~|\$HOME|/Users/[^/\s`]+)/\.claude/)"
# 前面接 `/` 的 `.claude/hooks/` 是專案級 hook，不屬本檢查範圍，所以裸前綴要求前一字元不是路徑字元。
HOOK_RE = re.compile(r"(?:" + PREFIX + r"|(?<![A-Za-z0-9._/~-]))hooks/(" + NAME + r"\.(?:sh|py|mjs|js))(?![A-Za-z0-9._-])")
SCRIPT_RE = re.compile(r"(" + PREFIX + r"|(?<![A-Za-z0-9._/~-]))scripts/(" + NAME + r"\.(?:sh|py|mjs))(?![A-Za-z0-9._-])")
BIN_RE = re.compile(r"(?:~|\$HOME|/Users/[^/\s`]+)/\.local/bin/(" + NAME + r")")
# 照 commands/memory-audit.md H 維度的 SELF_NOTE 判定：同一 clause 內已自述退役／歷史就不列；兩份 regex 要同步改。
SELF_NOTE_RE = re.compile(r"已.{0,40}(刪除|移除|退役|結案)|現已不存在|歷史(記錄|紀錄|實例)|示意|若存在")
SEPARATORS = ",，;；:：。！？"


def is_placeholder(name):
    stem = name.split(".", 1)[0] if not name.startswith(".") else name
    if len(stem) <= 1 or "..." in name or "YYYY" in name or "MM-DD" in name:
        return True
    if name.endswith("-") or ".test." in name or ".bak" in name:
        return True
    return not re.search(r"[A-Za-z0-9]", stem)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except (IsADirectoryError, FileNotFoundError):
        return ""


def walk(root, keep, skip_dirs=()):
    # skills/ 下有 symlink 目錄（2026-09-25 實測 16 個），不跟進去會把裡面的引用當成沒接線。
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
        for fn in sorted(filenames):
            if keep(fn):
                yield os.path.join(dirpath, fn)


def is_script(fn):
    return fn.endswith((".sh", ".py", ".mjs", ".js")) and ".test." not in fn and ".bak" not in fn


# test 檔引用 hook 不算接線，state/ 是 hook 的執行紀錄，也不算。
sources = [(p, read(p)) for p in settings]
sources += [(p, read(p)) for p in walk(hooks_dir, is_script, skip_dirs=("state", "__pycache__"))]
launchd_dir = os.environ.get("WIRED_LAUNCHD_DIR", os.path.expanduser("~/Library/LaunchAgents"))
if os.path.isdir(launchd_dir):
    sources += [(p, read(p)) for p in walk(launchd_dir, lambda f: f.endswith(".plist"))]
sources += [(p, read(p)) for p in walk(commands_dir, lambda f: f.endswith(".md"))]
sources += [(p, read(p)) for p in walk(skills_dir, lambda f: f.endswith(".md"))]
# rules/、references/、agents/ 的 md 與 ~/.zshrc alias 也會引用 scripts／hooks／tools：
# 2026-10-16 抽查 10 條 UNWIRED 有 6 條是這幾類假陽性（upstream-pr-bundle.sh、gpt-model-scan.py、cli-radar.sh…）。
root_dir = os.path.dirname(os.path.normpath(memory_dir))
for sub in ("rules", "references", "agents"):
    d = os.path.join(root_dir, sub)
    if os.path.isdir(d):
        sources += [(p, read(p)) for p in walk(d, lambda f: f.endswith(".md"))]
# workflows/ 的 .sh／.js 會呼叫 scripts/ 內腳本（2026-10-17：failure-mode-daily.py 只被 workflows/failure-mode-daily.sh 呼叫，被判 UNWIRED）。
workflows_dir = os.path.join(root_dir, "workflows")
if os.path.isdir(workflows_dir):
    sources += [(p, read(p)) for p in walk(workflows_dir, is_script)]
zshrc = os.environ.get("WIRED_ZSHRC", os.path.expanduser("~/.zshrc"))
if os.path.isfile(zshrc):
    sources.append((zshrc, read(zshrc)))
# scripts/ 與 workflows/ 內的檔只在「自己已被上面的來源點名」時才算來源（一層傳遞）：
# 腳本間互呼叫（例如 A.sh → B.sh、lib/resolve-account.sh → usage-color.sh）原本看不到
#（2026-10-15 抽查 10 條 UNWIRED 有 3 條是這種假陽性）；但沒人接線的 wrapper 提到某工具不能反過來
# 讓那個工具變 OK（dcg 事故：wrapper 從 settings 拆線後，記憶還寫著要過 dcg），所以不整個目錄照單全收。
base_text = "\n".join(text for _, text in sources)
def transitive(dir_path, prefix):
    out = []
    if not os.path.isdir(dir_path):
        return out
    for p in walk(dir_path, is_script, skip_dirs=("tests", "__pycache__")):
        rel = os.path.relpath(p, dir_path)
        if prefix + rel in base_text:
            out.append((p, read(p)))
    return out
sources += transitive(scripts_dir, "scripts/")
sources += transitive(os.path.join(root_dir, "workflows"), "workflows/")

tools = set()
for fn in os.listdir(bin_dir):
    p = os.path.join(bin_dir, fn)
    if os.path.isfile(p) and os.access(p, os.X_OK):
        tools.add(fn)
# 兩個字母以下的工具名（uv、hb…）在散文裡跟一般字詞撞太多，只認完整路徑寫法。
bare_tools = sorted((t for t in tools if len(t) >= 3 and not is_placeholder(t)), key=len, reverse=True)
BARE_RE = None
if bare_tools:
    BARE_RE = re.compile(
        r"(?<![A-Za-z0-9_./~-])(" + "|".join(re.escape(t) for t in bare_tools) + r")(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9])"
    )

wired_cache = {}


def mentioned(name, exclude, tool):
    key = (name, exclude, tool)
    if key in wired_cache:
        return wired_cache[key]
    # 工具名允許接 `-`，讓 `dcg-wrapper.sh` 這類 wrapper 被提到也算接線；檔名則要完整比對。
    if tool:
        pat = re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"(?![A-Za-z0-9_])")
    else:
        pat = re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(name) + r"(?![A-Za-z0-9_.-])")
    hit = any(p not in exclude and pat.search(text) for p, text in sources)
    wired_cache[key] = hit
    return hit


def classify_file(base_dir, name):
    path = os.path.join(base_dir, name)
    if not os.path.isfile(path):
        return "MISSING"
    return "OK" if mentioned(name, (path,), False) else "UNWIRED"


def classify_tool(name):
    if name not in tools:
        return "MISSING"
    return "OK" if mentioned(name, (), True) else "UNWIRED"


def refs_on_line(line):
    found = []
    for m in HOOK_RE.finditer(line):
        name = m.group(1)
        if not is_placeholder(name):
            found.append((m.start(), "hooks/" + name, lambda n=name: classify_file(hooks_dir, n)))
    for m in SCRIPT_RE.finditer(line):
        name = m.group(2)
        if is_placeholder(name):
            continue
        # 裸 `scripts/x.sh` 常指其他 repo 的 scripts/，找不到時不能斷言 MISSING。
        explicit = bool(m.group(1))
        found.append((m.start(), "scripts/" + name, lambda n=name, e=explicit: classify_file(scripts_dir, n) if e or os.path.exists(os.path.join(scripts_dir, n))  else None))
    for m in BIN_RE.finditer(line):
        name = m.group(1)
        if not is_placeholder(name):
            found.append((m.start(), name, lambda n=name: classify_tool(n)))
    if BARE_RE:
        for m in BARE_RE.finditer(line):
            found.append((m.start(), m.group(1), lambda n=m.group(1): classify_tool(n)))
    return sorted(found, key=lambda r: r[0])


CORRECTION_LINE_RE = re.compile(r"^\s*>\s*更正行 ")


def self_noted(line, refs, index):
    # 當場修留下的更正行整行都是歷史敘述，不看 clause。
    if CORRECTION_LINE_RE.match(line):
        return True
    start = refs[index][0]
    seg_start = max((line.rfind(sep, 0, start) for sep in SEPARATORS), default=-1) + 1
    seg_end = next((r[0] for r in refs[index + 1:] if r[0] > start), len(line))
    return bool(SELF_NOTE_RE.search(line[seg_start:seg_end]))


memory_files = sorted(walk(memory_dir, lambda f: f.endswith(".md"), skip_dirs=("archive",)))
seen = set()
for path in memory_files:
    rel = os.path.relpath(path, memory_dir)
    for lineno, line in enumerate(read(path).splitlines(), 1):
        refs = refs_on_line(line)
        for i, (_, ref, classify) in enumerate(refs):
            if (ref, rel, lineno) in seen or self_noted(line, refs, i):
                continue
            state = classify()
            if state is None:
                continue
            seen.add((ref, rel, lineno))
            print(f"{state} {ref} ← {rel}:{lineno}")
PY

out=$(python3 -c "$py_code" "$memory_dir" "$hooks_dir" "$commands_dir" "$skills_dir" "$scripts_dir" "$bin_dir" "${existing_settings[@]}") \
  || unavailable "audit failed"

[ -n "$out" ] && printf '%s\n' "$out"
exit 0
