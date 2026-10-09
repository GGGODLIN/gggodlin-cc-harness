#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date as calendar_date
from pathlib import Path

DIR = Path(__file__).resolve().parent
DEFAULT_LEDGER = DIR.parent.parent / "reports" / "local-analysis" / "pending-actions.jsonl"
DEFAULT_ALIASES = DIR / "recurring-errors-pattern-aliases.json"
SECTION_RE = re.compile(r"^## 🔁 重複錯誤 pattern(?:（按次數降冪(?:，escalation 優先排前)?）|（按 escalation 優先，再按目前簽名次數）)?$")
HEADING_RE = re.compile(r"^### (🚨|⚠️) (.+)$")
STAT_SUFFIX_RE = re.compile(r"（(?=[^）]*(?:第|延續|本輪|sessions|最近))[^）]*）$")
SIGNATURE_RE = re.compile(r"`([^`\n]+)`")
GENERAL_SOURCE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9:._-]{2,127}$")
RECURRING_SOURCE_KEY_RE = re.compile(r"^recurring-errors:[a-z0-9-]+$")
DECIDED = frozenset({"done", "killed", "kept", "observing"})


def load_json(path):
  try:
    return json.loads(path.read_text())
  except (OSError, ValueError) as error:
    raise ValueError(f"cannot read {path}: {error}") from error


def load_ledger(path):
  rows = []
  try:
    lines = path.read_text().splitlines()
  except OSError as error:
    raise ValueError(f"cannot read {path}: {error}") from error
  for line_number, line in enumerate(lines, 1):
    if not line.strip():
      continue
    try:
      row = json.loads(line)
    except ValueError as error:
      raise ValueError(f"ledger line {line_number} is not valid JSON: {error}") from error
    if not isinstance(row, dict):
      raise ValueError(f"ledger line {line_number} must be a JSON object")
    rows.append(row)
  return rows


def parse_calendar_date(value, label):
  if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
    raise ValueError(f"{label} must use YYYY-MM-DD and be a valid calendar date")
  try:
    parsed = calendar_date.fromisoformat(value)
  except ValueError as error:
    raise ValueError(f"{label} must use YYYY-MM-DD and be a valid calendar date") from error
  if parsed.isoformat() != value:
    raise ValueError(f"{label} must use YYYY-MM-DD and be a valid calendar date")
  return parsed


def normalize_signature(value):
  normalized = unicodedata.normalize("NFKC", value).casefold().strip()
  normalized = re.sub(r"\s+", " ", normalized)
  normalized = re.sub(r"^<tool_use_error>\s*", "", normalized)
  normalized = re.sub(r"\s*</tool_use_error>$", "", normalized)
  normalized = re.sub(r"^(?:exit code |--- )+", "", normalized)
  return normalized.strip()


def parse_aliases(path):
  data = load_json(path)
  if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("patterns"), list):
    raise ValueError("aliases must use schema_version=1 with a patterns array")
  title_to_key = {}
  signature_to_key = {}
  legacy_by_key = {}
  for index, pattern in enumerate(data["patterns"]):
    if not isinstance(pattern, dict):
      raise ValueError(f"alias pattern {index} must be an object")
    source_key = pattern.get("source_key")
    report_titles = pattern.get("report_titles")
    signature_aliases = pattern.get("signature_aliases")
    legacy_titles = pattern.get("legacy_ledger_titles")
    if not isinstance(source_key, str) or not RECURRING_SOURCE_KEY_RE.fullmatch(source_key):
      raise ValueError(f"alias pattern {index} has invalid source_key")
    if not isinstance(report_titles, list) or not report_titles or not all(isinstance(value, str) and value.strip() for value in report_titles):
      raise ValueError(f"alias pattern {index} has invalid report_titles")
    if not isinstance(signature_aliases, list) or not signature_aliases:
      raise ValueError(f"alias pattern {index} has invalid signature_aliases")
    normalized_signatures = [normalize_signature(value) for value in signature_aliases if isinstance(value, str)]
    if len(normalized_signatures) != len(signature_aliases) or any(not value for value in normalized_signatures):
      raise ValueError(f"alias pattern {index} has invalid signature_aliases")
    if not isinstance(legacy_titles, list) or not all(isinstance(value, str) and value.strip() for value in legacy_titles):
      raise ValueError(f"alias pattern {index} has invalid legacy_ledger_titles")
    if source_key in legacy_by_key:
      raise ValueError(f"duplicate alias source_key {source_key}")
    legacy_by_key[source_key] = tuple(legacy_titles)
    for title in report_titles:
      normalized = title.strip()
      existing = title_to_key.get(normalized)
      if existing is not None and existing != source_key:
        raise ValueError(f"report title {normalized!r} maps to multiple source keys")
      title_to_key[normalized] = source_key
    for signature in normalized_signatures:
      existing = signature_to_key.get(signature)
      if existing is not None and existing != source_key:
        raise ValueError(f"signature alias {signature!r} maps to multiple source keys")
      signature_to_key[signature] = source_key
  return title_to_key, signature_to_key, legacy_by_key


