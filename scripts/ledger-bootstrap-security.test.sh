#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/scripts/ledger-bootstrap-security.test.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/scripts/ledger-bootstrap.py"
FIX="$(mktemp -d)"
trap 'rm -R "$FIX"' EXIT

FIX_HOME="$FIX/home"
mkdir -p "$FIX_HOME/Desktop/projects" "$FIX_HOME/.claude/state"

make_git_repo() {
  local path=$1
  mkdir -p "$path"
  git -C "$path" init -q
}

SYMLINK_REPO="$FIX_HOME/Desktop/projects/symlink-docs"
SYMLINK_TARGET="$FIX/symlink-target"
mkdir -p "$SYMLINK_REPO" "$SYMLINK_TARGET"
git -C "$SYMLINK_REPO" init -q
ln -s "$SYMLINK_TARGET" "$SYMLINK_REPO/docs"
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$SYMLINK_REPO" >/dev/null 2>&1; then
  printf 'FAIL symlinked docs accepted\n'
  exit 1
fi
if [ -e "$SYMLINK_TARGET/owner/STATE.md" ]; then
  printf 'FAIL symlinked docs wrote outside repo\n'
  exit 1
fi
printf 'PASS symlinked docs rejected without outside write\n'

GIT_A="$FIX_HOME/Desktop/projects/git-env-a"
GIT_B="$FIX_HOME/Desktop/projects/git-env-b"
make_git_repo "$GIT_A"
make_git_repo "$GIT_B"
if ! HOME="$FIX_HOME" GIT_DIR="$GIT_B/.git" GIT_WORK_TREE="$GIT_B" python3 "$CLI" init-project-docs "$GIT_A" >/dev/null 2>&1; then
  printf 'FAIL sanitized Git environment rejected target repo\n'
  exit 1
fi
if [ ! -e "$GIT_A/docs/owner/STATE.md" ] || [ -e "$GIT_B/docs/owner/STATE.md" ]; then
  printf 'FAIL Git environment override caused a wrong-repo write\n'
  exit 1
fi
printf 'PASS Git environment override is sanitized\n'

EXCLUDE_REPO="$FIX_HOME/Desktop/projects/exclude-symlink"
EXCLUDE_TARGET="$FIX/external-exclude"
make_git_repo "$EXCLUDE_REPO"
python3 - "$EXCLUDE_REPO/.git/info/exclude" "$EXCLUDE_TARGET" <<'PY'
import sys
from pathlib import Path
link = Path(sys.argv[1])
target = Path(sys.argv[2])
target.write_text("outside-original\n")
link.unlink()
link.symlink_to(target)
PY
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$EXCLUDE_REPO" >/dev/null 2>&1; then
  printf 'FAIL symlinked Git exclude accepted\n'
  exit 1
fi
if [ "$(python3 - "$EXCLUDE_TARGET" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).read_text())
PY
)" != 'outside-original' ]; then
  printf 'FAIL symlinked Git exclude was written\n'
  exit 1
fi
printf 'PASS symlinked Git exclude rejected without outside write\n'

IGNORE_PARENT_REPO="$FIX_HOME/Desktop/projects/ignore-parent-symlink"
IGNORE_PARENT_TARGET="$FIX/external-ignore-parent"
IGNORE_PARENT_DIR="$FIX_HOME/.claude/state-symlink"
mkdir -p "$IGNORE_PARENT_TARGET"
make_git_repo "$IGNORE_PARENT_REPO"
ln -s "$IGNORE_PARENT_TARGET" "$IGNORE_PARENT_DIR"
if HOME="$FIX_HOME" python3 "$CLI" add-ignore "$IGNORE_PARENT_REPO" --ignore-file "$IGNORE_PARENT_DIR/ignore.txt" >/dev/null 2>&1; then
  printf 'FAIL ignore parent symlink accepted\n'
  exit 1
fi
if [ -e "$IGNORE_PARENT_TARGET/ignore.txt" ]; then
  printf 'FAIL ignore parent symlink wrote outside configured root\n'
  exit 1
fi
printf 'PASS ignore parent symlink rejected without outside write\n'

