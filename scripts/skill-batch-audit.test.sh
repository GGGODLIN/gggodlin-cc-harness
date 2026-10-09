#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/.claude"
CLI="$ROOT/scripts/skill-batch-audit.py"
VALIDATOR="$ROOT/skills/skill-creator/scripts/quick_validate.py"
TMP=$(mktemp -d)
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$TMP"' EXIT
pass=0
fail=0

record_pass() {
  printf 'PASS %s\n' "$1"
  pass=$((pass + 1))
}

record_fail() {
  printf 'FAIL %s\n' "$1"
  fail=$((fail + 1))
}

make_skill() {
  local path="$1"
  local name="$2"
  mkdir -p "$path"
  printf '%s\n' '---' "name: $name" 'description: A valid test skill.' '---' > "$path/SKILL.md"
}

run_validator_pass() {
  local label="$1"
  local path="$2"
  if python3 "$VALIDATOR" "$path" > "$TMP/validator.out" 2>&1; then
    record_pass "$label"
  else
    record_fail "$label: $(<"$TMP/validator.out")"
  fi
}

run_validator_fail() {
  local label="$1"
  local path="$2"
  if python3 "$VALIDATOR" "$path" > "$TMP/validator.out" 2>&1; then
    record_fail "$label unexpectedly passed"
  else
    record_pass "$label"
  fi
}

run_validator_exact() {
  local label="$1"
  local path="$2"
  local expected="$3"
  if python3 "$VALIDATOR" "$path" > "$TMP/validator.out" 2>&1; then
    record_fail "$label unexpectedly passed"
  elif [ "$(<"$TMP/validator.out")" = "$expected" ] && ! grep -q 'Traceback' "$TMP/validator.out"; then
    record_pass "$label"
  else
    record_fail "$label: $(<"$TMP/validator.out")"
  fi
}

run_batch() {
  local inventory="$1"
  local output="$2"
  local status=0
  HOME="$FIXTURE_HOME" python3 "$CLI" --inventory "$inventory" > "$output" 2> "$output.err" || status=$?
  BATCH_STATUS=$status
}

FIXTURE_HOME="$TMP/home"
FIXTURE_PROJECT="$TMP/project"
mkdir -p "$FIXTURE_HOME/.claude/skills" "$FIXTURE_PROJECT/.claude/skills"
make_skill "$FIXTURE_HOME/.claude/skills/alpha" alpha
make_skill "$FIXTURE_HOME/.claude/skills/delegate-browser-e2e" delegate-browser-e2e
make_skill "$FIXTURE_HOME/.claude/skills/zeta" zeta
make_skill "$FIXTURE_PROJECT/.claude/skills/gamma" gamma

cat > "$TMP/inventory.md" <<EOF
## Global skills (\`~/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| zeta | self | yes |
| ignored | self | no |
| support (command) | self | yes |
| alpha | self | yes |

## Project: fixture (\`$FIXTURE_PROJECT/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| gamma | self | yes (patched) |
EOF

run_batch "$TMP/inventory.md" "$TMP/success.out"
expected=$(printf 'RESULT\tPASS\t%s\tSkill is valid!\nRESULT\tPASS\t%s\tSkill is valid!\nRESULT\tPASS\t%s\tSkill is valid!\nRESULT\tPASS\t%s\tSkill is valid!\nSUMMARY\ttotal=4\tpass=4\tfail=0\n' \
  "$FIXTURE_HOME/.claude/skills/alpha/SKILL.md" \
  "$FIXTURE_HOME/.claude/skills/delegate-browser-e2e/SKILL.md" \
  "$FIXTURE_HOME/.claude/skills/zeta/SKILL.md" \
  "$FIXTURE_PROJECT/.claude/skills/gamma/SKILL.md")
if [ "$BATCH_STATUS" -eq 0 ] && [ "$(<"$TMP/success.out")" = "${expected%$'\n'}" ] && ! grep -qE 'ignored|support' "$TMP/success.out"; then
  record_pass 'batch scope, deterministic order, delegate row, and summary'
else
  record_fail "batch success output or scope: $(<"$TMP/success.out")"
fi

cat > "$TMP/missing.md" <<EOF
## Global skills (\`~/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| alpha | self | yes |
| missing | self | yes |
EOF
run_batch "$TMP/missing.md" "$TMP/missing.out"
if [ "$BATCH_STATUS" -ne 0 ] && grep -q $'RESULT\tFAIL' "$TMP/missing.out" && grep -q $'fail=1' "$TMP/missing.out"; then
  record_pass 'missing path exits nonzero'
else
  record_fail "missing path status/output: status=$BATCH_STATUS output=$(<"$TMP/missing.out")"
fi

cat > "$TMP/zero.md" <<EOF
## Global skills (\`~/.claude/skills/\`)

| Skill | Origin | Audit |
|---|---|---|
| ignored | self | no |
| support (command) | self | yes |
EOF
run_batch "$TMP/zero.md" "$TMP/zero.out"
if [ "$BATCH_STATUS" -ne 0 ] && grep -q 'total=0' "$TMP/zero.out"; then
  record_pass 'zero-path inventory exits nonzero'