def parse_report(path):
  try:
    lines = path.read_text().splitlines()
  except OSError as error:
    raise ValueError(f"cannot read {path}: {error}") from error
  candidates = []
  current = None
  section_count = 0
  in_patterns = False
  fence = None

  def finish_candidate():
    nonlocal current
    if current is None:
      return
    if current["signature_line_count"] != 1 or not current["signatures"]:
      raise ValueError(f"candidate at line {current['line_number']} must have exactly one representative signature line")
    current["signatures"] = list(dict.fromkeys(current["signatures"]))
    current.pop("signature_line_count")
    current.pop("line_number")
    candidates.append(current)
    current = None

  for line_number, line in enumerate(lines, 1):
    fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
    if fence is None and fence_match is not None:
      delimiter = fence_match.group(1)
      fence = (delimiter[0], len(delimiter))
      continue
    if fence is not None:
      if fence_match is not None:
        delimiter = fence_match.group(1)
        remainder = fence_match.group(2)
        if delimiter[0] == fence[0] and len(delimiter) >= fence[1] and not remainder.strip():
          fence = None
      continue
    if SECTION_RE.fullmatch(line):
      finish_candidate()
      section_count += 1
      in_patterns = True
      continue
    if line.startswith("## ") and in_patterns:
      finish_candidate()
      in_patterns = False
      continue
    if not in_patterns:
      continue
    if line.startswith("### "):
      finish_candidate()
      heading = HEADING_RE.fullmatch(line)
      if heading is None:
        continue
      icon, raw_title = heading.groups()
      title = STAT_SUFFIX_RE.sub("", raw_title).strip()
      if not title:
        raise ValueError(f"empty recurring pattern title at line {line_number}")
      current = {
        "icon": icon,
        "pattern": title,
        "source_heading": line,
        "report_order": len(candidates),
        "line_number": line_number,
        "signature_line_count": 0,
        "signatures": [],
      }
      continue
    if current is not None and line.startswith("- 代表簽名："):
      current["signature_line_count"] += 1
      current["signatures"].extend(
        normalized
        for value in SIGNATURE_RE.findall(line)
        if (normalized := normalize_signature(value))
      )
  if fence is not None:
    raise ValueError("report has an unclosed fenced code block")
  finish_candidate()
  if section_count != 1:
    raise ValueError("report must contain exactly one recurring pattern section")
  return candidates


def automatic_source_key(signatures):
  digest = hashlib.sha256(signatures[0].encode("utf-8")).hexdigest()[:16]
  return f"recurring-errors:auto-{digest}"


def index_ledger(rows):
  by_title = {}
  by_source_key = {}
  for index, row in enumerate(rows):
    title = row.get("title")
    if isinstance(title, str) and title:
      if title in by_title:
        raise ValueError(f"duplicate ledger title {title!r}")
      by_title[title] = index
    source_key = row.get("source_key")
    if source_key is None:
      continue
    if not isinstance(source_key, str) or not GENERAL_SOURCE_KEY_RE.fullmatch(source_key):
      raise ValueError(f"invalid source_key {source_key!r} in ledger")
    if source_key in by_source_key:
      raise ValueError(f"duplicate source_key {source_key}")
    by_source_key[source_key] = index
  return by_title, by_source_key