MARKER_REPO="$FIX_HOME/Desktop/projects/marker-parent-symlink"
MARKER_TARGET="$FIX/external-markers"
MARKER_LINK="$FIX_HOME/marker-link"
mkdir -p "$MARKER_TARGET"
make_git_repo "$MARKER_REPO"
ln -s "$MARKER_TARGET" "$MARKER_LINK"
MARKER_OUTPUT=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"marker-parent","cwd":"%s"}' "$MARKER_REPO" | HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="$MARKER_LINK" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/marker-ignore.txt" python3 "$CLI" session)
if [ -n "$MARKER_OUTPUT" ] || [ -e "$MARKER_TARGET/ledger-bootstrap-session-marker-parent" ]; then
  printf 'FAIL marker parent symlink wrote outside configured root\n'
  exit 1
fi
printf 'PASS marker parent symlink rejected without outside write\n'

ROLLBACK="$FIX_HOME/Desktop/projects/rollback"
make_git_repo "$ROLLBACK"
if HOME="$FIX_HOME" python3 - "$CLI" "$ROLLBACK" <<'PY' >/dev/null 2>&1
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("ledger_bootstrap", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original = module.atomic_write_text
calls = [0]
def fail_second(path, content, mode=0o644):
    calls[0] += 1
    if calls[0] == 2:
        raise RuntimeError("synthetic write failure")
    return original(path, content, mode)
module.atomic_write_text = fail_second
try:
    module.init_project_docs(Path(sys.argv[2]))
except RuntimeError:
    pass
else:
    raise SystemExit("synthetic failure did not fire")
root = Path(sys.argv[2])
if (root / "docs").exists() or (root / "docs" / "owner").exists():
    raise SystemExit("rollback left directories")
PY
then
  printf 'PASS failed init removes newly created directories\n'
else
  printf 'FAIL failed init left newly created directories\n'
  exit 1
fi

NONFILE="$FIX_HOME/Desktop/projects/nonfile-log"
make_git_repo "$NONFILE"
mkdir -p "$NONFILE/docs/owner/factcheck-log.md"
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$NONFILE" >/dev/null 2>&1; then
  printf 'FAIL directory log path accepted\n'
  exit 1
fi
if [ -e "$NONFILE/docs/owner/STATE.md" ]; then
  printf 'FAIL directory log path left STATE\n'
  exit 1
fi
printf 'PASS directory log path rejected without STATE\n'

PARTIAL="$FIX_HOME/Desktop/projects/partial"
make_git_repo "$PARTIAL"
python3 - "$PARTIAL/CLAUDE.md" <<'PY'
import sys
from pathlib import Path
Path(sys.argv[1]).write_bytes(bytes([255]))
PY
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$PARTIAL" >/dev/null 2>&1; then
  printf 'FAIL invalid CLAUDE encoding accepted\n'
  exit 1
fi
if [ -e "$PARTIAL/docs/owner/STATE.md" ]; then
  printf 'FAIL invalid CLAUDE encoding left partial STATE\n'
  exit 1
fi
printf 'PASS invalid CLAUDE encoding leaves no partial STATE\n'

CONCURRENT_BASE="$FIX_HOME/Desktop/projects/concurrent"
CONCURRENT_IGNORE="$FIX_HOME/.claude/state/concurrent-ignore.txt"
BARRIER="$FIX/barrier"
DRIVER="$FIX/slow-add.py"
mkdir -p "$CONCURRENT_BASE" "$BARRIER"
cat > "$DRIVER" <<'PY'
import importlib.util
import os
import sys
import time
from pathlib import Path

module_path = os.environ["LEDGER_BOOTSTRAP_MODULE"]
spec = importlib.util.spec_from_file_location("ledger_bootstrap", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

original = module.write_ignore_file
def delayed(path, paths):
    time.sleep(0.1)
    return original(path, paths)
module.write_ignore_file = delayed

repo = Path(sys.argv[1])
barrier = Path(os.environ["LEDGER_BOOTSTRAP_BARRIER"])
(barrier / repo.name).touch()
while len(list(barrier.iterdir())) < int(os.environ["LEDGER_BOOTSTRAP_TOTAL"]):
    time.sleep(0.01)
module.add_ignore(repo, Path(sys.argv[2]))
PY
PIDS=()
for i in $(python3 -c 'print(" ".join(str(i) for i in range(40)))'); do
  repo="$CONCURRENT_BASE/repo-$i"
  make_git_repo "$repo"
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MODULE="$CLI" LEDGER_BOOTSTRAP_BARRIER="$BARRIER" LEDGER_BOOTSTRAP_TOTAL=40 \
    python3 "$DRIVER" "$repo" "$CONCURRENT_IGNORE" &
  PIDS+=("$!")
done
WAIT_FAILED=0
for pid in "${PIDS[@]}"; do
  wait "$pid" || WAIT_FAILED=1
done
if [ "$WAIT_FAILED" -ne 0 ]; then
  printf 'FAIL concurrent add-ignore worker\n'
  exit 1
fi
ACTUAL_CONCURRENT=$(LEDGER_BOOTSTRAP_CONCURRENT_IGNORE="$CONCURRENT_IGNORE" python3 - "$CONCURRENT_BASE" <<'PY'
import os
import sys
from pathlib import Path

base = Path(sys.argv[1]).resolve()
expected = {str((base / f"repo-{i}").resolve()) for i in range(40)}
actual = {line.strip() for line in Path(os.environ["LEDGER_BOOTSTRAP_CONCURRENT_IGNORE"]).read_text().splitlines() if line.strip()}
print(len(expected & actual))
PY
)
if [ "$ACTUAL_CONCURRENT" != 40 ]; then
  printf 'FAIL concurrent add-ignore lost entries: %s/40\n' "$ACTUAL_CONCURRENT"
  exit 1
fi
printf 'PASS concurrent add-ignore preserves all entries\n'

FAILED=0

# F1: relative marker root (including single-segment symlink and empty string) must be rejected
F1_REPO="$FIX_HOME/Desktop/projects/f1-rel-marker"
F1_EXT="$FIX/f1-external-markers"
F1_EXT_SUB="$F1_EXT/sub"
mkdir -p "$F1_EXT_SUB"
make_git_repo "$F1_REPO"
ln -s "$F1_EXT" "$F1_REPO/marker-link"
F1_OUT1=$(cd "$F1_REPO" && printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"f1-s1","cwd":"%s"}' "$F1_REPO" | HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="marker-link" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/f1-ignore.txt" python3 "$CLI" session)
F1_OUT2=$(cd "$F1_REPO" && printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"f1-s2","cwd":"%s"}' "$F1_REPO" | HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="marker-link/sub" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/f1-ignore.txt" python3 "$CLI" session)
F1_OUT3=$(cd "$F1_REPO" && printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"f1-s3","cwd":"%s"}' "$F1_REPO" | HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/f1-ignore.txt" python3 "$CLI" session)
if [ -n "$F1_OUT1" ] || [ -n "$F1_OUT2" ] || [ -n "$F1_OUT3" ] || \
   [ -e "$F1_EXT/ledger-bootstrap-session-f1-s1" ] || \
   [ -e "$F1_EXT_SUB/ledger-bootstrap-session-f1-s2" ] || \
   [ -e "$F1_REPO/ledger-bootstrap-session-f1-s3" ]; then
  printf 'FAIL F1 relative marker root bypassed symlink/cwd boundary (out1=%s out2=%s out3=%s)\n' "$F1_OUT1" "$F1_OUT2" "$F1_OUT3"
  FAILED=1
else
  printf 'PASS F1 relative marker root rejected without outside or cwd write\n'
fi

# F2: apply_writes rollback must not re-write an unwritten existing exclude file when .git/info is 0555
F2_REPO="$FIX_HOME/Desktop/projects/f2-readonly-info"
make_git_repo "$F2_REPO"
touch "$F2_REPO/.git/info/.exclude.lock"
chmod 0600 "$F2_REPO/.git/info/.exclude.lock"
chmod 0555 "$F2_REPO/.git/info"
F2_RC=0
HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$F2_REPO" >/dev/null 2>&1 || F2_RC=$?
chmod 0755 "$F2_REPO/.git/info"
if [ "$F2_RC" -eq 0 ] || [ -e "$F2_REPO/docs" ] || [ -e "$F2_REPO/docs/owner/STATE.md" ]; then
  printf 'FAIL F2 failed init left residual docs/STATE.md (rc=%s docs_exists=%s)\n' "$F2_RC" "$([ -e "$F2_REPO/docs" ] && echo yes || echo no)"
  FAILED=1
else
  printf 'PASS F2 failed init with unwritable .git/info rolls back STATE.md and logs cleanly\n'
fi

# M10: apply_writes rollback restores an already-written existing exclude file when CLAUDE.md fails
M10_REPO="$FIX_HOME/Desktop/projects/m10-restore-exclude"
make_git_repo "$M10_REPO"
printf '%s\n' '*.tmp' > "$M10_REPO/.git/info/exclude"
mkdir -p "$M10_REPO/docs/owner"
chmod 0555 "$M10_REPO"
M10_RC=0
HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$M10_REPO" >/dev/null 2>&1 || M10_RC=$?
chmod 0755 "$M10_REPO"
M10_EXCL=$(python3 -c 'import sys; from pathlib import Path; print(repr(Path(sys.argv[1]).read_text()))' "$M10_REPO/.git/info/exclude")
if [ "$M10_RC" -eq 0 ] || [ -e "$M10_REPO/docs/owner/STATE.md" ] || [ "$M10_EXCL" != "'*.tmp\n'" ]; then
  printf 'FAIL M10 rollback did not restore modified exclude (rc=%s excl=%s)\n' "$M10_RC" "$M10_EXCL"
  FAILED=1
else
  printf 'PASS M10 rollback restores modified exclude after subsequent write failure\n'
fi

# F3a: concurrent init_project_docs on same repo must allow only one success
F3A_REPO="$FIX_HOME/Desktop/projects/f3a-same-repo"
make_git_repo "$F3A_REPO"
if ! HOME="$FIX_HOME" python3 - "$CLI" "$F3A_REPO" <<'PY'
import importlib.util
import sys
import threading
from pathlib import Path

spec = importlib.util.spec_from_file_location("ledger_bootstrap", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

orig_git_path = module.git_path
barrier = threading.Barrier(2)
def synced_git_path(root, relative):
    barrier.wait(timeout=5)
    return orig_git_path(root, relative)
module.git_path = synced_git_path

repo = Path(sys.argv[2])
results = []
lock = threading.Lock()
def worker():
    try:
        module.init_project_docs(repo)
        with lock:
            results.append(("ok", ""))
    except Exception as exc:
        with lock:
            results.append(("err", str(exc)))

t1 = threading.Thread(target=worker)
t2 = threading.Thread(target=worker)
t1.start(); t2.start()
t1.join(timeout=10); t2.join(timeout=10)
oks = [r for r in results if r[0] == "ok"]
errs = [r for r in results if r[0] == "err" and "already exists" in r[1]]
if len(oks) != 1 or len(errs) != 1:
    raise SystemExit(f"expected 1 ok and 1 already exists error, got {results}")
PY
then
  printf 'FAIL F3a concurrent init_project_docs on same repo allowed duplicate or errored\n'
  FAILED=1
else
  printf 'PASS F3a concurrent init_project_docs on same repo serializes cleanly\n'
fi

# F3b: concurrent init_project_docs across two worktrees sharing .git/info/exclude must not lose exclude entry on rollback
F3B_MAIN="$FIX_HOME/Desktop/projects/f3b-wt-main"
F3B_WT1="$FIX_HOME/Desktop/projects/f3b-wt1"
F3B_WT2="$FIX_HOME/Desktop/projects/f3b-wt2"
make_git_repo "$F3B_MAIN"
git -C "$F3B_MAIN" -c user.name=test -c user.email=test@example.com commit --allow-empty -m init -q
git -C "$F3B_MAIN" worktree add -q "$F3B_WT1" -b wt1
git -C "$F3B_MAIN" worktree add -q "$F3B_WT2" -b wt2
mkdir -p "$F3B_WT2/docs/owner"
chmod 0555 "$F3B_WT2"
F3B_OK=0
HOME="$FIX_HOME" python3 - "$CLI" "$F3B_WT1" "$F3B_WT2" "$F3B_MAIN" <<'PY' || F3B_OK=1
import importlib.util
import sys
import threading
from pathlib import Path

spec = importlib.util.spec_from_file_location("ledger_bootstrap", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

wt1, wt2, main_repo = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
wt1_canon = wt1.resolve()
wt2_snapshot_taken = threading.Event()
wt1_done = threading.Event()

orig_git_path = module.git_path
def hooked_git_path(root, relative):
    if root == wt1_canon:
        wt2_snapshot_taken.wait(timeout=2.0)
    return orig_git_path(root, relative)

orig_write_text = module.atomic_write_text
def hooked_write_text(path, content, mode=0o644):
    if threading.current_thread().name == "wt2" and path.name == "STATE.md":
        wt2_snapshot_taken.set()
        wt1_done.wait(timeout=0.3)
    return orig_write_text(path, content, mode)

module.git_path = hooked_git_path
module.atomic_write_text = hooked_write_text

errors = []
def run_wt1():
    try:
        module.init_project_docs(wt1)
    except Exception as exc:
        errors.append(("wt1", repr(exc)))
    finally:
        wt1_done.set()

def run_wt2():
    try:
        module.init_project_docs(wt2)
        errors.append(("wt2", "unexpectedly succeeded"))
    except PermissionError:
        pass
    except Exception as exc:
        errors.append(("wt2", repr(exc)))

t1 = threading.Thread(target=run_wt1, name="wt1")
t2 = threading.Thread(target=run_wt2, name="wt2")
t1.start(); t2.start()
t1.join(timeout=10); t2.join(timeout=10)
if errors:
    raise SystemExit(f"unexpected errors: {errors}")
excl = (main_repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
if "docs/owner/" not in excl.splitlines():
    raise SystemExit(f"docs/owner/ lost from shared exclude: {excl!r}")
PY
chmod 0755 "$F3B_WT2"
if [ "$F3B_OK" -ne 0 ]; then
  printf 'FAIL F3b concurrent worktree init lost docs/owner/ from shared exclude\n'
  FAILED=1
else
  printf 'PASS F3b concurrent worktree init preserves shared exclude entry\n'
fi

# F4: git_path must reject .git gitdir escaping allowed_repo scope while allowing valid same-scope worktree
F4_OUTSIDE="$FIX/f4-outside-repo"
F4_EVIL="$FIX_HOME/Desktop/projects/f4-evil-gitdir"
make_git_repo "$F4_OUTSIDE"
mkdir -p "$F4_EVIL"
OUTSIDE_GIT_REAL=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$F4_OUTSIDE/.git")
printf 'gitdir: %s\n' "$OUTSIDE_GIT_REAL" > "$F4_EVIL/.git"
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$F4_EVIL" >/dev/null 2>&1 || \
   grep -qF 'docs/owner/' "$F4_OUTSIDE/.git/info/exclude"; then
  printf 'FAIL F4 .git gitdir outside scope was accepted or wrote outside exclude\n'
  FAILED=1
else
  printf 'PASS F4 .git gitdir outside scope rejected without outside write\n'
fi

F4_FAKE_OUTSIDE="$FIX/f4-fake-outside-gitdir"
F4_EVIL_FAKE="$FIX_HOME/Desktop/projects/f4-evil-fake"
mkdir -p "$F4_FAKE_OUTSIDE/objects" "$F4_FAKE_OUTSIDE/refs" "$F4_FAKE_OUTSIDE/info" "$F4_EVIL_FAKE"
printf 'ref: refs/heads/main\n' > "$F4_FAKE_OUTSIDE/HEAD"
FAKE_OUTSIDE_REAL=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$F4_FAKE_OUTSIDE")
printf 'gitdir: %s\n' "$FAKE_OUTSIDE_REAL" > "$F4_EVIL_FAKE/.git"
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$F4_EVIL_FAKE" >/dev/null 2>&1 || \
   [ -e "$F4_FAKE_OUTSIDE/info/exclude" ]; then
  printf 'FAIL F4 fake .git gitdir outside scope was accepted\n'
  FAILED=1
else
  printf 'PASS F4 fake .git gitdir outside scope rejected\n'
fi

F4_VALID_MAIN="$FIX_HOME/Desktop/projects/f4-valid-wt-main"
F4_VALID_WT="$FIX_HOME/Desktop/projects/f4-valid-wt-child"
make_git_repo "$F4_VALID_MAIN"
git -C "$F4_VALID_MAIN" -c user.name=test -c user.email=test@example.com commit --allow-empty -m init -q
git -C "$F4_VALID_MAIN" worktree add -q "$F4_VALID_WT" -b f4-valid-branch
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$F4_VALID_WT" >/dev/null 2>&1 && \
   [ -f "$F4_VALID_WT/docs/owner/STATE.md" ] && \
   grep -qF 'docs/owner/' "$F4_VALID_MAIN/.git/info/exclude"; then
  printf 'PASS F4 valid same-scope git worktree succeeds init\n'
else
  printf 'FAIL F4 valid same-scope git worktree failed init\n'
  FAILED=1
fi

# F5: session_output and run_is_ignored must catch ValueError / UnicodeDecodeError cleanly
F5_REPO="$FIX_HOME/Desktop/projects/f5-bad-inputs"
F5_MARKERS="$FIX/f5-markers"
F5_BAD_IGNORE="$FIX_HOME/.claude/state/f5-bad-ignore.txt"
mkdir -p "$F5_MARKERS"
make_git_repo "$F5_REPO"
python3 -c 'import sys; from pathlib import Path; Path(sys.argv[1]).write_bytes(b"\xff\n")' "$F5_BAD_IGNORE"

F5_STDERR1="$FIX/f5-err1.txt"
F5_RC1=0
F5_OUT1=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"f5-1","cwd":"%s"}' "$F5_REPO" | \
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$F5_BAD_IGNORE" LEDGER_BOOTSTRAP_MARKER_ROOT="$F5_MARKERS" python3 "$CLI" session 2>"$F5_STDERR1") || F5_RC1=$?

F5_STDERR2="$FIX/f5-err2.txt"
F5_RC2=0
F5_OUT2=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"f5-2","cwd":"%s\\u0000bad"}' "$F5_REPO" | \
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/f5-ok.txt" LEDGER_BOOTSTRAP_MARKER_ROOT="$F5_MARKERS" python3 "$CLI" session 2>"$F5_STDERR2") || F5_RC2=$?

F5_STDERR3="$FIX/f5-err3.txt"
F5_RC3=0
F5_OUT3=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"f5-3","cwd":"%s"}' "$F5_REPO" | \
  HOME="$FIX_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="" LEDGER_BOOTSTRAP_MARKER_ROOT="$F5_MARKERS" python3 "$CLI" session 2>"$F5_STDERR3") || F5_RC3=$?

F5_STDERR4="$FIX/f5-err4.txt"
F5_RC4=0
HOME="$FIX_HOME" python3 "$CLI" is-ignored "$F5_REPO" --ignore-file "relative.txt" >/dev/null 2>"$F5_STDERR4" || F5_RC4=$?

if [ "$F5_RC1" -ne 0 ] || [ -n "$F5_OUT1" ] || [ -s "$F5_STDERR1" ] || \
   [ "$F5_RC2" -ne 0 ] || [ -n "$F5_OUT2" ] || [ -s "$F5_STDERR2" ] || \
   [ "$F5_RC3" -ne 0 ] || [ -n "$F5_OUT3" ] || [ -s "$F5_STDERR3" ] || \
   [ "$F5_RC4" -ne 2 ] || [ -s "$F5_STDERR4" ]; then
  printf 'FAIL F5 unhandled ValueError/UnicodeDecodeError (rcs=%s,%s,%s,%s errs=%s,%s,%s,%s)\n' \
    "$F5_RC1" "$F5_RC2" "$F5_RC3" "$F5_RC4" \
    "$(cat "$F5_STDERR1")" "$(cat "$F5_STDERR2")" "$(cat "$F5_STDERR3")" "$(cat "$F5_STDERR4")"
  FAILED=1
else
  printf 'PASS F5 session and is-ignored handle ValueError and bad UTF-8 cleanly\n'
fi

# A1: safe_path_under / validated_ignore_file must reject ~/.claude root and .. traversal
A1_HOME="$FIX/a1-home"
A1_REPO="$A1_HOME/Desktop/projects/a1-repo"
mkdir -p "$A1_HOME/.claude/state"
make_git_repo "$A1_REPO"
A1_RC1=0; HOME="$A1_HOME" python3 "$CLI" add-ignore "$A1_REPO" --ignore-file "$A1_HOME/.claude" >/dev/null 2>&1 || A1_RC1=$?
A1_RC2=0; HOME="$A1_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$A1_HOME/.claude" python3 "$CLI" is-ignored "$A1_REPO" >/dev/null 2>&1 || A1_RC2=$?
A1_RC3=0; A1_OUT3=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"a1-s1","cwd":"%s"}' "$A1_REPO" | HOME="$A1_HOME" LEDGER_BOOTSTRAP_IGNORE_FILE="$A1_HOME/.claude" python3 "$CLI" session 2>/dev/null) || A1_RC3=$?
A1_RC4=0; HOME="$A1_HOME" python3 "$CLI" add-ignore "$A1_REPO" --ignore-file "$A1_HOME/.claude/state/missing/../ignore.txt" >/dev/null 2>&1 || A1_RC4=$?
if [ "$A1_RC1" -eq 0 ] || [ "$A1_RC2" -ne 2 ] || [ "$A1_RC3" -ne 0 ] || [ -n "$A1_OUT3" ] || \
   [ "$A1_RC4" -eq 0 ] || [ -e "$A1_HOME/..claude.lock" ] || [ -e "$A1_HOME/.claude/state/missing" ]; then
  printf 'FAIL A1 ignore_file equal to ~/.claude or containing .. created lock/dir outside boundary (rcs=%s,%s,%s,%s lock=%s missing=%s)\n' \
    "$A1_RC1" "$A1_RC2" "$A1_RC3" "$A1_RC4" \
    "$([ -e "$A1_HOME/..claude.lock" ] && echo yes || echo no)" \
    "$([ -e "$A1_HOME/.claude/state/missing" ] && echo yes || echo no)"
  FAILED=1
else
  printf 'PASS A1 ~/.claude root and .. traversal rejected without creating ..claude.lock\n'
fi

# M2: ~/Desktop/projects itself initialized as a git repo must be rejected
M2_HOME="$FIX/m2-home"
M2_MARKERS="$FIX/m2-markers"
mkdir -p "$M2_HOME/Desktop/projects" "$M2_HOME/.claude/state" "$M2_MARKERS"
git -C "$M2_HOME/Desktop/projects" init -q
M2_INIT_RC=0; HOME="$M2_HOME" python3 "$CLI" init-project-docs "$M2_HOME/Desktop/projects" >/dev/null 2>&1 || M2_INIT_RC=$?
M2_IGN_RC=0; HOME="$M2_HOME" python3 "$CLI" add-ignore "$M2_HOME/Desktop/projects" >/dev/null 2>&1 || M2_IGN_RC=$?
M2_SESS_OUT=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"m2-s1","cwd":"%s"}' "$M2_HOME/Desktop/projects" | \
  HOME="$M2_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="$M2_MARKERS" python3 "$CLI" session)
