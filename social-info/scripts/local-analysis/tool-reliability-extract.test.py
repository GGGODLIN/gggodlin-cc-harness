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

import importlib.util
import json
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

print(f"\n---- {PASS} passed, {FAIL} failed ----")
sys.exit(1 if FAIL else 0)