def matched_row(candidate, rows, by_title, by_source_key, legacy_by_key):
  indexes = set()
  source_key = candidate["source_key"]
  if source_key in by_source_key:
    indexes.add(by_source_key[source_key])
  generated_title = f"recurring-errors：{candidate['pattern']}"
  if generated_title in by_title:
    indexes.add(by_title[generated_title])
  for title in legacy_by_key.get(source_key, ()):
    if title in by_title:
      indexes.add(by_title[title])
  if len(indexes) > 1:
    raise ValueError(f"source_key {source_key} matches multiple ledger rows")
  if not indexes:
    return None
  return rows[indexes.pop()]


def is_available(row, run_date):
  if row is None:
    return True
  status = row.get("status")
  if status in DECIDED:
    return False
  if status != "pending":
    raise ValueError(f"unsupported ledger status {status!r} for {row.get('title')!r}")
  next_due = row.get("next_due")
  if next_due is None:
    return True
  due_date = parse_calendar_date(next_due, f"next_due for {row.get('title')!r}")
  return run_date >= due_date


def select_candidate(candidates, rows, title_to_key, signature_to_key, legacy_by_key, date_text, run_date):
  by_title, by_source_key = index_ledger(rows)
  enriched = []
  seen_keys = set()
  for candidate in candidates:
    signature_keys = {signature_to_key[value] for value in candidate["signatures"] if value in signature_to_key}
    if len(signature_keys) > 1:
      raise ValueError(f"candidate {candidate['pattern']!r} matches multiple source keys")
    signature_key = next(iter(signature_keys), None)
    title_key = title_to_key.get(candidate["pattern"])
    if signature_key is not None and title_key is not None and signature_key != title_key:
      raise ValueError(f"candidate {candidate['pattern']!r} title and signature aliases disagree")
    alias_key = signature_key or title_key
    generated_title = f"recurring-errors：{candidate['pattern']}"
    existing_row = rows[by_title[generated_title]] if generated_title in by_title else None
    existing_key = None if existing_row is None else existing_row.get("source_key")
    if existing_key is not None and alias_key is not None and existing_key != alias_key:
      raise ValueError(f"candidate {candidate['pattern']!r} alias conflicts with existing source_key")
    source_key = existing_key or alias_key or automatic_source_key(candidate["signatures"])
    if not RECURRING_SOURCE_KEY_RE.fullmatch(source_key):
      raise ValueError(f"candidate {candidate['pattern']!r} has invalid recurring source_key")
    if source_key in seen_keys:
      raise ValueError(f"duplicate source_key {source_key} in report")
    seen_keys.add(source_key)
    enriched.append({**candidate, "source_key": source_key})
  ordered = sorted(enriched, key=lambda value: (0 if value["icon"] == "🚨" else 1, value["report_order"]))
  for candidate in ordered:
    row = matched_row(candidate, rows, by_title, by_source_key, legacy_by_key)
    if not is_available(row, run_date):
      continue
    pattern = candidate["pattern"]
    source_key = candidate["source_key"]
    title = f"recurring-errors：{pattern}"
    match = None if row is None else row.get("title")
    bucket = "high" if candidate["icon"] == "🚨" else "medium"
    return {
      **candidate,
      "bucket": bucket,
      "finding": {
        "title": title,
        "match": match,
        "channel": "recurring-errors",
        "source_key": source_key,
        "note": f"{date_text} recurring-errors 第 2 次以上：{candidate['icon']} {pattern}",
      },
      "choices": {
        "handle": "修正與復發驗證完成後以 verdict=done 回寫；完成前維持 pending",
        "ignore": "以 verdict=killed 回寫",
        "defer": "以 verdict=pending 與 next_due 回寫",
      },
    }
  return None


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--date", required=True)
  parser.add_argument("--report", required=True, type=Path)
  parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
  parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
  args = parser.parse_args()
  run_date = parse_calendar_date(args.date, "--date")
  if args.report.name != f"{args.date}-recurring-errors.md":
    raise ValueError("--report filename must match --date")
  title_to_key, signature_to_key, legacy_by_key = parse_aliases(args.aliases)
  candidates = parse_report(args.report)
  rows = load_ledger(args.ledger)
  packet = {
    "date": args.date,
    "report_path": str(args.report.resolve()),
    "eligible_count": len(candidates),
    "candidate": select_candidate(
      candidates,
      rows,
      title_to_key,
      signature_to_key,
      legacy_by_key,
      args.date,
      run_date,
    ),
  }
  print(json.dumps(packet, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  try:
    main()
  except ValueError as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1) from None
