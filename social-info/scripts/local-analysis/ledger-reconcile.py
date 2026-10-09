#!/usr/bin/env python3
"""ledger-reconcile.py — pending-actions.jsonl 的確定性對帳層（2026-07-30 加）

Why: digest 的排檔規則裡有一半根本不需要判斷力——`next_due` 比日期、`escalate_at`
比計數、observing/kept 靜默、count 同日不重複累加、家族計數口徑，全都是算術。
把算術交給 LLM 的代價已經量化過：pending-actions.jsonl 178 筆裡有 21 筆（12%）的
note 記載 channel 判斷本身錯，而其中最頑固的一類是「規則明明在 prompt 裡、加粗過，
還是照抄了凍結的舊數字」（2026-07-28「30 天內第 3 次」vs 家族實際 8 次）。那類錯
不是規則沒送達造成的，送十遍也一樣——只有把它從 LLM 手上拿走才會消失。

設計接縫（唯一留給 LLM 的判斷）：
  LLM 只負責語意比對——今天各 channel 的 finding 對應到 ledger 哪一筆既有 title
  （同一件事不同措辭算同一筆），以及最後排 🔴/🟡/🔵 哪一檔。
  其餘一律本腳本算：計數、狀態閘、靜默判定、強制升檔、可查物存在性證據、家族計數。

刻意不做的事（誠實的邊界）：
  本腳本**不判斷「問題是否已解決」**。它只回報可查物的存在性證據（檔案在不在、
  wikilink 解不解得開），因為「修 X 檔的 Y 欄位」這種項目，X 存在與否跟 Y 有沒有修好
  無關——存在性能證偽一部分誤報，不能證實「已修」。verdict 留給有脈絡的那一層，
  但證據已經先查好、不必依賴誰記得要查。

Usage:
  ledger-reconcile.py --date 2026-07-30                      # dry-run，只輸出對帳結果
  ledger-reconcile.py --date 2026-07-30 --findings f.json    # 併入今日 finding
  ledger-reconcile.py --date 2026-07-30 --findings f.json --apply   # 寫回 ledger
  ledger-reconcile.py --date 2026-07-30 --decide d.json --apply     # 寫回使用者拍板
  ledger-reconcile.py --date 2026-07-30 --json               # 機器可讀

findings.json schema（LLM 產出，只含語意判斷）:
  [{"title": "<標題>", "match": "<既有 ledger title 或 null>", "channel": "<channel key>",
    "source_key": "<確定性來源識別，選填>"}]

decide.json schema（使用者拍板的轉寫，status 轉換的唯一機械路徑）:
  [{"match": "<既有 ledger title>", "verdict": "done|killed|kept|observing|pending",
    "note": "<證據或原因>", "escalate_at": <int 選填>, "next_due": "<YYYY-MM-DD 選填>"}]

  status 屬 human-controlled surface：只有使用者拍板才會變。走 --decide 而不是手改
  jsonl 的理由是把最後一條「LLM 直接編輯 ledger」的路也關掉——2026-07-30 手寫一次性
  腳本改 status 時就漏帶了一條 entry（靠腳本印出的剩餘清單才發現對不上）。
  verdict 值不在白名單、或 match 指不到既有 title → 非 0 退出，不靜默跳過。
"""

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date as calendar_date, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LEDGER = os.path.join(DIR, "..", "..", "reports", "local-analysis", "pending-actions.jsonl")
HEALTH = os.path.join(DIR, "rule-family-health.py")
HOME = os.path.expanduser("~")

TERMINAL = ("done", "killed")
ALLOWED_FINDING_CHANNELS = frozenset({
    "memory", "wiki-candidates", "wiki-cross-link", "wiki-graduation", "wiki-lint",
    "wiki-stale", "deep-research-pending", "skill-desc-quality", "recap", "codemap",
    "distill", "recurring-errors", "rba-verify", "bumblebee", "symlink", "skill-upstream",
    "skill-doctor", "tool-updates", "codex-violation", "rules-size", "ledger-lifecycle", "skill-collision",
    "agnix", "skill-trigger", "skill-changes", "evidence-level", "ccp-free-watch", "path-rot", "free-pool", "codex-cdp",
})
PATH_RE = re.compile(r"(~?/[\w./@-]+\.\w{1,6}|[\w-]+\.(?:md|sh|py|js|mjs|json|jsonl|txt|toml))")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
SOURCE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{2,127}$")

