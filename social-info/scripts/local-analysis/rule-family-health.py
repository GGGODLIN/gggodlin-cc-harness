#!/usr/bin/env python3
"""rule-family-health.py — rule-adherence-ledger 的家族聚合層（2026-07-25 加）

Why: ledger 的 `rule` 欄是 LLM 每天自由書寫的規則名，同一條規則會分裂成十幾個變體字串
（例：「宣稱與證據層級對位」後面掛五種不同括號補述）。單一 rule 字串的 >=3 escalation
閾值因此永遠抓不到真正的集中度——30 天 110 次糾正裡證據類佔 46 次、白話類 22 次，
合計 62% 卻沒有任何一條 rule 字串越過閾值。

本 script 把 rule 字串歸併成穩定家族再統計。優先讀 entry 自帶的 `rule_family` 欄
（recap prompt 從 2026-07-25 起會寫），缺欄則用關鍵字 fallback，舊 entry 無需 migration。

⚠️ `unclassified` 在 2026-08-25 之前混有兩種成因，門檻誤觸請先分辨再判斷：
  (1) writer 明寫 `rule_family: "unclassified"` = 8 家族 enum 真的裝不下 → 這才是「該檢討 enum」
  (2) entry 無 `rule_family` 欄（2026-07-26 之前的舊格式，欄位覆蓋率 0% → 100% 當天切換）
      走下面的 regex fallback 而漏接 → 這只是關鍵字表不全，跟 enum 夠不夠用無關
  2026-08-01 實例：unclassified 踩到 5 次門檻，但 3 筆屬 (2)、只有 2 筆屬 (1)；而且最舊那筆
  08-06 就離開 30 天窗口、警報會自己停 → 當時的計數量的是「窗口裡剩多少舊格式資料」而非 enum 健康度。
  最後一筆無欄位 entry 是 2026-07-25，故 2026-08-25 起任何 30 天窗口都不再有 (2)、此混淆自動消失。
  分辨方法：對 unclassified 的 entry 看 `rule_family` 欄存不存在，存在且值為 unclassified 才算 (1)。

Usage:
  python3 rule-family-health.py [--days 30] [--ledger PATH] [--json]
"""

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

DEFAULT_LEDGER = os.path.expanduser(
    "~/code/social-info/reports/local-analysis/rule-adherence-ledger.jsonl"
)

# family -> 關鍵字（任一命中即歸入；由上而下第一個命中者勝，順序即優先級）
FAMILY_PATTERNS = [
    ("evidence-level", r"證據|驗證|實證|行為數據|附出處|憑印象|憑推測|推估|斷言"),
    ("plain-language", r"白話|晶晶體|措詞|措辭|繁體中文|翻成中文"),
    ("self-research-first", r"自己查|先查|先搜|research-before-answer|查事實|不憑猜|不要問使用者"),
    ("ask-vs-decide", r"停下問|拍板|討論模式|一次收斂|訪談|越權|未經拍板|問之前先分工"),
    ("scope-discipline", r"只改|無關 code|修改範圍|修改前先閱讀|不動全域"),
    ("process-completeness", r"skill 流程|流程完整|不省略|Trial|固化|archive"),
    ("output-delivery", r"最終訊息|最終聊天訊息|連結格式|URL|呈現|報告|日期牆"),
    ("tooling-routing", r"抓取路由|fetch|chrome|帳號判準|工具評估"),
]


def classify(entry):
    fam = (entry.get("rule_family") or "").strip()
    if fam:
        return fam
    rule = entry.get("rule") or ""
    for name, pattern in FAMILY_PATTERNS:
        if re.search(pattern, rule):
            return name
    return "unclassified"


def load(ledger_path, days):
    cutoff = dt.date.today() - dt.timedelta(days=days)
    rows = []
    with open(ledger_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("kind") != "rule_violation":
                continue
            try:
                when = dt.date.fromisoformat(entry.get("date", ""))
            except ValueError:
                continue
            if when >= cutoff:
                rows.append(entry)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--family-threshold", type=int, default=5)
    ap.add_argument("--rule-threshold", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.ledger):
        print(f"ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    rows = load(args.ledger, args.days)
    total = len(rows)
    fam_counts = collections.Counter(classify(r) for r in rows)
    rule_counts = collections.Counter(r.get("rule", "") for r in rows)

    fam_alerts = [
        {"family": f, "count": n, "share": round(n / total * 100, 1) if total else 0.0}
        for f, n in fam_counts.most_common()
        if n >= args.family_threshold
    ]
    rule_alerts = [
        {"rule": r, "count": n}
        for r, n in rule_counts.most_common()
        if n >= args.rule_threshold and r
    ]

    result = {
        "days": args.days,
        "total_violations": total,
        "distinct_rule_strings": len([r for r in rule_counts if r]),
        "families": [
            {"family": f, "count": n, "share": round(n / total * 100, 1) if total else 0.0}
            for f, n in fam_counts.most_common()
        ],
        "family_alerts": fam_alerts,
        "rule_alerts": rule_alerts,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"近 {args.days} 天 rule_violation: {total} 次 / {result['distinct_rule_strings']} 種 rule 字串")
    print(f"\n家族分佈（閾值 >={args.family_threshold} 觸發 ⚠）:")
    for f in result["families"]:
        mark = " ⚠" if f["count"] >= args.family_threshold else ""
        print(f"  {f['count']:4d}  {f['share']:5.1f}%  {f['family']}{mark}")
    if rule_alerts:
        print(f"\n單一 rule 字串 >={args.rule_threshold}:")
        for r in rule_alerts:
            print(f"  {r['count']:4d}  {r['rule'][:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
