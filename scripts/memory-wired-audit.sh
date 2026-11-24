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
from bisect import bisect_right
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


def read_bytes(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (IsADirectoryError, FileNotFoundError):
        return b""


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
sources = [(p, read_bytes(p)) for p in settings]
sources += [(p, read_bytes(p)) for p in walk(hooks_dir, is_script, skip_dirs=("state", "__pycache__"))]
launchd_dir = os.environ.get("WIRED_LAUNCHD_DIR", os.path.expanduser("~/Library/LaunchAgents"))
if os.path.isdir(launchd_dir):
    sources += [(p, read_bytes(p)) for p in walk(launchd_dir, lambda f: f.endswith(".plist"))]
sources += [(p, read_bytes(p)) for p in walk(commands_dir, lambda f: f.endswith(".md"))]
sources += [(p, read_bytes(p)) for p in walk(skills_dir, lambda f: f.endswith(".md"))]
# rules/、references/、agents/ 的 md 與 ~/.zshrc alias 也會引用 scripts／hooks／tools：
# 2026-10-16 抽查 10 條 UNWIRED 有 6 條是這幾類假陽性（upstream-pr-bundle.sh、gpt-model-scan.py、cli-radar.sh…）。
root_dir = os.path.dirname(os.path.normpath(memory_dir))
for sub in ("rules", "references", "agents"):
    d = os.path.join(root_dir, sub)
    if os.path.isdir(d):
        sources += [(p, read_bytes(p)) for p in walk(d, lambda f: f.endswith(".md"))]
# workflows/ 的 .sh／.js 會呼叫 scripts/ 內腳本（2026-10-17：failure-mode-daily.py 只被 workflows/failure-mode-daily.sh 呼叫，被判 UNWIRED）。
workflows_dir = os.path.join(root_dir, "workflows")
if os.path.isdir(workflows_dir):
    sources += [(p, read_bytes(p)) for p in walk(workflows_dir, is_script)]
zshrc = os.environ.get("WIRED_ZSHRC", os.path.expanduser("~/.zshrc"))
if os.path.isfile(zshrc):
    sources.append((zshrc, read_bytes(zshrc)))
# scripts/ 與 workflows/ 內的檔只在「自己已被上面的來源點名」時才算來源（一層傳遞）：
# 腳本間互呼叫（例如 A.sh → B.sh、lib/resolve-account.sh → usage-color.sh）原本看不到
#（2026-10-15 抽查 10 條 UNWIRED 有 3 條是這種假陽性）；但沒人接線的 wrapper 提到某工具不能反過來
# 讓那個工具變 OK（dcg 事故：wrapper 從 settings 拆線後，記憶還寫著要過 dcg），所以不整個目錄照單全收。
base_bytes = b"\n".join(data for _, data in sources)
def transitive(dir_path, prefix):
    out = []
    if not os.path.isdir(dir_path):
        return out
    candidates = [
        (p, os.path.relpath(p, dir_path).encode("utf-8"))
        for p in walk(dir_path, is_script, skip_dirs=("tests", "__pycache__"))
    ]
    if not candidates:
        return out
    max_rel = max(len(rel) for _, rel in candidates)
    prefix_b = prefix.encode("utf-8")
    plen = len(prefix_b)
    by_two = {}
    find = base_bytes.find
    pos = find(prefix_b)
    while pos != -1:
        after = pos + plen
        snip = base_bytes[after:after + max_rel]
        if len(snip) >= 2:
            key = snip[:2]
            bucket = by_two.get(key)
            if bucket is None:
                by_two[key] = [snip]
            else:
                bucket.append(snip)
        pos = find(prefix_b, pos + 1)
    for p, rel in candidates:
        bucket = by_two.get(rel[:2])
        if bucket and any(s.startswith(rel) for s in bucket):
            out.append((p, read_bytes(p)))
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
_WORD_ONLY_RE = re.compile(r"[A-Za-z0-9_-]+")
_ALNUM = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
_BARE_NEXT_BAD = _ALNUM | {"_", "-"}
_BARE_PREV_ALL = _BARE_NEXT_BAD | {".", "/", "~"}
_ALNUM_B = bytes(i in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789" for i in range(256))
_BARE_NEXT_BAD_B = bytes(i in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for i in range(256))
_BARE_PREV_ALL_B = bytes(i in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./~-" for i in range(256))
bare_word_tools = set()
bare_special_tools = ()
bare_word_bytes = set()
bare_special_bytes = ()
if bare_tools:
    BARE_RE = re.compile(
        r"(?<![A-Za-z0-9_./~-])(" + "|".join(re.escape(t) for t in bare_tools) + r")(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9])"
    )
    bare_word_tools = {t for t in bare_tools if _WORD_ONLY_RE.fullmatch(t)}
    bare_special_tools = tuple(t for t in bare_tools if t not in bare_word_tools)
    bare_word_bytes = {t.encode("ascii") for t in bare_word_tools}
    bare_special_bytes = tuple(t.encode("utf-8") for t in bare_special_tools)

all_sources_bytes = b"\x00".join(data for _, data in sources)
all_sources_len = len(all_sources_bytes)
source_ends = []
source_paths = []
source_datas_by_path = {}
_off = 0
for _p, _d in sources:
    _off += len(_d)
    source_ends.append(_off)
    source_paths.append(_p)
    _bucket = source_datas_by_path.get(_p)
    if _bucket is None:
        source_datas_by_path[_p] = [_d]
    else:
        _bucket.append(_d)
    _off += 1

_ALNUM_UNDER_BYTES = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
_FILE_CHARS_BYTES = _ALNUM_UNDER_BYTES + b".-"
_ALNUM_UNDER_SET = frozenset(_ALNUM_UNDER_BYTES)
_FILE_CHARS_SET = frozenset(_FILE_CHARS_BYTES)
_PREV_TOOL_B = bytes(i in (_ALNUM_UNDER_BYTES + b".") for i in range(256))
_NEXT_TOOL_B = bytes(i in _ALNUM_UNDER_BYTES for i in range(256))
_BOTH_FILE_B = bytes(i in _FILE_CHARS_BYTES for i in range(256))
_TBL_FILE = bytes(i if i in _FILE_CHARS_SET else 32 for i in range(256))
file_tokens = set(all_sources_bytes.translate(_TBL_FILE).split())
unique_tokens_bytes = None
wired_cache = {}


def _find_with_bounds(haystack, needle, prev_bad, next_bad, exclude):
    hlen = len(haystack)
    nlen = len(needle)
    find = haystack.find
    pos = find(needle)
    while pos != -1:
        end = pos + nlen
        if (pos == 0 or not prev_bad[haystack[pos - 1]]) and (
            end == hlen or not next_bad[haystack[end]]
        ):
            if not exclude or source_paths[bisect_right(source_ends, pos)] not in exclude:
                return True
        pos = find(needle, pos + 1)
    return False


def mentioned(name, exclude, tool):
    global unique_tokens_bytes
    key = (name, exclude, tool)
    if key in wired_cache:
        return wired_cache[key]
    name_b = name.encode("utf-8")
    # 工具名允許接 `-`，讓 `dcg-wrapper.sh` 這類 wrapper 被提到也算接線；檔名則要完整比對。
    if tool:
        if all(b in _FILE_CHARS_SET for b in name_b):
            if unique_tokens_bytes is None:
                unique_tokens_bytes = b"\x00".join(file_tokens)
            hit = _find_with_bounds(unique_tokens_bytes, name_b, _PREV_TOOL_B, _NEXT_TOOL_B, ())
        else:
            hit = _find_with_bounds(all_sources_bytes, name_b, _PREV_TOOL_B, _NEXT_TOOL_B, ())
    else:
        if name_b not in file_tokens:
            hit = False
        elif not exclude:
            hit = True
        else:
            own_datas = source_datas_by_path.get(exclude[0])
            if not own_datas or all(name_b not in d for d in own_datas):
                hit = True
            else:
                hit = _find_with_bounds(all_sources_bytes, name_b, _BOTH_FILE_B, _BOTH_FILE_B, exclude)
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


def refs_on_line(line, has_hook, has_script, has_bin, has_special, line_words):
    found = []
    if has_hook and "hooks/" in line:
        for m in HOOK_RE.finditer(line):
            name = m.group(1)
            if not is_placeholder(name):
                found.append((m.start(), "hooks/" + name, lambda n=name: classify_file(hooks_dir, n)))
    if has_script and "scripts/" in line:
        for m in SCRIPT_RE.finditer(line):
            name = m.group(2)
            if is_placeholder(name):
                continue
            # 裸 `scripts/x.sh` 常指其他 repo 的 scripts/，找不到時不能斷言 MISSING。
            explicit = bool(m.group(1))
            found.append((m.start(), "scripts/" + name, lambda n=name, e=explicit: classify_file(scripts_dir, n) if e or os.path.exists(os.path.join(scripts_dir, n))  else None))
    if has_bin and "/.local/bin/" in line:
        for m in BIN_RE.finditer(line):
            name = m.group(1)
            if not is_placeholder(name):
                found.append((m.start(), name, lambda n=name: classify_tool(n)))
    if BARE_RE:
        if has_special and any(t in line for t in bare_special_tools):
            for m in BARE_RE.finditer(line):
                found.append((m.start(), m.group(1), lambda n=m.group(1): classify_tool(n)))
        elif line_words:
            llen = len(line)
            find = line.find
            for tok in line_words:
                tlen = len(tok)
                pos = find(tok)
                while pos != -1:
                    end = pos + tlen
                    if (pos == 0 or line[pos - 1] not in _BARE_PREV_ALL) and (
                        end == llen
                        or (
                            line[end] not in _BARE_NEXT_BAD
                            and not (end + 1 < llen and line[end] == "." and line[end + 1] in _ALNUM)
                        )
                    ):
                        found.append((pos, tok, lambda n=tok: classify_tool(n)))
                    pos = find(tok, pos + 1)
    if len(found) > 1:
        found.sort(key=lambda r: r[0])
    return found


CORRECTION_LINE_RE = re.compile(r"^\s*>\s*更正行 ")


def self_noted(line, refs, index):
    start = refs[index][0]
    seg_start = max((line.rfind(sep, 0, start) for sep in SEPARATORS), default=-1) + 1
    seg_end = next((r[0] for r in refs[index + 1:] if r[0] > start), len(line))
    return bool(SELF_NOTE_RE.search(line[seg_start:seg_end]))


_BARE_CHARS_SET = frozenset(_ALNUM_UNDER_BYTES + b"-")
_TBL_BARE = bytes(i if i in _BARE_CHARS_SET else 32 for i in range(256))
memory_files = sorted(walk(memory_dir, lambda f: f.endswith(".md"), skip_dirs=("archive",)))
seen = set()
out_lines = []


def _emit_line(rel, lineno, line, has_hook, has_script, has_bin, has_special, line_words):
    # 當場修留下的更正行整行都是歷史敘述，不看 clause。
    if "更正行 " in line and CORRECTION_LINE_RE.match(line):
        return
    refs = refs_on_line(line, has_hook, has_script, has_bin, has_special, line_words)
    if not refs:
        return
    maybe_note = "已" in line or "歷史" in line or "示意" in line or "若存在" in line
    for i, (_, ref, classify) in enumerate(refs):
        if (ref, rel, lineno) in seen or (maybe_note and self_noted(line, refs, i)):
            continue
        state = classify()
        if state is None:
            continue
        seen.add((ref, rel, lineno))
        out_lines.append(f"{state} {ref} ← {rel}:{lineno}")


for path in memory_files:
    raw = read_bytes(path)
    if not raw:
        continue
    file_has_hook = b"hooks/" in raw
    file_has_script = b"scripts/" in raw
    file_has_bin = b"/.local/bin/" in raw
    file_special_bytes = tuple(t for t in bare_special_bytes if t in raw) if bare_special_bytes else ()
    file_has_special = bool(file_special_bytes)
    file_word_bytes = bare_word_bytes.intersection(raw.translate(_TBL_BARE).split()) if bare_word_bytes else ()
    if not (file_has_hook or file_has_script or file_has_bin or file_has_special or file_word_bytes):
        continue
    rel = os.path.relpath(path, memory_dir)
    has_exotic_lb = (
        b"\r" in raw or b"\x0b" in raw or b"\x0c" in raw
        or b"\x1c" in raw or b"\x1d" in raw or b"\x1e" in raw
        or b"\xc2\x85" in raw or b"\xe2\x80\xa8" in raw or b"\xe2\x80\xa9" in raw
    )
    if has_exotic_lb or any(b"\n" in t for t in file_special_bytes):
        file_word_tuple = tuple(b.decode("ascii") for b in file_word_bytes) if file_word_bytes else ()
        txt = raw.decode("utf-8", "replace")
        for lineno, line in enumerate(txt.splitlines(), 1):
            _emit_line(rel, lineno, line, file_has_hook, file_has_script, file_has_bin, file_has_special, file_word_tuple)
    else:
        line_starts = set()
        rfind = raw.rfind
        find = raw.find
        rlen = len(raw)
        plain_needles = []
        if file_has_hook:
            plain_needles.append(b"hooks/")
        if file_has_script:
            plain_needles.append(b"scripts/")
        if file_has_bin:
            plain_needles.append(b"/.local/bin/")
        if file_special_bytes:
            plain_needles.extend(file_special_bytes)
        for needle in plain_needles:
            nlen = len(needle)
            pos = find(needle)
            while pos != -1:
                line_starts.add(rfind(b"\n", 0, pos) + 1)
                nl = find(b"\n", pos + nlen)
                if nl == -1:
                    break
                pos = find(needle, nl + 1)
        line_word_hits = {}
        for needle in file_word_bytes:
            nlen = len(needle)
            tok_s = needle.decode("ascii")
            pos = find(needle)
            while pos != -1:
                end = pos + nlen
                if (pos == 0 or not _BARE_PREV_ALL_B[raw[pos - 1]]) and (
                    end == rlen
                    or (
                        not _BARE_NEXT_BAD_B[raw[end]]
                        and not (end + 1 < rlen and raw[end] == 46 and _ALNUM_B[raw[end + 1]])
                    )
                ):
                    ls = rfind(b"\n", 0, pos) + 1
                    line_starts.add(ls)
                    bucket = line_word_hits.get(ls)
                    if bucket is None:
                        line_word_hits[ls] = [tok_s]
                    else:
                        bucket.append(tok_s)
                    nl = find(b"\n", end)
                    if nl == -1:
                        break
                    pos = find(needle, nl + 1)
                else:
                    pos = find(needle, pos + 1)
        if not line_starts:
            continue
        lineno = 1
        prev_ls = 0
        for ls in sorted(line_starts):
            lineno += raw.count(b"\n", prev_ls, ls)
            prev_ls = ls
            le = find(b"\n", ls)
            line = (raw[ls:] if le == -1 else raw[ls:le]).decode("utf-8", "replace")
            _emit_line(rel, lineno, line, file_has_hook, file_has_script, file_has_bin, file_has_special, line_word_hits.get(ls, ()))
if out_lines:
    sys.stdout.write("\n".join(out_lines) + "\n")
PY

python3 -c "$py_code" "$memory_dir" "$hooks_dir" "$commands_dir" "$skills_dir" "$scripts_dir" "$bin_dir" "${existing_settings[@]}" \
  || unavailable "audit failed"
exit 0