FAMILY_KEYS = (
    "plain-language", "evidence-level", "self-research-first", "ask-vs-decide",
    "scope-discipline", "process-completeness", "output-delivery", "tooling-routing",
)


def parse_calendar_date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        sys.exit(f"{label} must use YYYY-MM-DD and be a valid calendar date")
    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError:
        sys.exit(f"{label} must use YYYY-MM-DD and be a valid calendar date")
    if parsed.isoformat() != value:
        sys.exit(f"{label} must use YYYY-MM-DD and be a valid calendar date")
    return parsed


def load_ledger(path):
    rows = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as e:
                sys.exit(f"ledger line {i} is not valid JSON: {e}")
    return rows


def write_ledger(path, rows):
    directory = os.path.dirname(path) or "."
    prefix = f".{os.path.basename(path)}."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def family_counts():
    try:
        out = subprocess.run(
            [sys.executable, HEALTH, "--json"], capture_output=True, text=True, timeout=60
        )
        data = json.loads(out.stdout)
    except Exception:
        return {}
    for key in ("families", "family_counts", "by_family"):
        if isinstance(data.get(key), dict):
            return data[key]
        if isinstance(data.get(key), list):
            return {d.get("family"): d.get("count") for d in data[key] if isinstance(d, dict)}
    return {k: v for k, v in data.items() if k in FAMILY_KEYS}


def resolve_wikilink(slug):
    slug = slug.split("#")[0].strip()
    if not slug:
        return False
    if os.path.isfile(f"{HOME}/.claude/wiki/{slug}.md"):
        return True
    mem = f"{HOME}/.claude/memory"
    if os.path.isfile(f"{mem}/{slug}.md"):
        return True
    for root, _dirs, files in os.walk(mem):
        if f"{slug}.md" in files:
            return True
        for fn in files:
            if not fn.endswith(".md"):
                continue
            try:
                with open(os.path.join(root, fn), errors="replace") as f:
                    head = f.read(400)
            except OSError:
                continue
            if re.search(rf"^name:\s*{re.escape(slug)}\s*$", head, re.M):
                return True
    return False


def expand(target):
    t = target.strip().rstrip("）)，,。、")
    if t.startswith("~"):
        return os.path.expanduser(t)
    if t.startswith("/"):
        return t
    for base in (f"{HOME}/.claude", f"{HOME}/.claude/memory", f"{HOME}/.claude/wiki",
                 f"{HOME}/.claude/hooks", f"{HOME}/.claude/commands", DIR):
        cand = os.path.join(base, t)
        if os.path.exists(cand):
            return cand
    return t


def verify_evidence(entry):
    blob = (entry.get("title") or "") + " " + (entry.get("note") or "")
    checks = []
    seen = set()
    for slug in WIKILINK_RE.findall(blob):
        key = ("wikilink", slug)
        if key in seen:
            continue
        seen.add(key)
        checks.append({"kind": "wikilink", "target": slug, "resolves": resolve_wikilink(slug)})
    for raw in PATH_RE.findall(blob):
        target = raw if isinstance(raw, str) else raw[0]
        key = ("path", target)
        if key in seen:
            continue
        seen.add(key)
        checks.append({"kind": "path", "target": target, "exists": os.path.exists(expand(target))})
    return checks[:8]


def validate_findings(findings):
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            sys.exit(f"finding {index} must be a JSON object")
        channel = finding.get("channel")
        if not isinstance(channel, str) or not channel:
            sys.exit(f"finding {index} must include a non-empty channel")
        if channel not in ALLOWED_FINDING_CHANNELS:
            sys.exit(f"finding {index} channel {channel!r} is not allowed to write the ledger")
        source_key = finding.get("source_key")
        if source_key is not None and (not isinstance(source_key, str) or not SOURCE_KEY_RE.fullmatch(source_key)):
            sys.exit(f"finding {index} has invalid source_key {source_key!r}")


