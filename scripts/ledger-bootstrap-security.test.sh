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

printf 'All security boundary tests passed\n'
