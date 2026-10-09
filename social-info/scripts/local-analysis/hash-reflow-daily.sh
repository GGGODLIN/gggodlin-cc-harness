#!/bin/bash
# hash-reflow-daily — 每日 shell channel：三個自家 repo 的程式檔裡 hash 識別字有沒有長回來。
# 本檔在契約測試底下：bash ~/code/social-info/scripts/local-analysis/hash-reflow-daily.test.sh
#
# 為什麼存在：2026-10 拆掉 harness 裡沒人要求的 sha256／checksum 後，規則只寫在 CLAUDE.md 與
# openspec spec；個人 repo 直推 main、沒有人審 diff，所以要有一個每天看一次的偵測器。它只偵測、
# 不擋寫入、不算 digest；對照的是「每檔命中行數」baseline，不是整檔豁免——整檔豁免會讓例外檔內
# 新增的 hash 永遠不被看到（2026-10-07 GPT-6 Pro 審查第 1 條）。
# 只報兩種事：新檔有命中、既有檔命中數上升；下降或持平不報。沒有 baseline 就報錯退出，不猜。
# 連續 __SILENT__ 不代表治理有效，只代表沒抓到；log 另記本期有沒有 commit 動到自家程式檔。
# 只掃 git 追蹤的檔：live ~/.claude 裡 file-history/ 等執行期目錄有上千個無副檔名檔，用 find 會淹掉。
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:~/.local/bin"
export PATH

REPO_DIR="$HOME/code/social-info"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="${HASH_REFLOW_LOG_DIR:-$REPO_DIR/logs}"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="${HASH_REFLOW_OUT:-$OUT_DIR/$DATE-hash-reflow.md}"
LOG="$LOG_DIR/local-analysis-hash-reflow-$DATE.log"
BASELINE="${HASH_REFLOW_BASELINE:-$REPO_DIR/scripts/local-analysis/hash-reflow-baseline.tsv}"
REPOS="${HASH_REFLOW_REPOS:-claude=$HOME/.claude;social-info=$HOME/code/social-info;watchdogs=$HOME/Desktop/projects/watchdogs}"
MODE="${1:-check}"
mkdir -p "$LOG_DIR"
[ "$MODE" = "--write-baseline" ] || mkdir -p "$(dirname "$OUT")"

log() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

log "═══ hash reflow check ($DATE) mode=$MODE baseline=$BASELINE ═══"

RESULT=$(python3 - "$REPOS" "$BASELINE" "$MODE" <<'PY'
import json, os, re, subprocess, sys

repos_arg, baseline_path, mode = sys.argv[1:4]
# 與 2026-10-06 審計、hash-free-harness 收尾歸零同一條 regex；裸 hash／digest 刻意不抓。
RE = re.compile(r"(sha-?(1|224|256|384|512)|\bmd5\b|hashlib|createHash|subtle\.digest|\.hexdigest\(|\bchecksum|\bblake2|\bhmac\b|sha256sum|shasum)", re.I)
EXTS = {".py", ".sh", ".mjs", ".js", ".ts"}
ROOT_EXCL = ("archive/", "trials/archive/", "openspec/changes/archive/", ".scratch/", "worktrees/", "plugins/",
             "shell-snapshots/", "projects/", "cache/", "file-history/")
ANY_EXCL = {"node_modules", ".venv", "venv", "site-packages", "vendor", "dist", "__pycache__", ".git"}

def tracked_files(root):
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, check=True).stdout
        return [p.decode("utf-8", "replace") for p in out.split(b"\0") if p], True
    except (subprocess.CalledProcessError, FileNotFoundError):
        rels = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ANY_EXCL]
            for f in filenames:
                rels.append(os.path.relpath(os.path.join(dirpath, f), root))
        return rels, False

def is_candidate(rel):
    if rel.startswith(ROOT_EXCL):
        return False
    parts = rel.split("/")
    if any(p in ANY_EXCL for p in parts[:-1]):
        return False
    name = parts[-1]
    return os.path.splitext(name)[1] in EXTS or "." not in name

def hits(path):
    try:
        data = open(path, "rb").read()
    except OSError:
        return 0, []
    if b"\0" in data[:8000]:
        return 0, []
    found = []
    for n, line in enumerate(data.decode("utf-8", "replace").split("\n"), 1):
        if RE.search(line):
            found.append((n, line.strip()[:120]))
    return len(found), found

def changed_last_day(root, candidates, is_git):
    if not is_git:
        return "unknown"
    out = subprocess.run(["git", "-C", root, "log", "--since=1 day ago", "--name-only", "--format="],
                         capture_output=True, text=True).stdout
    touched = {l.strip() for l in out.splitlines() if l.strip()}
    return "yes" if touched & set(candidates) else "no"