def apply_findings(rows, findings, date):
    run_date = parse_calendar_date(date, "date")
    by_title = {r.get("title"): r for r in rows}
    by_source_key = {}
    for row in rows:
        source_key = row.get("source_key")
        if source_key is None:
            continue
        if not isinstance(source_key, str) or not SOURCE_KEY_RE.fullmatch(source_key):
            sys.exit(f"ledger has invalid source_key {source_key!r}")
        if source_key in by_source_key:
            sys.exit(f"ledger has duplicate source_key {source_key!r}")
        by_source_key[source_key] = row
    touched, added, unmatched = set(), [], []
    for f in findings:
        m = f.get("match")
        source_key = f.get("source_key")
        if m:
            row = by_title.get(m)
            if row is None:
                unmatched.append(f)
                continue
            if row.get("status") in TERMINAL:
                continue
            existing_source_key = row.get("source_key")
            if source_key is not None and existing_source_key not in (None, source_key):
                sys.exit(f"finding source_key {source_key!r} conflicts with ledger row {m!r}")
            if source_key is not None and existing_source_key is None:
                if source_key in by_source_key:
                    sys.exit(f"finding source_key {source_key!r} already belongs to another ledger row")
                row["source_key"] = source_key
                by_source_key[source_key] = row
            due = row.get("next_due")
            due_date = parse_calendar_date(due, f"next_due {due!r}") if due is not None else None
            muted = due_date is not None and run_date < due_date
            if row.get("last_seen") != date and not muted:
                row["count"] = int(row.get("count", 0)) + 1
            row["last_seen"] = date
            touched.add(row["title"])
        else:
            title = f.get("title")
            if not title or title in by_title:
                unmatched.append(f)
                continue
            if source_key is not None and source_key in by_source_key:
                sys.exit(f"finding source_key {source_key!r} already exists; match must name its ledger title")
            row = {"title": title, "first_seen": date, "last_seen": date,
                   "count": 1, "status": "pending", "note": f.get("note", "")}
            if source_key is not None:
                row["source_key"] = source_key
            rows.append(row)
            by_title[title] = row
            if source_key is not None:
                by_source_key[source_key] = row
            added.append(title)
            touched.add(title)
    return touched, added, unmatched


VERDICTS = ("done", "killed", "kept", "observing", "pending")


def apply_decisions(rows, decisions, date):
    by_title = {r.get("title"): r for r in rows}
    applied = []
    for d in decisions:
        m = d.get("match")
        v = d.get("verdict")
        if v not in VERDICTS:
            sys.exit(f"verdict {v!r} not in {VERDICTS} (match={m!r})")
        row = by_title.get(m)
        if row is None:
            sys.exit(f"--decide match {m!r} does not exist in the ledger; no partial write performed")
        row["status"] = v
        row["last_seen"] = date
        if d.get("note"):
            row["note"] = (row.get("note", "") + " ｜ " if row.get("note") else "") + d["note"]
        if d.get("escalate_at") is not None:
            row["escalate_at"] = int(d["escalate_at"])
        if "next_due" in d:
            parse_calendar_date(d["next_due"], f"next_due {d['next_due']!r}")
            row["next_due"] = d["next_due"]
        applied.append({"title": m, "verdict": v})
    return applied


