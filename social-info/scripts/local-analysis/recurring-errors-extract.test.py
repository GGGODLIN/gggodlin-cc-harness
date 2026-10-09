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
import re
import subprocess
import sys
import tempfile
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

print(f"\n---- {PASS} passed, {FAIL} failed ----")
sys.exit(1 if FAIL else 0)
