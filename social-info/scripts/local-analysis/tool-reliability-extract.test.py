#!/usr/bin/env python3
"""tool-reliability-extract.py 的回歸 fixture。

跑法：python3 tool-reliability-extract.test.py
鎖住的線：
  (1) tool_use_id 配對正確（錯誤歸給對的工具，不是隔壁那個）
  (2) 孤兒 tool_result（配不到 tool_use）不得混入統計
  (3) ISO 週切分正確、跨年邊界不炸
  (4) 樣本門檻：呼叫數不足時不輸出比率（分母太小的比率是假訊號）
  (5) 全量重算冪等——同一份輸入跑兩次結果相同（本檔刻意無增量模式，這條防有人加回來）
"""

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "trx", Path(__file__).parent / "tool-reliability-extract.py"
)
trx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trx)

PASS = FAIL = 0


def check(name, want, got):
    global PASS, FAIL
    if want == got:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}\n        want {want!r}\n        got  {got!r}")
        FAIL += 1


def mkfile(path, entries):
    lines = []
    for e in entries:
        lines.append(json.dumps(e))
    Path(path).write_text("\n".join(lines))


def use(tid, name, ts="2026-07-28T10:00:00.000Z"):
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {"content": [{"type": "tool_use", "id": tid, "name": name}]},
    }


def result(tid, err, ts="2026-07-28T10:00:01.000Z"):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": tid, "is_error": err, "content": "x"}]
        },
    }


print("\n=== 配對正確性：錯誤要歸給對的工具 ===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "s.jsonl"
    mkfile(
        p,
        [
            use("t1", "Bash"),
            use("t2", "Read"),
            use("t3", "Bash"),
            result("t1", True),
            result("t2", False),
            result("t3", False),
        ],
    )
    got = trx.scan_file(p)
    check("抽出 3 筆配對", 3, len(got))
    by_tool = {}
    for wk, tool, err in got:
        by_tool.setdefault(tool, [0, 0])
        by_tool[tool][0] += 1
        if err:
            by_tool[tool][1] += 1
    check("Bash 2 呼叫 1 錯", [2, 1], by_tool.get("Bash"))
    check("Read 1 呼叫 0 錯", [1, 0], by_tool.get("Read"))

print("\n=== 孤兒 tool_result 不得混入 ===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "s.jsonl"
    mkfile(p, [use("t1", "Bash"), result("t1", False), result("ORPHAN", True)])
    got = trx.scan_file(p)
    check("只算配對得上的 1 筆", 1, len(got))
    check("孤兒的錯誤沒被算進去", False, any(e for _, _, e in got))

print("\n=== ISO 週切分 ===")
check("2026-07-28 → W31", "2026-W31", trx.iso_week("2026-07-28T00:00:00.000Z"))
check("2026-08-01 同週", "2026-W31", trx.iso_week("2026-08-01T00:00:00.000Z"))
check("2026-08-03 進 W32", "2026-W32", trx.iso_week("2026-08-03T00:00:00.000Z"))
check("跨年 2027-01-01 屬 2026-W53", "2026-W53", trx.iso_week("2027-01-01T00:00:00.000Z"))
check("空 timestamp → None", None, trx.iso_week(""))
check("壞格式 → None", None, trx.iso_week("not-a-date"))

print("\n=== 壞資料容忍 ===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "s.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps(use("t1", "Bash")),
                "{ broken json",
                json.dumps({"type": "assistant", "message": {"content": "not-a-list"}}),
                json.dumps(result("t1", True)),
            ]
        )
    )
    got = trx.scan_file(p)
    check("壞行跳過、有效的仍抽到", 1, len(got))

print("\n=== 樣本門檻：分母不足不出比率 ===")
check("門檻常數存在", True, isinstance(trx.MIN_CALLS_FOR_RATE, int))
check("門檻 >= 20（避免小分母假訊號）", True, trx.MIN_CALLS_FOR_RATE >= 20)