def gate(entry, date, has_signal_today):
    status = entry.get("status")
    count = int(entry.get("count", 0))
    esc = entry.get("escalate_at")
    due = entry.get("next_due")
    run_date = parse_calendar_date(date, "date")
    due_date = parse_calendar_date(due, f"next_due {due!r}") if due is not None else None

    if status in TERMINAL:
        return {"bucket": "excluded", "reason": f"status={status}"}
    if due_date is not None and run_date < due_date:
        return {"bucket": "silent", "reason": f"next_due {due} 未到（count 不累加）"}
    if status in ("observing", "kept"):
        if esc is None:
            return {"bucket": "silent", "reason": f"status={status} 無 escalate_at → 完全靜默"}
        if count < int(esc):
            return {"bucket": "silent", "reason": f"status={status} count {count} < escalate_at {esc}"}
        return {"bucket": "forced_high", "reason": f"status={status} count {count} >= escalate_at {esc}"}
    if esc is not None:
        if count < int(esc):
            return {"bucket": "bottom_only", "reason": f"count {count} < escalate_at {esc} → 只列沉底行"}
        return {"bucket": "forced_high", "reason": f"count {count} >= escalate_at {esc}"}
    if status == "pending" and count >= 3:
        return {"bucket": "forced_high", "reason": f"pending count={count} >= 3（標「⏫ 第 {count} 次出現」）"}
    if status == "pending" and count == 2:
        return {"bucket": "min_medium", "reason": "pending count=2 → 至少中檔，不得只放沉底行"}
    return {"bucket": "open", "reason": "無強制檔位，由排檔者判斷"}


def family_hint(entry, fam):
    blob = (entry.get("title") or "") + " " + (entry.get("note") or "")
    hits = {k: fam[k] for k in fam if k in blob}
    if hits:
        return hits
    if "白話" in blob and "plain-language" in fam:
        return {"plain-language": fam["plain-language"]}
    if "證據" in blob and "evidence-level" in fam:
        return {"evidence-level": fam["evidence-level"]}
    if "自己查" in blob and "self-research-first" in fam:
        return {"self-research-first": fam["self-research-first"]}
    return {}


LATE_REPORT_CHANNELS = ("rba-verify", "evidence-level")
WARNING_MARKS = ("🚨", "⚠️")


def late_unconsumed(rows, date, report_dir):
    run_date = parse_calendar_date(date, "date")
    items = []
    for channel in LATE_REPORT_CHANNELS:
        for delta in range(1, 8):
            d = (run_date - timedelta(days=delta)).isoformat()
            path = os.path.join(report_dir, f"{d}-{channel}.md")
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    content = handle.read()
            except OSError:
                break
            if not any(m in content for m in WARNING_MARKS):
                break
            receipt = f"{channel}:{d}"
            if any(r.get("source_key") == receipt for r in rows):
                break
            items.append({
                "channel": channel,
                "report_date": d,
                "report_path": path,
                "receipt_needed": receipt,
                "action": f"digest 從未消費此報告：讀 {path}，把其 🚨/⚠️ 判讀寫成 finding（source_key={receipt}）並走 --findings --apply",
            })
            break
    return items


def build_packet(rows, date, touched, added, unmatched, fam):
    buckets = {"forced_high": [], "min_medium": [], "open": [], "bottom_only": [], "silent": []}
    for r in rows:
        if r.get("status") in TERMINAL:
            continue
        has_signal = r.get("title") in touched
        g = gate(r, date, has_signal)
        if g["bucket"] == "excluded":
            continue
        item = {
            "title": r.get("title"),
            "status": r.get("status"),
            "count": r.get("count"),
            "first_seen": r.get("first_seen"),
            "last_seen": r.get("last_seen"),
            "signal_today": has_signal,
            "gate_reason": g["reason"],
        }
        if g["bucket"] != "silent":
            fh = family_hint(r, fam)
            if fh:
                item["family_counts_current"] = fh
            if not has_signal:
                item["verify_evidence"] = verify_evidence(r)
                item["verdict_needed"] = "存在性證據已附；問題是否已解決需排檔者判斷"
        buckets[g["bucket"]].append(item)
    return {
        "date": date,
        "new_entries": added,
        "unmatched_findings": unmatched,
        "counts": {k: len(v) for k, v in buckets.items()},
        "family_counts_30d": fam,
        **buckets,
    }


