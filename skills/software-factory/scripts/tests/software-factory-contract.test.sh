#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILL="${SKILL_DIR}/SKILL.md"
LESSONS="${SKILL_DIR}/LESSONS.md"
SCRIPT="${SKILL_DIR}/scripts/inventory-existing-automations.py"
PASS=0
FAIL=0

assert_grep() {
  local label="$1"
  local pattern="$2"
  local target="${3:-$SKILL}"
  if command grep -qE "$pattern" "$target"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_absent() {
  local label="$1"
  local pattern="$2"
  local target="${3:-$SKILL}"
  if command grep -qE "$pattern" "$target"; then
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  fi
}

assert_grep "skill marks its contract test" '本檔在契約測試底下.*software-factory-contract\.test\.sh'
assert_grep "description has Use when trigger" 'Use when.*Software Factory'
assert_grep "description has Do not use for exclusion" 'Do not use for.*gate-authoring'
assert_absent "model invocation stays enabled" 'disable-model-invocation:[[:space:]]*true'
assert_grep "stage 1 calls inventory script" 'inventory-existing-automations\.py'
assert_grep "stage 1 requires automation check even when user names a workflow" '直接點名某個流程.*先執行步驟 1 對帳既有自動觸發器'
assert_grep "stage 1 separates zombie/unconsumed schedules from normal exclusions" '殭屍排程／無消費端提醒.*不得混入正常排除項目掩蓋'
assert_grep "stage 2 requires 6-field restate" '六欄重述.*Outcome.*User.*Why now.*Success.*Constraint.*Out of scope'
assert_grep "stage 2 requires 9 controlled glossary slots" '9 大受控詞彙槽位'
assert_grep "stage 2 requires Three Brakes" '三道煞車（Three Brakes）'
assert_grep "stage 2 names Automated checks / Automated review / Human review" 'Automated checks'
assert_grep "stage 2 requires 1-shot anti-rerun state machine" '1-shot 狀態機.*merged.*needs_human.*failed.*retry_pending'
assert_grep "stage 2 requires launcher_chain fallback and quota retry_pending" 'launcher_chain.*retry_pending'
assert_grep "stage 2 requires idle session protection (< 30m lock and in_progress CI)" '< 30.*分鐘.*in_progress'
assert_grep "stage 3 context pointer to gate-authoring" '如果.*就在.*前讀.*gate-authoring/SKILL\.md'
assert_grep "stage 3 context pointer to trial-observation" '如果.*就在.*前讀.*trial-observation\.md'
assert_grep "stage 3 requires factory.disabled sentinel and Surface 4-way table" 'factory\.disabled'
assert_grep "stage 3 requires deterministic orchestrator verification" 'git status --porcelain'
assert_grep "stage 3 requires flock single-instance mutex" 'fcntl\.flock'
assert_grep "stage 3 requires atomic os.replace write" 'os\.replace'
assert_grep "stage 3 requires lstat + O_NOFOLLOW pathological protection" 'lstat.*O_NOFOLLOW'
assert_grep "stage 3 requires no content hashing" '零內容雜湊'
assert_grep "stage 3 requires 5-category test suite" '五類回歸測試.*7 天 Trial 登記'
assert_grep "stage 3 requires trials/active.md registration" 'trials/active\.md'
assert_grep "LESSONS.md records self-verify decision" 'skill-verify-auditor' "$LESSONS"

# Verify helper script runs cleanly on --help
if python3 -B "$SCRIPT" --help >/dev/null 2>&1; then
  printf 'PASS: inventory-existing-automations.py --help exits 0\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: inventory-existing-automations.py --help failed\n'
  FAIL=$((FAIL + 1))
fi

# Behavioral tests for inventory-existing-automations.py (IEA-01..IEA-04, EXTRA-IEA-1)
BASE_TMP="${TMPDIR:-/tmp}"
TMP_IEA="$(mktemp -d "${BASE_TMP%/}/sf-iea-test.XXXXXX")"
trap 'chmod -R u+rwx "$TMP_IEA" 2>/dev/null || true; rm -rf "$TMP_IEA"' EXIT

FAKE_HOME="${TMP_IEA}/fakehome"
mkdir -p "${FAKE_HOME}/.claude" "${FAKE_HOME}/Library/LaunchAgents"
cat > "${FAKE_HOME}/.claude/settings.json" <<'EOF'
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"command":"echo host-leak"}]}]}}
EOF
cat > "${FAKE_HOME}/Library/LaunchAgents/com.example.hostleak.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.example.hostleak</string>
  <key>ProgramArguments</key><array><string>/bin/echo</string><string>leak</string></array>
</dict></plist>
EOF

# IEA-01a: --root on empty fixture must not leak HOME settings or LaunchAgents
EMPTY_ROOT="${TMP_IEA}/empty-root"
mkdir -p "$EMPTY_ROOT"
if HOME="$FAKE_HOME" python3 -B "$SCRIPT" --root "$EMPTY_ROOT" > "${TMP_IEA}/iea01a.json" 2>"${TMP_IEA}/iea01a.err" && \
   HOME="$FAKE_HOME" python3 -B - "${TMP_IEA}/iea01a.json" "$EMPTY_ROOT" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
root = sys.argv[2]
assert data["hooks"] == [], f"leaked hooks: {data['hooks']}"
assert data["launch_agents"] == [], f"leaked launch_agents: {data['launch_agents']}"
assert data["settings_path"].startswith(root), data["settings_path"]
assert data["launch_agents_dir"].startswith(root), data["launch_agents_dir"]
PY
then
  printf 'PASS: IEA-01a --root empty fixture does not leak HOME\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: IEA-01a --root empty fixture leaked HOME or failed: %s\n' "$(cat "${TMP_IEA}/iea01a.err" 2>/dev/null || true)"
  FAIL=$((FAIL + 1))
