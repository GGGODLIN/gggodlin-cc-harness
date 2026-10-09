#!/usr/bin/env python3
"""tool-reliability-extract.py — per-tool 可靠度統計（2026-08-01 建，HKUDS/OpenSpace 抽件 2）。

問題：既有 recurring-errors ledger 記的是「錯誤簽名」，不知道錯誤是哪個工具吐的。
所以答不出「哪個工具最容易掛」「這週有沒有變差」。

做法：唯讀掃 session jsonl，用 tool_use_id 把 assistant 的 tool_use（有工具名）
跟 user 的 tool_result（有 is_error）配對，按 ISO 週 × 工具聚合。實測配對率 100%。

**既有 recurring-errors-ledger.jsonl 零改動**——那支管錯誤簽名去重，這支管工具歸因，
兩件事分開。本檔的輸出 100% 是衍生資料，砍掉重算隨時可以。

設計取捨（拍板紀錄）：
- **不收 latency**。p50/p95 算得出來，但同一則 assistant 訊息內並行發出的工具**共用一個
  timestamp**，平行批次會系統性失真；且「多慢算慢」是使用者要定的門檻。沒有門檻與消費者
  之前收集它，就會重演 OpenSpace 那個「量了一堆沒人看」的失敗模式。
- **不設警報門檻**。第一次量，沒人知道 Agent 12.8% 算高還是正常。先讓數字可得、累積幾週
  有體感再定閾值——閾值拍歪的代價（誤報讓人以後忽略這個 channel）比沒閾值更糟。
- **趨勢看週對週**，不是絕對值。這是使用者 2026-08-01 拍板：「第一次就先報，之後長期趨勢
  穩定的話就不用報，也就是還是看趨勢的」。

**永遠全量重算、沒有增量模式**——這是刻意的。session jsonl 會持續被追加，mtime 跟著更新，
增量會把同一個檔的既有計數再加一次。全掃 180 天約 10 秒，不值得為此背一個雙重計數的 bug。
輸出是純衍生資料，砍掉重算隨時可以。

用法：
  python3 tool-reliability-extract.py                # 全量重算（預設回看 180 天）
  python3 tool-reliability-extract.py --report       # 印人讀週報（給 weekly channel 用）
  --days N（改回看天數）/ --dry-run

輸出：~/code/social-info/reports/local-analysis/tool-reliability.jsonl
每行 {week, tool, calls, errors, rate}，week 為 ISO 年-週（2026-W31）。
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
OUT = HOME / "code" / "social-info" / "reports" / "local-analysis" / "tool-reliability.jsonl"

MIN_CALLS_FOR_RATE = 20
DELTA_ALERT = 0.03
HIGH_RATE = 0.15
TOP_NOTABLE = 5


def iso_week(ts):
    if not ts:
        return None
    try:
        d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def scan_file(path):
    names = {}
    pairs = []
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                msg = d.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                if d.get("type") == "assistant":
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            names[b.get("id")] = b.get("name")
                elif d.get("type") == "user":
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            pairs.append(
                                (b.get("tool_use_id"), bool(b.get("is_error")), d.get("timestamp"))
                            )
    except OSError:
        return []
    out = []
    for tid, err, ts in pairs:
        name = names.get(tid)
        if not name:
            continue
        wk = iso_week(ts)
        if wk:
            out.append((wk, name, err))
    return out


def write_agg(agg):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".jsonl.tmp")
    with open(tmp, "w") as f:
        for (wk, tool), (calls, errors) in sorted(agg.items()):
            rate = round(errors / calls, 4) if calls else 0.0
            f.write(
                json.dumps(
                    {"week": wk, "tool": tool, "calls": calls, "errors": errors, "rate": rate},
                    ensure_ascii=False,
                )
                + "\n"
            )
    os.replace(tmp, OUT)


def report():
    rows = defaultdict(lambda: [0, 0])
    if not OUT.exists():
        print("尚無資料，先跑一次 tool-reliability-extract.py")
        return
    with open(OUT, errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            rows[(d["week"], d["tool"])] = [d["calls"], d["errors"]]
    weeks = sorted({k[0] for k in rows})
    if not weeks:
        print("尚無資料")
        return
    cur = weeks[-1]
    prev = weeks[-2] if len(weeks) > 1 else None

    sized = []
    small_n = small_calls = 0
    for (w, t), (calls, errors) in rows.items():
        if w != cur:
            continue
        if calls < MIN_CALLS_FOR_RATE:
            small_n += 1
            small_calls += calls
            continue
        rate = errors / calls
        pv = rows.get((prev, t)) if prev else None
        prate = pv[1] / pv[0] if pv and pv[0] >= MIN_CALLS_FOR_RATE else None
        sized.append((t, calls, errors, rate, prate))

    print(f"## 工具可靠度：{cur}" + (f"（對照 {prev}）" if prev else "（無前一週可比）"))
    print()

    notable = []
    for t, calls, errors, rate, prate in sized:
        if prate is not None and abs(rate - prate) >= DELTA_ALERT:
            notable.append((abs(rate - prate), t, calls, errors, rate, prate))
        elif prate is None and rate >= HIGH_RATE:
            notable.append((rate, t, calls, errors, rate, None))
    notable.sort(reverse=True)

    if notable:
        print(f"**值得看（錯誤率變動 ≥{DELTA_ALERT:.0%} 或新工具錯誤率 ≥{HIGH_RATE:.0%}）**")
        print()
        for _, t, calls, errors, rate, prate in notable[:TOP_NOTABLE]:
            if prate is None:
                print(f"- `{t}` {rate:.0%}（{errors}/{calls}）— 無前週基期")
            else:
                d = rate - prate
                print(
                    f"- `{t}` {prate:.0%} → {rate:.0%}（{d:+.0%}，{errors}/{calls}）"
                )
        print()
    else:
        print("**值得看**：無——所有工具錯誤率與前週差異均在門檻內")
        print()

    print("<details><summary>全部工具（本週呼叫 ≥ %d）</summary>" % MIN_CALLS_FOR_RATE)
    print()
    print("| 工具 | 呼叫 | 錯誤 | 錯誤率 | 前週 |")
    print("|---|---|---|---|---|")
    for t, calls, errors, rate, prate in sorted(sized, key=lambda x: -x[1]):
        pr = f"{prate:.1%}" if prate is not None else "—"
        print(f"| {t} | {calls} | {errors} | {rate:.1%} | {pr} |")
    print()
    print("</details>")
    print()
    print(
        f"（本週另有 {small_n} 個工具呼叫數 < {MIN_CALLS_FOR_RATE}、合計 {small_calls} 次，"
        f"分母太小不計比率；歷史週數 {len(weeks)}：{weeks[0]} → {weeks[-1]}）"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.report:
        report()
        return

    started = time.time()
    cutoff = time.time() - (args.days or 180) * 86400

    files = []
    for p in PROJECTS.rglob("*.jsonl"):
        if "/subagents/" in str(p):
            continue
        try:
            if p.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        files.append(p)

    agg = defaultdict(lambda: [0, 0])
    scanned = 0
    added = 0
    for p in files:
        scanned += 1
        for wk, tool, err in scan_file(p):
            agg[(wk, tool)][0] += 1
            added += 1
            if err:
                agg[(wk, tool)][1] += 1

    if args.dry_run:
        print(
            f"DRY-RUN scanned={scanned} pairs={added} groups={len(agg)} "
            f"elapsed={time.time() - started:.1f}s"
        )
        return

    write_agg(agg)
    print(f"scanned={scanned} pairs={added} groups={len(agg)}")


if __name__ == "__main__":
    sys.exit(main())
