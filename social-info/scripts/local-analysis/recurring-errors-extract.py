#!/usr/bin/env python3
"""recurring-errors-extract.py — recurring-errors channel 的確定性前段。

2026-08-01 從 recurring-errors-extract.sh 改寫。改寫理由不是「python 比較好」，是舊版的
bug 內生於它的結構：`jq ... | while IFS= read -r err` 按**行**迭代，一個多行錯誤訊息就被
拆成 N 個獨立簽名。實測 13 個錯誤產生 124 個簽名（9.5x），且排除首跑回填後的 top 15 裡有
11 個是同一則 dcg 攔截訊息的碎片——一次攔截佔掉 11 個名額，真正的行為問題被擠到第 9。
按行迭代要修就得脫離 shell 的 read 迴圈，所以整支改寫。

三個修正：
1. 一個錯誤 = 一個簽名（錯誤文字內的換行先壓成空白再正規化）
2. 日期用該筆錯誤的真實 timestamp，不是掃描當天（舊版 `date +%Y-%m-%d` 讓同一次回填的
   六個月資料全部標成同一天，趨勢與「跨多日」判斷都失真）
3. 去重用記憶體 set，不是對整個 ledger 跑 grep（舊版 O(n*m)，全量重建會慢到不可用）

正規化語意與舊版逐項對齊：小寫 → 去路徑 → 去長 hex → 去數字 → 壓空白 → 截 140 字 →
去頭尾空白 → 短於 15 字元丟棄。短簽名門檻是 `exit code` / `---` / `total` 這類碎片的濾網。

用法：
  python3 recurring-errors-extract.py            # 增量（state file 之後的新檔）
  python3 recurring-errors-extract.py --rebuild  # 全量重建（回看 180 天、覆寫 ledger）
  --days N     回看天數（預設增量吃 state、rebuild 吃 180）
  --dry-run    只印統計不寫檔
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
STATE = HOME / ".claude" / "state" / "recurring-errors.last_run"
LEDGER = HOME / "code" / "social-info" / "reports" / "local-analysis" / "recurring-errors-ledger.jsonl"

MIN_SIG_LEN = 15
MAX_SIG_LEN = 140

RE_PATH = re.compile(r"/\S+")
RE_HEX = re.compile(r"[0-9a-f]{8,}")
RE_NUM = re.compile(r"\d+")
RE_WS = re.compile(r"\s+")


def normalize(text):
    s = RE_WS.sub(" ", text.lower())
    s = RE_PATH.sub("", s)
    s = RE_HEX.sub("", s)
    s = RE_NUM.sub("", s)
    s = RE_WS.sub(" ", s).strip()
    return s[:MAX_SIG_LEN].strip()


def error_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return " ".join(
            x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"
        )
    return "" if c is None else str(c)


def iter_errors(path):
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                if '"is_error"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "user":
                    continue
                content = (d.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                ts = d.get("timestamp") or ""
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") != "tool_result" or not b.get("is_error"):
                        continue
                    txt = error_text(b)
                    if txt:
                        yield ts[:10], txt
    except OSError:
        return


def load_seen(ledger):
    seen = set()
    rows = 0
    if ledger.exists():
        with open(ledger, errors="ignore") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                seen.add((d.get("sig"), d.get("session")))
                rows += 1
    return seen, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    started = time.time()
    cutoff = None
    if args.rebuild:
        cutoff = time.time() - (args.days or 180) * 86400
    elif args.days is not None:
        cutoff = time.time() - args.days * 86400
    elif STATE.exists():
        cutoff = STATE.stat().st_mtime

    files = []
    for p in PROJECTS.rglob("*.jsonl"):
        if "/subagents/" in str(p):
            continue
        try:
            if cutoff is not None and p.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        files.append(p)

    if args.rebuild:
        seen, prior = set(), 0
    else:
        seen, prior = load_seen(LEDGER)

    out = []
    scanned = 0
    raw_errors = 0
    for p in files:
        scanned += 1
        session = p.stem
        for date, txt in iter_errors(p):
            raw_errors += 1
            sig = normalize(txt)
            if len(sig) < MIN_SIG_LEN:
                continue
            key = (sig, session)
            if key in seen:
                continue
            seen.add(key)
            out.append({"date": date or time.strftime("%Y-%m-%d"), "sig": sig, "session": session})

    if args.dry_run:
        print(
            f"DRY-RUN scanned={scanned} raw_errors={raw_errors} new_rows={len(out)} "
            f"prior_rows={prior} elapsed={time.time() - started:.1f}s"
        )
        return

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if args.rebuild else "a"
    tmp = LEDGER.with_suffix(".jsonl.tmp")
    if args.rebuild:
        with open(tmp, "w") as f:
            for row in out:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, LEDGER)
        total = len(out)
    else:
        with open(LEDGER, mode) as f:
            for row in out:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        total = prior + len(out)

    STATE.touch()
    print(f"scanned={scanned} ledger_total={total}")


if __name__ == "__main__":
    sys.exit(main())