if [ "$M2_INIT_RC" -eq 0 ] || [ "$M2_IGN_RC" -eq 0 ] || [ -n "$M2_SESS_OUT" ] || \
   [ -e "$M2_HOME/Desktop/projects/docs/owner/STATE.md" ] || \
   [ -e "$M2_MARKERS/ledger-bootstrap-session-m2-s1" ]; then
  printf 'FAIL M2 Desktop/projects root accepted as managed repo\n'
  FAILED=1
else
  printf 'PASS M2 Desktop/projects root itself rejected\n'
fi

# M6: concurrent session calls with same session_id emit reminder once and reject dangling marker symlink
M6_REPO="$FIX_HOME/Desktop/projects/m6-concurrent-session"
M6_MARKERS="$FIX/m6-markers"
mkdir -p "$M6_MARKERS"
make_git_repo "$M6_REPO"
if ! HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="$M6_MARKERS" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/m6-ignore.txt" \
  python3 - "$CLI" "$M6_REPO" <<'PY'
import importlib.util
import sys
import threading
from pathlib import Path

spec = importlib.util.spec_from_file_location("ledger_bootstrap", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

orig_gc = module.gc_markers
barrier = threading.Barrier(8)
def synced_gc(marker_root):
    orig_gc(marker_root)
    barrier.wait(timeout=5)
module.gc_markers = synced_gc

repo = sys.argv[2]
outputs = []
lock = threading.Lock()
def worker():
    out = module.session_output({
        "hook_event_name": "SessionStart",
        "source": "startup",
        "session_id": "m6-race-sid",
        "cwd": repo,
    })
    with lock:
        outputs.append(out)

threads = [threading.Thread(target=worker) for _ in range(8)]
for t in threads:
    t.start()
for t in threads:
    t.join(timeout=10)
non_empty = [o for o in outputs if o]
if len(non_empty) != 1:
    raise SystemExit(f"expected exactly 1 reminder across 8 concurrent callers, got {len(non_empty)}")
PY
then
  printf 'FAIL M6 concurrent session_id did not deduplicate atomically\n'
  FAILED=1
else
  M6_DANGLING_TARGET="$FIX/m6-dangling-target"
  ln -s "$M6_DANGLING_TARGET" "$M6_MARKERS/ledger-bootstrap-session-m6-dangling"
  M6_DANGLING_OUT=$(printf '{"hook_event_name":"SessionStart","source":"startup","session_id":"m6-dangling","cwd":"%s"}' "$M6_REPO" | \
    HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="$M6_MARKERS" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/m6-ignore.txt" python3 "$CLI" session)
  if [ -n "$M6_DANGLING_OUT" ] || [ -e "$M6_DANGLING_TARGET" ]; then
    printf 'FAIL M6 dangling symlink marker was followed\n'
    FAILED=1
  else
    printf 'PASS M6 concurrent same session_id creates marker once and rejects dangling symlink\n'
  fi
fi

# M6b: deterministic TOCTOU window between marker.exists() and marker.touch(exist_ok=False)
if ! HOME="$FIX_HOME" LEDGER_BOOTSTRAP_MARKER_ROOT="$M6_MARKERS" LEDGER_BOOTSTRAP_IGNORE_FILE="$FIX_HOME/.claude/state/m6-ignore.txt" \
  python3 - "$CLI" "$M6_REPO" <<'PY'
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("ledger_bootstrap", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

orig_exists = Path.exists
def racing_exists(self):
    if self.name == "ledger-bootstrap-session-m6-toctou":
        # Simulate another process creating the marker right after exists() returns False
        orig_exists(self)
        self.touch(exist_ok=True)
        return False
    return orig_exists(self)

Path.exists = racing_exists
try:
    out = module.session_output({
        "hook_event_name": "SessionStart",
        "source": "startup",
        "session_id": "m6-toctou",
        "cwd": sys.argv[2],
    })
finally:
    Path.exists = orig_exists

if out != "":
    raise SystemExit(f"expected empty output when marker already exists at touch(), got {out!r}")
PY
then
  printf 'FAIL M6b marker TOCTOU race emitted duplicate reminder\n'
  FAILED=1
else
  printf 'PASS M6b marker touch(exist_ok=False) blocks TOCTOU duplicate reminder\n'
fi

# M4: intra-repo symlink .git/info/exclude (target inside .git/info) must still be rejected
M4_REPO="$FIX_HOME/Desktop/projects/m4-intragit-symlink-exclude"
make_git_repo "$M4_REPO"
printf '# inside target\n' > "$M4_REPO/.git/info/other-exclude"
rm -f "$M4_REPO/.git/info/exclude"
ln -s "$M4_REPO/.git/info/other-exclude" "$M4_REPO/.git/info/exclude"
if HOME="$FIX_HOME" python3 "$CLI" init-project-docs "$M4_REPO" >/dev/null 2>&1 || \
   grep -qF 'docs/owner/' "$M4_REPO/.git/info/other-exclude"; then
  printf 'FAIL M4 intra-repo symlinked .git/info/exclude was accepted\n'
  FAILED=1
else
  printf 'PASS M4 intra-repo symlinked .git/info/exclude rejected without write\n'
fi

[ "$FAILED" -eq 0 ] || exit 1
printf 'All security boundary tests passed\n'