def render(packet):
    L = []
    A = L.append
    A(f"# ledger 對帳 — {packet['date']}")
    A("")
    c = packet["counts"]
    A(f"強制高檔 {c['forced_high']}｜至少中檔 {c['min_medium']}｜待排檔 {c['open']}"
      f"｜只列沉底 {c['bottom_only']}｜靜默 {c['silent']}")
    if packet["new_entries"]:
        A(f"新增 entry {len(packet['new_entries'])}：" + "、".join(packet["new_entries"]))
    if packet.get("decisions_applied"):
        A(f"套用拍板 {len(packet['decisions_applied'])}："
          + "、".join(f"{d['title'][:34]}→{d['verdict']}" for d in packet["decisions_applied"]))
    if packet["unmatched_findings"]:
        A(f"⚠️ 無法併入的 finding {len(packet['unmatched_findings'])}（match 指向不存在的 title 或標題重複）")
        for f in packet["unmatched_findings"]:
            A(f"    - {f.get('title', '')[:70]}  match={f.get('match')!r}")
    if packet.get("late_unconsumed_reports"):
        A(f"🚨 漏收週報 {len(packet['late_unconsumed_reports'])}（產出晚於當日 digest、至今無消費收據）")
        for it in packet["late_unconsumed_reports"]:
            A(f"    - {it['channel']} {it['report_date']} → 讀 {it['report_path']}，finding 需帶 source_key={it['receipt_needed']}")
    for key, label in (("forced_high", "🔴 強制高檔"), ("min_medium", "🟡 至少中檔"),
                       ("open", "待排檔（你決定檔位）"), ("bottom_only", "只列沉底行")):
        items = packet[key]
        if not items:
            continue
        A("")
        A(f"## {label}（{len(items)}）")
        for it in items:
            A(f"- [{it['status']} c={it['count']}{'' if it['signal_today'] else ' 今日無訊號'}] {it['title']}")
            A(f"      閘：{it['gate_reason']}")
            if it.get("family_counts_current"):
                A(f"      家族現值（用這個、不要抄標題裡的數字）：{it['family_counts_current']}")
            if "verify_evidence" in it:
                if it["verify_evidence"]:
                    for chk in it["verify_evidence"]:
                        ok = chk.get("exists", chk.get("resolves"))
                        A(f"      查證：{chk['kind']} {chk['target']} → {'在' if ok else '不在'}")
                else:
                    A("      查證：抽不到可查物 → 排檔時必須標「未重驗」")
    if packet["silent"]:
        A("")
        A(f"## 靜默（不進三檔、不列沉底行）（{len(packet['silent'])}）")
        for it in packet["silent"]:
            A(f"- {it['title'][:64]} — {it['gate_reason']}")
    return "\n".join(L)


def reconcile(rows, findings, decisions, date, no_health, report_dir):
    touched, added, unmatched = apply_findings(rows, findings, date)
    decided = apply_decisions(rows, decisions, date)
    fam = {} if no_health else family_counts()
    packet = build_packet(rows, date, touched, added, unmatched, fam)
    packet["decisions_applied"] = decided
    packet["late_unconsumed_reports"] = late_unconsumed(rows, date, report_dir)
    return packet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--findings")
    ap.add_argument("--decide")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-health", action="store_true")
    a = ap.parse_args()

    parse_calendar_date(a.date, "--date")

    ledger = os.path.abspath(a.ledger)
    if a.findings:
        with open(a.findings) as handle:
            findings = json.load(handle)
    else:
        findings = []
    if not isinstance(findings, list):
        sys.exit("findings must be a JSON array")
    validate_findings(findings)

    if a.decide:
        with open(a.decide) as handle:
            decisions = json.load(handle)
    else:
        decisions = []
    if not isinstance(decisions, list):
        sys.exit("decide must be a JSON array")

    if a.apply:
        with open(f"{ledger}.lock", "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            rows = load_ledger(ledger)
            packet = reconcile(
                rows, findings, decisions, a.date, a.no_health, os.path.dirname(ledger)
            )
            write_ledger(ledger, rows)
        packet["applied"] = True
        packet["ledger"] = ledger
    else:
        rows = load_ledger(ledger)
        packet = reconcile(
            rows, findings, decisions, a.date, a.no_health, os.path.dirname(ledger)
        )

    print(json.dumps(packet, ensure_ascii=False, indent=2) if a.json else render(packet))
    if not a.apply:
        print("\n(dry-run：未寫回 ledger；要寫加 --apply)" if not a.json else "", file=sys.stderr)


if __name__ == "__main__":
    main()