else
  record_fail "zero-path status/output: status=$BATCH_STATUS output=$(<"$TMP/zero.out")"
fi

printf '%s\n' 'not an inventory table' > "$TMP/malformed.md"
run_batch "$TMP/malformed.md" "$TMP/malformed.out"
if [ "$BATCH_STATUS" -ne 0 ]; then
  record_pass 'malformed inventory exits nonzero'
else
  record_fail 'malformed inventory unexpectedly passed'
fi

run_batch "$TMP/does-not-exist.md" "$TMP/not-found.out"
if [ "$BATCH_STATUS" -ne 0 ]; then
  record_pass 'missing inventory exits nonzero'
else
  record_fail 'missing inventory unexpectedly passed'
fi

mkdir -p "$TMP/accepted"
printf '%s\n' '---' 'name: historical-provenance' 'description: Use when values stay <100 items or > 8k entries.' 'upstream: mattpocock/skills' 'upstream-path: skills/engineering/example/SKILL.md' 'upstream-pinned: 54bc6b6' 'upstream-branch: main' 'upstream-status: orphaned' 'disable-model-invocation: true' '---' > "$TMP/accepted/SKILL.md"
run_validator_pass 'historical provenance, disable-model-invocation, and numeric comparisons' "$TMP/accepted"

mkdir -p "$TMP/merge"
printf '%s\n' '---' 'name: merge' 'description: Merge metadata with an explicit override.' 'metadata:' '  <<: &base' '    owner: base' '  owner: override' '---' > "$TMP/merge/SKILL.md"
run_validator_pass 'YAML merge with explicit override passes' "$TMP/merge"

mkdir -p "$TMP/nested-duplicate"
printf '%s\n' '---' 'name: nested-duplicate' 'description: Nested duplicate keys are invalid.' 'metadata:' '  nested:' '    key: one' '    key: two' '---' > "$TMP/nested-duplicate/SKILL.md"
run_validator_exact 'nested duplicate YAML keys fail exactly' "$TMP/nested-duplicate" "Invalid YAML in frontmatter: duplicate key 'key'"

mkdir -p "$TMP/unhashable"
printf '%s\n' '---' 'name: unhashable' 'description: Unhashable keys are invalid.' 'metadata:' '  ? [one, two]' '  : value' '---' > "$TMP/unhashable/SKILL.md"
run_validator_exact 'unhashable YAML keys fail exactly' "$TMP/unhashable" 'Invalid YAML in frontmatter: unhashable YAML key'

mkdir -p "$TMP/context-command"
printf '%s\n' '---' 'name: context-command' 'description: Use /review-html <file> for the selected document.' '---' > "$TMP/context-command/SKILL.md"
run_validator_pass 'slash command argument placeholder passes' "$TMP/context-command"

mkdir -p "$TMP/context-path"
printf '%s\n' '---' 'name: context-path' 'description: Write .scratch/<feature-slug>/spec.md after planning.' '---' > "$TMP/context-path/SKILL.md"
run_validator_pass 'path segment placeholder passes' "$TMP/context-path"

mkdir -p "$TMP/adjacent-numeric"
printf '%s\n' '---' 'name: adjacent-numeric' 'description: Match a<100 without whitespace.' '---' > "$TMP/adjacent-numeric/SKILL.md"
run_validator_pass 'adjacent numeric comparison passes' "$TMP/adjacent-numeric"

mkdir -p "$TMP/docs-path"
printf '%s\n' '---' 'name: docs-path' 'description: Read docs/<file> from the generated bundle.' '---' > "$TMP/docs-path/SKILL.md"
run_validator_pass 'path placeholder without trailing slash passes' "$TMP/docs-path"

mkdir -p "$TMP/not-command"
printf '%s\n' '---' 'name: not-command' 'description: Do not treat not/review-html <file> as a command.' '---' > "$TMP/not-command/SKILL.md"
run_validator_fail 'embedded slash command fails' "$TMP/not-command"

mkdir -p "$TMP/command-suffix"
printf '%s\n' '---' 'name: command-suffix' 'description: Do not accept /review-html <file>suffix.' '---' > "$TMP/command-suffix/SKILL.md"
run_validator_fail 'command placeholder suffix fails' "$TMP/command-suffix"

mkdir -p "$TMP/html"
printf '%s\n' '---' 'name: html' 'description: Use <strong>markup</strong>.' '---' > "$TMP/html/SKILL.md"
run_validator_fail 'HTML angle brackets fail' "$TMP/html"

mkdir -p "$TMP/placeholder"
printf '%s\n' '---' 'name: placeholder' 'description: Replace <name> before use.' '---' > "$TMP/placeholder/SKILL.md"
run_validator_fail 'placeholder angle brackets fail' "$TMP/placeholder"