fi

# IEA-01b: --root with explicit --settings honors explicit --settings
POP_ROOT="${TMP_IEA}/pop-root"
mkdir -p "$POP_ROOT"
cat > "${POP_ROOT}/settings.json" <<'EOF'
{"hooks":{"Stop":[{"matcher":"*","hooks":[{"command":"echo root-hook"}]}]}}
EOF
CUSTOM_SETTINGS="${TMP_IEA}/custom-settings.json"
cat > "$CUSTOM_SETTINGS" <<'EOF'
{"hooks":{"PreToolUse":[{"matcher":"Edit","hooks":[{"command":"echo custom-hook"}]}]}}
EOF
if HOME="$FAKE_HOME" python3 -B "$SCRIPT" --root "$POP_ROOT" --settings "$CUSTOM_SETTINGS" > "${TMP_IEA}/iea01b.json" 2>"${TMP_IEA}/iea01b.err" && \
   python3 -B - "${TMP_IEA}/iea01b.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
cmds = [h["command"] for h in data["hooks"]]
assert cmds == ["echo custom-hook"], f"expected custom-hook, got {cmds}"
PY
then
  printf 'PASS: IEA-01b explicit --settings overrides --root settings.json\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: IEA-01b explicit --settings was overridden by --root\n'
  FAIL=$((FAIL + 1))
fi

# IEA-02 & EXTRA-IEA-1: plist with <date>, <data>, and Program key
PLIST_ROOT="${TMP_IEA}/plist-root"
mkdir -p "${PLIST_ROOT}/LaunchAgents"
cat > "${PLIST_ROOT}/LaunchAgents/com.example.types.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.example.types</string>
  <key>ProgramArguments</key><array><string>/bin/echo</string><data>AQID</data></array>
  <key>StartCalendarInterval</key><date>2026-11-24T12:00:00Z</date>
</dict></plist>
EOF
cat > "${PLIST_ROOT}/LaunchAgents/com.example.program.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.example.program</string>
  <key>Program</key><string>/usr/local/bin/my-daemon</string>
</dict></plist>
EOF
if HOME="$FAKE_HOME" python3 -B "$SCRIPT" --root "$PLIST_ROOT" > "${TMP_IEA}/iea02.json" 2>"${TMP_IEA}/iea02.err" && \
   python3 -B - "${TMP_IEA}/iea02.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
by_label = {x["label"]: x for x in data["launch_agents"]}
t = by_label["com.example.types"]
assert t["program_arguments"] == ["/bin/echo", "AQID"], t
assert t["start_calendar_interval"].startswith("2026-11-24T12:00:00"), t
p = by_label["com.example.program"]
assert p["program_arguments"] == ["/usr/local/bin/my-daemon"], p
PY
then
  printf 'PASS: IEA-02 and EXTRA-IEA-1 serialize plist date/data and read Program key\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: IEA-02/EXTRA-IEA-1 failed: %s\n' "$(cat "${TMP_IEA}/iea02.err" 2>/dev/null || true)"
  FAIL=$((FAIL + 1))
fi

# IEA-03: non-object JSON root ([] and null) returns ERROR entry without crashing
for bad_json in '[]' 'null'; do
  BAD_ROOT="${TMP_IEA}/bad-json"
  mkdir -p "$BAD_ROOT"
  printf '%s\n' "$bad_json" > "${BAD_ROOT}/settings.json"
  if HOME="$FAKE_HOME" python3 -B "$SCRIPT" --root "$BAD_ROOT" > "${TMP_IEA}/iea03.json" 2>"${TMP_IEA}/iea03.err" && \
     python3 -B - "${TMP_IEA}/iea03.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
assert len(data["hooks"]) == 1 and data["hooks"][0]["event"] == "ERROR", data["hooks"]
PY
  then
    printf 'PASS: IEA-03 handles non-object JSON root (%s) cleanly\n' "$bad_json"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: IEA-03 crashed on %s: %s\n' "$bad_json" "$(cat "${TMP_IEA}/iea03.err" 2>/dev/null || true)"
    FAIL=$((FAIL + 1))
  fi
done

# IEA-04: broken settings.json symlink and unreadable LaunchAgents dir return ERROR entries
IEA04_ROOT="${TMP_IEA}/iea04-root"
mkdir -p "${IEA04_ROOT}/LaunchAgents"
ln -s "${IEA04_ROOT}/nonexistent.json" "${IEA04_ROOT}/settings.json"
printf 'x\n' > "${IEA04_ROOT}/LaunchAgents/a.plist"
chmod 000 "${IEA04_ROOT}/LaunchAgents"
if HOME="$FAKE_HOME" python3 -B "$SCRIPT" --settings "${IEA04_ROOT}/settings.json" --launch-agents "${IEA04_ROOT}/LaunchAgents" > "${TMP_IEA}/iea04.json" 2>"${TMP_IEA}/iea04.err" && \
   python3 -B - "${TMP_IEA}/iea04.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
assert len(data["hooks"]) == 1 and data["hooks"][0]["event"] == "ERROR", data["hooks"]
assert len(data["launch_agents"]) == 1 and data["launch_agents"][0]["label"] == "ERROR", data["launch_agents"]
PY
then
  printf 'PASS: IEA-04 reports broken settings symlink and unreadable LaunchAgents dir as ERROR\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL: IEA-04 silently returned empty or crashed\n'
  FAIL=$((FAIL + 1))
fi
chmod 755 "${IEA04_ROOT}/LaunchAgents"

printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
if (( FAIL > 0 )); then
  exit 1
fi