print("\n=== 冪等：同輸入跑兩次結果相同（防有人加回增量造成雙重計數）===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "s.jsonl"
    mkfile(p, [use("t1", "Bash"), result("t1", True)])
    a = trx.scan_file(p)
    b = trx.scan_file(p)
    check("兩次掃描結果一致", a, b)
    check("不會累加（各 1 筆）", (1, 1), (len(a), len(b)))

print("\n=== 重複 tool_use_id 去重（同檔與跨檔分岔）===")
with tempfile.TemporaryDirectory() as td:
    p1 = Path(td) / "parent.jsonl"
    p2 = Path(td) / "fork.jsonl"
    mkfile(p1, [use("t1", ""), use("t1", "Bash"), result("t1", True), use("t1", "Read"), result("t1", True)])
    check("同 ID 重播保留首個合法工具名稱", [("2026-W31", "Bash", True)], trx.scan_file(p1))
    mkfile(p2, [use("t1", "Bash"), result("t1", True), use("t2", "Read"), result("t2", False)])
    check("單檔重複 tool_result 去重為 1 筆", 1, len(trx.scan_file(p1)))
    shared_seen = set()
    g1 = trx.scan_file(p1, seen_tids=shared_seen)
    g2 = trx.scan_file(p2, seen_tids=shared_seen)
    check("跨檔分岔共享 tool_use_id 去重", 2, len(g1) + len(g2))

print("\n=== 壞型別／None-ID 孤兒／字串 false／時區歸一化 ===")
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "weird.jsonl"
    p.write_text(
        "\n".join(
            [
                '["tool_use"]',
                json.dumps({"type": "assistant", "timestamp": "2026-07-28T10:00:00Z", "message": "bad"}),
                json.dumps({"type": "assistant", "timestamp": "2026-07-28T10:00:00Z", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}),
                json.dumps({"type": "user", "timestamp": "2026-07-28T10:00:01Z", "message": {"content": [{"type": "tool_result", "is_error": True}]}}),
                json.dumps({"type": "assistant", "timestamp": "2026-07-28T10:00:02Z", "message": {"content": [{"type": "tool_use", "id": ["bad"], "name": ["Bash"]}]}}),
                json.dumps({"type": "assistant", "timestamp": "2026-07-28T10:00:02Z", "message": {"content": [{"type": "tool_use", "id": "t-ok", "name": "Read"}]}}),
                json.dumps({"type": "user", "timestamp": "2026-07-28T10:00:03Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "t-ok", "is_error": "false"}]}}),
            ]
        ),
        encoding="utf-8",
    )
    got = trx.scan_file(p)
    check("None-ID 孤兒不誤配且字串 false 不算錯", [("2026-W31", "Read", False)], got)

check("非字串 True timestamp → None", None, trx.iso_week(True))
check("同瞬時 UTC 與 +08:00 歸同一 ISO 週", "2026-W31", trx.iso_week("2026-08-03T04:00:00+08:00"))
check("數值時間戳不會轉成 ISO 週", [None, None], [trx.iso_week(ts) for ts in (42, 1785614400.0)])
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "numeric.jsonl"
    mkfile(p, [use("t1", "Bash"), result("t1", True, 42), result("t1", False)])
    check("數值時間戳略過且不會搶先佔用 ID", [("2026-W31", "Bash", False)], trx.scan_file(p))

print("\n=== 事件級 cutoff、ASCII locale 編碼、參數校驗與 --report 行為 ===")
SCRIPT_PY = Path(__file__).parent / "tool-reliability-extract.py"
with tempfile.TemporaryDirectory() as td:
    home = Path(td) / "home"
    proj = home / ".claude" / "projects" / "p1"
    proj.mkdir(parents=True)
    now_dt = dt.datetime.now(dt.timezone.utc)
    cur_ts = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_ts = (now_dt - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_ts = "2025-01-15T10:00:00Z"

    # 建立舊事件 + 前週 25 筆 (0 錯) + 本週 25 筆 (5 錯 = 20%) + 小分母工具 5 筆 + 中文工具名 1 筆
    entries = [use("old-1", "Bash", old_ts), result("old-1", True, old_ts)]
    for i in range(25):
        entries.append(use(f"p-{i}", "Bash", prev_ts))
        entries.append(result(f"p-{i}", False, prev_ts))
    for i in range(25):
        entries.append(use(f"c-{i}", "Bash", cur_ts))
        entries.append(result(f"c-{i}", i < 5, cur_ts))
    for i in range(5):
        entries.append(use(f"s-{i}", "TinyTool", cur_ts))
        entries.append(result(f"s-{i}", True, cur_ts))
    entries.append(use("zh-1", "中文工具", cur_ts))
    entries.append(result("zh-1", False, cur_ts))
    (proj / "sess.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["PYTHONCOERCECLOCALE"] = "0"
    env["PYTHONUTF8"] = "0"

    r_run = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--days", "14"], env=env, capture_output=True, text=True)
    check("ASCII locale 正常執行寫出中文工具", 0, r_run.returncode)
    out_file = home / "code" / "social-info" / "reports" / "local-analysis" / "tool-reliability.jsonl"
    rows = [json.loads(l) for l in out_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    check("cutoff 攔截過期 2025-W03 事件", False, any(r["week"] == "2025-W03" for r in rows))
    check("中文工具名完整保留", True, any(r["tool"] == "中文工具" for r in rows))
    check("寫入後無殘留 .tmp 檔", [], list(out_file.parent.glob("*.tmp")))

    # 在 jsonl 塞入壞行確認 --report 容忍並正確輸出門檻與值得看
    with open(out_file, "a", encoding="utf-8") as fh:
        fh.write("[]\n" + json.dumps({"week": "2026-W99", "tool": "Bad", "calls": "nan", "errors": 0}) + "\n")
    r_rep = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--report"], env=env, capture_output=True, text=True)
    check("--report 正常結束", 0, r_rep.returncode)
    check("--report 偵測 Bash 變動進值得看", True, "`Bash`" in r_rep.stdout and "20%" in r_rep.stdout)
    check("--report 小分母工具未列入表格且標註計數", True, "| TinyTool |" not in r_rep.stdout and "另有 2 個工具" in r_rep.stdout)

    # 錯誤參數與缺目錄不可清檔並須回傳非零
    before_text = out_file.read_text(encoding="utf-8")
    r_zero = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--days", "0"], env=env, capture_output=True, text=True)
    check("--days 0 回傳 exit 2", 2, r_zero.returncode)
    r_neg = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--days", "-3"], env=env, capture_output=True, text=True)
    check("--days -3 回傳 exit 2", 2, r_neg.returncode)
    check("錯誤參數未破壞既有 jsonl", before_text, out_file.read_text(encoding="utf-8"))

    env_miss = env.copy()
    env_miss["HOME"] = str(Path(td) / "empty-home")
    Path(env_miss["HOME"]).mkdir()
    r_miss = subprocess.run([sys.executable, "-B", str(SCRIPT_PY)], env=env_miss, capture_output=True, text=True)
    check("缺 PROJECTS 目錄回傳 exit 2", 2, r_miss.returncode)
    r_no_out = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--report"], env=env_miss, capture_output=True, text=True)
    check("--report 缺資料檔回傳 exit 1", 1, r_no_out.returncode)
    check("--report 缺資料檔錯誤訊息寫到 stderr", True, len(r_no_out.stderr.strip()) > 0 and r_no_out.stdout == "")

print("\n=== 週報錯誤率恰差三個百分點 ===")
with tempfile.TemporaryDirectory() as td:
    data = Path(td) / "week.jsonl"
    mkfile(data, [
        {"week": "2026-W30", "tool": tool, "calls": 100, "errors": old}
        for tool, old in [("Increase", 26), ("Decrease", 29), ("Below", 26)]
    ] + [
        {"week": "2026-W31", "tool": tool, "calls": 100, "errors": new}
        for tool, new in [("Increase", 29), ("Decrease", 26), ("Below", 28)]
    ])
    env = dict(os.environ, TOOL_RELIABILITY_DATA_FILE=str(data))
    rep = subprocess.run([sys.executable, "-B", str(SCRIPT_PY), "--report"], env=env, capture_output=True, text=True)
    check("門檻週報回傳成功", 0, rep.returncode)
    check("26% → 29% 恰差 +3% 觸發告警", True, "- `Increase` 26% → 29%（+3%" in rep.stdout)
    check("29% → 26% 恰差 -3% 觸發告警", True, "- `Decrease` 29% → 26%（-3%" in rep.stdout)
    check("未達三個百分點仍僅列全量表", (False, True), ("- `Below`" in rep.stdout, "| Below |" in rep.stdout))

print(f"\n---- {PASS} passed, {FAIL} failed ----")
sys.exit(1 if FAIL else 0)
