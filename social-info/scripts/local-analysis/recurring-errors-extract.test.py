#!/usr/bin/env python3
"""recurring-errors-extract.py 的回歸 fixture。

跑法：python3 recurring-errors-extract.test.py
改正規化或抽取邏輯後必重跑。鎖住的線：
  (1) 正規化語意與舊 bash 版逐項一致（避免重建後簽名體系整個位移、跨輪不可比）
  (2) 一個多行錯誤 = 一個簽名（本次修的主 bug）
  (3) 短碎片仍被門檻濾掉
  (4) 日期取該筆錯誤的真實 timestamp、不是掃描當天
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "extract", Path(__file__).parent / "recurring-errors-extract.py"
)
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

OLD_PIPELINE = (
    "printf '%s' \"$1\" | tr '[:upper:]' '[:lower:]' "
    "| sed -E 's#/[^ ]+##g; s/[0-9a-f]{8,}//g; s/[0-9]+//g; s/[[:space:]]+/ /g' "
    "| cut -c1-140 | sed 's/^ *//; s/ *$//'"
)

PASS = FAIL = 0


def check(name, want, got):
    global PASS, FAIL
    if want == got:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}\n        want {want!r}\n        got  {got!r}")
        FAIL += 1


def old_norm(text):
    return subprocess.run(
        ["bash", "-c", OLD_PIPELINE, "_", text], capture_output=True, text=True
    ).stdout.strip()


print("\n=== 正規化語意與舊 bash 版對齊（單行輸入，兩版應完全相同）===")
SINGLE_LINE = [
    "Exit code 1",
    "string to replace not found in file.",
    "<tool_use_error>File has not been read yet. Read it first before writing to it.<",
    "ls: /Users/foo/bar: No such file or directory",
    "error: ENOTFOUND registry.npmjs.org",
    "Command timed out after 300000 ms",
    "fatal: repository 'https://example.com/x.git' not found",
    "ModuleNotFoundError: No module named 'yaml'",
]
for c in SINGLE_LINE:
    check(f"對齊 {c[:38]!r}", old_norm(c), extract.normalize(c))

print("\n=== 主 bug 迴歸：多行錯誤 = 一個簽名 ===")
GUARD_BLOCK = "\n".join(
    [
        "BLOCKED by guard",
        "",
        "Reason: destructive operation requires approval.",
        "Rule: core.filesystem:general",
        "",
        "[協作協議 — 給 Claude 的指示]",
        "1. 不要改寫、拆解或混淆指令來繞過這個防護。",
        "2. 向使用者說明這條指令要動什麼、為什麼需要。",
        "使用者也可以選擇自己手動執行該指令。",
    ]
)
sig = extract.normalize(GUARD_BLOCK)
check("9 行攔截訊息 → 1 個簽名（不含換行）", True, "\n" not in sig)
check("簽名從首行開始", True, sig.startswith("blocked by guard"))
old_lines = [x for x in (old_norm(l) for l in GUARD_BLOCK.split("\n")) if len(x) >= 15]
check("舊版會把它拆成多筆（證明 bug 真實）", True, len(old_lines) > 1)
print(f"        舊版產生 {len(old_lines)} 筆、新版 1 筆")

TIMEOUT_BLOCK = "Command timed out after 5m 0s\nb9908897-8b66-4a7a-a69e-7b77d4a5083b: 0\ne8f56764-e808-482b-9d90-bf91a7facfc0: 1"
sig2 = extract.normalize(TIMEOUT_BLOCK)
check("逾時+UUID 三行 → 1 個簽名", True, "\n" not in sig2)
check("逾時語意保留（envclass 分得出來）", True, "timed out" in sig2)

print("\n=== 短碎片門檻仍生效 ===")
for frag in ["Exit code 1", "---", "total", "{", "}"]:
    s = extract.normalize(frag)
    check(f"{frag!r} 長度 {len(s)} < 15 → 丟棄", True, len(s) < extract.MIN_SIG_LEN)

print("\n=== 長度上限 ===")
check("截到 140 字元", True, len(extract.normalize("x" * 500)) <= extract.MAX_SIG_LEN)

print("\n=== 日期取真實 timestamp、不是掃描當天 ===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "sess-abc.jsonl"
    rows = [
        {
            "type": "user",
            "timestamp": "2026-03-15T08:22:11.000Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "is_error": True,
                        "content": [{"type": "text", "text": GUARD_BLOCK}],
                    }
                ]
            },
        }
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    got = list(extract.iter_errors(p))
    check("抽出 1 筆錯誤", 1, len(got))
    check("日期 = 錯誤發生日不是今天", "2026-03-15", got[0][0])

print("\n=== content 是字串（非 array）的相容性 ===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "sess-str.jsonl"
    r = {
        "type": "user",
        "timestamp": "2026-04-01T00:00:00.000Z",
        "message": {
            "content": [
                {"type": "tool_result", "is_error": True, "content": "plain string error text here"}
            ]
        },
    }
    p.write_text(json.dumps(r))
    got = list(extract.iter_errors(p))
    check("字串型 content 也抽得到", 1, len(got))
    check("內容正確", "plain string error text here", got[0][1])

print("\n=== 非錯誤與壞行不得混入 ===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "sess-mix.jsonl"
    lines = [
        json.dumps(
            {
                "type": "user",
                "timestamp": "2026-04-01T00:00:00.000Z",
                "message": {
                    "content": [
                        {"type": "tool_result", "is_error": False, "content": "ok result"}
                    ]
                },
            }
        ),
        "{ not json at all",
        json.dumps({"type": "assistant", "message": {"content": []}}),
        json.dumps(
            {
                "type": "user",
                "timestamp": "2026-04-02T00:00:00.000Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "is_error": True,
                            "content": [{"type": "text", "text": "real failure message here"}],
                        }
                    ]
                },
            }
        ),
    ]
    p.write_text("\n".join(lines))
    got = list(extract.iter_errors(p))
    check("只抽到 1 筆真錯誤（壞行/非錯誤跳過）", 1, len(got))

print("\n=== 非標準時間戳、壞型別與 load_seen 容錯 ===")
check("normalize 非字串回傳空字串", "", extract.normalize(None))
check("normalize 14 字元低於門檻 15", True, len(extract.normalize("z" * 14)) < extract.MIN_SIG_LEN)
check("normalize 15 字元通過門檻 15", True, len(extract.normalize("z" * 15)) == extract.MIN_SIG_LEN)
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "weird.jsonl"
    p.write_text(
        "\n".join(
            [
                '["is_error"]',
                json.dumps({"type": "user", "timestamp": "2026-04-01T00:00:00Z", "message": "not-a-dict", "is_error": True}),
                json.dumps({"type": "user", "timestamp": "2026-04-01T00:00:00Z", "message": {"content": [{"type": "tool_result", "is_error": "false", "content": "string false should not count"}]}}),
                json.dumps({"type": "user", "timestamp": 1773562931, "message": {"content": [{"type": "tool_result", "is_error": True, "content": [{"type": "text", "text": None}, {"type": "text", "text": "numeric epoch timestamp error here"}]}]}}),
                json.dumps({"type": "user", "timestamp": "2026-03-16T01:00:00+08:00", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "offset timestamp normalizes to utc date"}]}}),
                json.dumps({"type": "user", "timestamp": "not-a-date", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "invalid timestamp falls back cleanly"}]}}),
            ]
        ),
        encoding="utf-8",
    )
    got = list(extract.iter_errors(p))
    check("壞型別與字串 false 濾除後僅留 3 筆", 3, len(got))
    check("數值時間戳回傳空日期但保留錯誤本文", ("", "numeric epoch timestamp error here"), got[0])
    check("帶時區偏移時間戳歸一化為 UTC 日期", "2026-03-15", got[1][0])
    check("無效時間戳回傳空日期交由 fallback", "", got[2][0])

    bad_ledger = Path(td) / "bad-ledger.jsonl"
    bad_ledger.write_text(
        "\n".join(
            [
                "[]",
                "{broken",
                json.dumps({"sig": ["unhashable"], "session": "s1"}),
                json.dumps({"sig": "valid error signature here", "session": "s1", "tool_use_id": "tid-old"}),
            ]
        ),
        encoding="utf-8",
    )
    seen, rows_cnt = extract.load_seen(bad_ledger)
    check("load_seen 跳過壞行與不可雜湊欄位", {("valid error signature here", "s1")}, seen)
    check("load_seen 僅統計合法 dict 列", 2, rows_cnt)

print("\n=== 游標 mtime 競態、--days 不超前游標、跨檔分岔去重、編碼與原子寫入 ===")
SCRIPT_PY = Path(__file__).parent / "recurring-errors-extract.py"
with tempfile.TemporaryDirectory() as td:
    # 1. 游標競態：掃描期間被追加的錯誤，下一輪增量必能補抓（因 STATE mtime 設在掃描起點）
    home = Path(td) / "race-home"
    proj = home / ".claude" / "projects" / "p1"
    proj.mkdir(parents=True)
    f1 = proj / "s1.jsonl"
    f1.write_text(
        json.dumps({"type": "user", "timestamp": "2026-11-18T10:00:00Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "race-t1", "is_error": True, "content": "initial error message one"}]}}) + "\n",
        encoding="utf-8",
    )
    race_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(race_mod)
    race_mod.HOME = home
    race_mod.PROJECTS = home / ".claude" / "projects"
    race_mod.STATE = home / ".claude" / "state" / "recurring-errors.last_run"
    race_mod.LEDGER = home / "code" / "social-info" / "reports" / "local-analysis" / "recurring-errors-ledger.jsonl"

    orig_rec_iter = race_mod._iter_error_records
    appended = {"done": False}
    def hooked_rec_iter(path):
        yield from orig_rec_iter(path)
        if not appended["done"]:
            appended["done"] = True
            time.sleep(0.05)
            with open(f1, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"type": "user", "timestamp": "2026-11-18T10:01:00Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "race-t2", "is_error": True, "content": "mid-scan appended error two"}]}}) + "\n")
            time.sleep(0.05)

    race_mod._iter_error_records = hooked_rec_iter
    orig_argv = sys.argv
    try:
        sys.argv = ["recurring-errors-extract.py"]
        rc1 = race_mod.main()
        race_mod._iter_error_records = orig_rec_iter
        sys.argv = ["recurring-errors-extract.py"]
        rc2 = race_mod.main()
    finally:
        sys.argv = orig_argv
    race_rows = [json.loads(l) for l in race_mod.LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    check("游標競態兩輪皆 exit 0", (0, 0), (rc1, rc2))
    check("掃描中途追加的錯誤於次輪增量被捕獲", True, any("mid-scan appended error two" in r["sig"] for r in race_rows))

    with f1.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "type": "user",
            "timestamp": "2026-11-18T10:02:00Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "race-t3", "is_error": True,
                                     "content": "error appended in cursor second"}]},
        }) + "\n")
    cursor_ns = race_mod.STATE.stat().st_mtime_ns
    os.utime(f1, ns=(cursor_ns, cursor_ns))
    check("檔案與游標的 mtime 相等", cursor_ns, f1.stat().st_mtime_ns)
    try:
        sys.argv = ["recurring-errors-extract.py"]
        rc_equal = race_mod.main()
    finally:
        sys.argv = orig_argv
    rows_equal = [json.loads(line) for line in race_mod.LEDGER.read_text(encoding="utf-8").splitlines()]
    check("游標同一秒追加的錯誤被補入且不重計", (0, ["race-t1", "race-t2", "race-t3"]),
          (rc_equal, [row["tool_use_id"] for row in rows_equal]))

    # 2. 跨檔分岔 tool_use_id 去重、--days 不推進游標、缺尾端換行安全追加、ASCII locale 中文寫入、錯誤參數攔截
    home2 = Path(td) / "cli-home"
    proj2 = home2 / ".claude" / "projects" / "p1"
    proj2.mkdir(parents=True)
    fork_row = json.dumps({
        "type": "user",
        "timestamp": "2026-11-18T10:00:00Z",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "fork-tid-1", "is_error": True, "content": "中文分岔錯誤訊息重複測試內容驗證"}]},
    }, ensure_ascii=False)
    (proj2 / "parent.jsonl").write_text(fork_row + "\n", encoding="utf-8")
    (proj2 / "fork.jsonl").write_text(fork_row + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(home2)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["PYTHONCOERCECLOCALE"] = "0"
    env["PYTHONUTF8"] = "0"

    r_dry = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--rebuild", "--dry-run"], env=env, capture_output=True, text=True)
    ledger2 = home2 / "code" / "social-info" / "reports" / "local-analysis" / "recurring-errors-ledger.jsonl"
    check("--dry-run 不寫出 ledger", (0, False), (r_dry.returncode, ledger2.exists()))

    r_reb = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--rebuild"], env=env, capture_output=True, text=True)
    check("ASCII locale --rebuild 正常寫出中文", 0, r_reb.returncode)
    reb_rows = [json.loads(l) for l in ledger2.read_text(encoding="utf-8").splitlines() if l.strip()]
    check("跨檔分岔共享 tool_use_id 去重為 1 筆", 1, len(reb_rows))
    check("中文簽名保留未遺失", True, "中文分岔錯誤訊息重複測試內容驗證" in reb_rows[0]["sig"])
    check("--rebuild 無殘留 .tmp", [], list(ledger2.parent.glob("*.tmp")))

    # 移除 ledger 尾端換行再做增量追加，並確認 --days 不會推進舊 STATE 游標
    raw_no_nl = ledger2.read_text(encoding="utf-8").rstrip("\n")
    ledger2.write_text(raw_no_nl, encoding="utf-8")
    state2 = home2 / ".claude" / "state" / "recurring-errors.last_run"
    old_cursor = time.time() - 10 * 86400
    os.utime(state2, (old_cursor, old_cursor))

    new_err = json.dumps({
        "type": "user",
        "timestamp": "not-a-valid-ts",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "new-tid-2", "is_error": True, "content": "second unique error message for append"}]},
    })
    (proj2 / "extra.jsonl").write_text(new_err + "\n", encoding="utf-8")
    r_days = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--days", "1"], env=env, capture_output=True, text=True)
    check("ad-hoc --days 1 正常執行", 0, r_days.returncode)
    check("ad-hoc --days 不覆寫既有 STATE 游標", True, abs(state2.stat().st_mtime - old_cursor) < 2.0)
    appended_rows = [json.loads(l) for l in ledger2.read_text(encoding="utf-8").splitlines() if l.strip()]
    check("缺尾端換行追加後兩筆 JSONL 皆可解析", 2, len(appended_rows))
    check("無效時間戳使用 UTC YYYY-MM-DD fallback", True, bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", appended_rows[1]["date"])))

    # --days <= 0 與缺 PROJECTS 目錄回傳 exit 2 且不覆寫既有 ledger
    snap = ledger2.read_text(encoding="utf-8")
    r_d0 = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--rebuild", "--days", "0"], env=env, capture_output=True, text=True)
    check("--days 0 回傳 exit 2", 2, r_d0.returncode)
    r_dneg = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--rebuild", "--days", "-2"], env=env, capture_output=True, text=True)
    check("--days -2 回傳 exit 2", 2, r_dneg.returncode)
    check("錯誤 --days 未動到既有 ledger", snap, ledger2.read_text(encoding="utf-8"))

    env_miss = env.copy()
    env_miss["HOME"] = str(Path(td) / "no-proj-home")
    Path(env_miss["HOME"]).mkdir()
    r_miss = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--rebuild"], env=env_miss, capture_output=True, text=True)
    check("缺 PROJECTS 目錄回傳 exit 2", 2, r_miss.returncode)

print(f"\n---- {PASS} passed, {FAIL} failed ----")
sys.exit(1 if FAIL else 0)