mkdir -p "$TMP/unscoped-hyphen-placeholder"
printf '%s\n' '---' 'name: unscoped-hyphen-placeholder' 'description: Replace <feature-slug> before use.' '---' > "$TMP/unscoped-hyphen-placeholder/SKILL.md"
run_validator_fail 'unscoped hyphen placeholder fails' "$TMP/unscoped-hyphen-placeholder"

mkdir -p "$TMP/duplicate"
printf '%s\n' '---' 'name: duplicate' 'name: duplicate-again' 'description: Duplicate keys are invalid.' '---' > "$TMP/duplicate/SKILL.md"
run_validator_exact 'duplicate YAML keys fail exactly' "$TMP/duplicate" "Invalid YAML in frontmatter: duplicate key 'name'"

mkdir -p "$TMP/bad-yaml"
printf '%s\n' '---' 'name: bad-yaml' 'description: [unterminated' '---' > "$TMP/bad-yaml/SKILL.md"
run_validator_fail 'malformed YAML fails' "$TMP/bad-yaml"

mkdir -p "$TMP/io-directory/SKILL.md"
run_validator_exact 'SKILL.md directory read fails exactly' "$TMP/io-directory" 'Unable to read SKILL.md'

mkdir -p "$TMP/invalid-utf8"
python3 - "$TMP/invalid-utf8/SKILL.md" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes(b'\xff\xfe')
PY
run_validator_exact 'invalid UTF-8 read fails exactly' "$TMP/invalid-utf8" 'SKILL.md is not valid UTF-8'

mkdir -p "$TMP/bad-delimiter"
printf '%s\n' '---' 'name: bad-delimiter' 'description: A complete frontmatter delimiter is required.' '---not-a-delimiter' > "$TMP/bad-delimiter/SKILL.md"
run_validator_exact 'incomplete closing delimiter fails exactly' "$TMP/bad-delimiter" 'Invalid frontmatter format'

python3 - "$CLI" <<'PY'
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import sys

spec = spec_from_file_location('skill_batch_audit_test', sys.argv[1])
module = module_from_spec(spec)
spec.loader.exec_module(module)
paths = [
    Path('/tmp/skill-audit-isolation/alpha/SKILL.md'),
    Path('/tmp/skill-audit-isolation/raise/SKILL.md'),
    Path('/tmp/skill-audit-isolation/noisy/SKILL.md'),
]
module.inventory_paths = lambda _: sorted(paths, key=str)

def validate(path):
    if path.name == 'raise':
        raise RuntimeError('boom')
    if path.name == 'noisy':
        return False, 'bad\tfield\nnext\r'
    return True, 'ok'

module.load_validator = lambda: validate
stdout = StringIO()
stderr = StringIO()
with redirect_stdout(stdout), redirect_stderr(stderr):
    exit_code = module.main(['--inventory', '/tmp/unused-inventory.md'])
lines = stdout.getvalue().splitlines()
expected = [
    'RESULT\tPASS\t/tmp/skill-audit-isolation/alpha/SKILL.md\tok',
    'RESULT\tFAIL\t/tmp/skill-audit-isolation/noisy/SKILL.md\tbad\\tfield\\nnext\\r',
    'RESULT\tFAIL\t/tmp/skill-audit-isolation/raise/SKILL.md\tValidator exception: RuntimeError: boom',
    'SUMMARY\ttotal=3\tpass=1\tfail=2',
]
if exit_code == 1 and lines == expected and 'Traceback' not in stdout.getvalue() + stderr.getvalue():
    print('PASS batch isolates exceptions and escapes TSV messages')
else:
    print('FAIL batch isolation output')
    print(stdout.getvalue(), end='')
    print(stderr.getvalue(), end='')
    sys.exit(1)
PY

python3 - "$CLI" <<'PY'
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile

spec = spec_from_file_location('skill_batch_path_test', sys.argv[1])
module = module_from_spec(spec)
spec.loader.exec_module(module)

module.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
    returncode=0,
    stdout='/tmp/skill-audit-root/../outside/SKILL.md\n',
    stderr='',
)
try:
    module.inventory_paths(Path('/tmp/unused-inventory.md'))
except module.AuditInputError as error:
    traversal_ok = str(error) == 'inventory parser produced path traversal'
else:
    traversal_ok = False

with tempfile.TemporaryDirectory() as root:
    root_path = Path(root)
    real = root_path / 'real'
    alias = root_path / 'alias'
    real.mkdir()
    alias.symlink_to(real, target_is_directory=True)
    module.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
        returncode=0,
        stdout=f'{real / "SKILL.md"}\n{alias / "SKILL.md"}\n',
        stderr='',
    )
    try:
        module.inventory_paths(Path('/tmp/unused-inventory.md'))
    except module.AuditInputError as error:
        duplicate_ok = str(error) == 'inventory parser produced normalized duplicate skill paths'
    else:
        duplicate_ok = False

if traversal_ok and duplicate_ok:
    print('PASS batch path traversal and normalized duplicate defenses')
else:
    print('FAIL batch path defenses')
    sys.exit(1)
PY

printf '%s\n' "---- $pass pass / $fail fail ----"
exit "$fail"