current, scanned, changed = {}, {}, {}
for item in repos_arg.split(";"):
    if not item.strip():
        continue
    label, root = item.split("=", 1)
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        scanned[label] = None
        continue
    files, is_git = tracked_files(root)
    cands = [r for r in files if is_candidate(r) and os.path.isfile(os.path.join(root, r))]
    scanned[label] = len(cands)
    for rel in cands:
        n, found = hits(os.path.join(root, rel))
        if n:
            current[(label, rel)] = (n, found)
    changed[label] = changed_last_day(root, cands, is_git)

if mode == "--write-baseline":
    lines = ["# hash-reflow baseline：label<TAB>repo 相對路徑<TAB>命中行數。識別鍵／外部契約／誤中沿用此處計數；",
             "# 新增例外要使用者拍板後再重寫（bash hash-reflow-daily.sh --write-baseline）。"]
    for (label, rel), (n, _) in sorted(current.items()):
        lines.append(f"{label}\t{rel}\t{n}")
    with open(baseline_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(json.dumps({"mode": "write-baseline", "files": len(current), "scanned": scanned}, ensure_ascii=False))
    sys.exit(0)

if not os.path.isfile(baseline_path):
    print(json.dumps({"error": f"baseline not found: {baseline_path}"}, ensure_ascii=False))
    sys.exit(2)

baseline = {}
for line in open(baseline_path, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line or line.startswith("#"):
        continue
    label, rel, n = line.split("\t")
    baseline[(label, rel)] = int(n)

new, increased = [], []
for key, (n, found) in sorted(current.items()):
    base = baseline.get(key)
    if base is None:
        new.append({"label": key[0], "rel": key[1], "count": n, "lines": found[:3]})
    elif n > base:
        increased.append({"label": key[0], "rel": key[1], "count": n, "base": base, "lines": found[:3]})

def render(entries, arrow):
    out = []
    for e in entries:
        base = e["rel"].rsplit("/", 1)[-1]
        where = "；".join("`%s:%d` %s" % (base, n, t) for n, t in e["lines"])
        head = "`%s/%s` %s" % (e["label"], e["rel"], arrow(e))
        out.append("- %s — %s" % (head, where))
    return "\n".join(out)

sections = []
if new:
    sections.append("## 新檔有命中\n\n" + render(new, lambda e: "命中 %d 行" % e["count"]) + "\n")
if increased:
    sections.append("## 既有檔命中數上升\n\n" + render(increased, lambda e: "%d → %d" % (e["base"], e["count"])) + "\n")

print(json.dumps({"scanned": scanned, "changed": changed, "baseline_files": len(baseline),
                  "new": new, "increased": increased, "sections": "\n".join(sections)}, ensure_ascii=False))
PY
) || { rc=$?; log "python exited $rc: $RESULT"; exit "$rc"; }

if [ "$MODE" = "--write-baseline" ]; then
  log "baseline written: $RESULT"
  exit 0
fi

NEW_COUNT=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["new"]))')
INC_COUNT=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["increased"]))')
SCANNED=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; d=json.load(sys.stdin)["scanned"]; print(" ".join(f"{k}={v}" for k,v in d.items()))')
CHANGED=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; d=json.load(sys.stdin)["changed"]; print(" ".join(f"{k}={v}" for k,v in d.items()))')

if [ "$NEW_COUNT" -eq 0 ] && [ "$INC_COUNT" -eq 0 ]; then
  printf '__SILENT__' > "$OUT"
  log "done. scanned[$SCANNED] new=0 increased=0 changed_24h[$CHANGED] → __SILENT__"
  exit 0
fi

{
  echo "# hash 回流偵測 ($DATE)"
  echo ""
  echo "**目標**：三個自家 repo 內 git 追蹤的程式檔（.py／.sh／.mjs／.js／.ts 與無副檔名檔）逐檔數 hash 識別字命中行，對照 baseline \`$BASELINE\`。只報新檔有命中、既有檔命中數上升；識別鍵、外部契約、誤中沿用 baseline 計數。規則：\`~/.claude/CLAUDE.md\` 程式碼風格段、\`~/.claude/openspec/specs/harness-trust-binding/spec.md\`。"
  echo ""
  echo "## 結果"
  echo ""
  echo "- 掃描檔案：${SCANNED}"
  echo "- 新檔有命中：**新檔 ${NEW_COUNT}**"
  echo "- 既有檔命中數上升：**${INC_COUNT}**"
  echo "- 近 24 小時有 commit 動到自家程式檔：${CHANGED}"
  echo ""
  printf '%s' "$RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sections"])'
  echo "處置：驗證用途（permit 綁定、receipt digest、manifest 清單、自產物回驗、內容比對）→ 拆掉，改身分或原文比對；識別鍵或外部契約 → 使用者拍板後更新 baseline：\`bash ~/code/social-info/scripts/local-analysis/hash-reflow-daily.sh --write-baseline\`；誤中（git SHA 長度表、rubric 字樣）→ 同樣更新 baseline。"
} > "$OUT"

log "done. scanned[$SCANNED] new=$NEW_COUNT increased=$INC_COUNT changed_24h[$CHANGED] report=$OUT"
