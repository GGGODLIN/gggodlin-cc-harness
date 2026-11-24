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
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile
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
    if not isinstance(text, str):
        return ""
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
            x["text"]
            for x in c
            if isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str)
        )
    return "" if c is None else str(c)


def _extract_date(ts):
    if not isinstance(ts, str) or not (s := ts.strip()):
        return ""
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is not None:
            d = d.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError):
        return ""
    return d.date().isoformat()


def _iter_error_records(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"is_error"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not isinstance(d, dict) or d.get("type") != "user":
                    continue
                msg = d.get("message")
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                date_s = _extract_date(d.get("timestamp"))
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") != "tool_result" or b.get("is_error") is not True:
                        continue
                    txt = error_text(b)
                    if txt:
                        tuid = b.get("tool_use_id")
                        tuid_s = tuid if isinstance(tuid, str) else ""
                        yield date_s, txt, tuid_s
    except OSError:
        return


def iter_errors(path):
    for date_s, txt, _ in _iter_error_records(path):
        yield date_s, txt


def _load_seen_with_tids(ledger):
    seen = set()
    seen_tids = set()
    rows = 0
    if ledger.exists():
        with open(ledger, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not isinstance(d, dict):
                    continue
                sig = d.get("sig")
                session = d.get("session")
                if isinstance(sig, str) and isinstance(session, str):
                    seen.add((sig, session))
                tid = d.get("tool_use_id")
                if isinstance(tid, str) and tid:
                    seen_tids.add(tid)
                rows += 1
    return seen, seen_tids, rows


def load_seen(ledger):
    seen, _, rows = _load_seen_with_tids(ledger)
    return seen, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.days is not None and args.days < 1:
        print("Error: --days must be >= 1", file=sys.stderr)
        return 2

    if not PROJECTS.is_dir():
        print(f"Error: projects directory does not exist: {PROJECTS}", file=sys.stderr)
        return 2

    started = time.time()
    cutoff = None
    if args.rebuild:
        days = args.days if args.days is not None else 180
        cutoff = started - days * 86400
    elif args.days is not None:
        cutoff = started - args.days * 86400
    elif STATE.exists():
        cutoff = STATE.stat().st_mtime

    files = []
    for p in sorted(PROJECTS.rglob("*.jsonl")):
        if "/subagents/" in str(p):
            continue
        try:
            # 檔案可能在游標所記錄的同一秒內追加資料，等於游標時也要重掃。
            if cutoff is not None and p.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        files.append(p)

    if args.rebuild:
        seen, seen_tids, prior = set(), set(), 0
    else:
        seen, seen_tids, prior = _load_seen_with_tids(LEDGER)

    out = []
    scanned = 0
    raw_errors = 0
    fallback_date = time.strftime("%Y-%m-%d", time.gmtime(started))
    for p in files:
        scanned += 1
        session = p.stem
        for date, txt, tuid in _iter_error_records(p):
            raw_errors += 1
            sig = normalize(txt)
            if len(sig) < MIN_SIG_LEN:
                continue
            if tuid and tuid in seen_tids:
                continue
            key = (sig, session)
            if key in seen:
                continue
            seen.add(key)
            if tuid:
                seen_tids.add(tuid)
            row = {"date": date or fallback_date, "sig": sig, "session": session}
            if tuid:
                row["tool_use_id"] = tuid
            out.append(row)

    if args.dry_run:
        print(
            f"DRY-RUN scanned={scanned} raw_errors={raw_errors} new_rows={len(out)} "
            f"prior_rows={prior} elapsed={time.time() - started:.1f}s"
        )
        return 0

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if args.rebuild:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=LEDGER.parent,
                prefix=LEDGER.name + ".",
                suffix=".tmp",
                delete=False,
            ) as f:
                tmp_path = f.name
                for row in out:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp_path, LEDGER)
            tmp_path = None
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        total = len(out)
    else:
        need_leading_nl = False
        if out and LEDGER.exists():
            try:
                if LEDGER.stat().st_size > 0:
                    with open(LEDGER, "rb") as rf:
                        rf.seek(-1, os.SEEK_END)
                        need_leading_nl = rf.read(1) != b"\n"
            except OSError:
                pass
        with open(LEDGER, "a", encoding="utf-8") as f:
            if need_leading_nl:
                f.write("\n")
            for row in out:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        total = prior + len(out)

    # 只在全量重建或常規增量模式更新游標；使用掃描起點而非結束時刻，避免掃描期間追加的錯誤下輪漏計
    if args.rebuild or args.days is None:
        STATE.touch()
        cursor_ts = math.floor(started)
        os.utime(STATE, (cursor_ts, cursor_ts))
    print(f"scanned={scanned} ledger_total={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
