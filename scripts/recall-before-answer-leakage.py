#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

TRIGGER_PATTERN = r"我記得|之前有|上次|翻一下|查一下|重撈|好像有|應該有|處理過|做過|眼熟|研究紀錄|自創|先確認|看一下|不是有|之前(的|那個)"
TRIGGER_RE = re.compile(TRIGGER_PATTERN)
DEFAULT_LEDGER = Path(os.path.expanduser("~/code/social-info/reports/local-analysis/rule-adherence-ledger.jsonl"))
# ~/.claude/rule-review/ledger-mapping.json 為原作者 2026-08-25 歷史盤點產生的舊規則文字對照表（公開版不匯出）；
# 檔案不存在時 load_mapping() 會自動退回空對照表，直接由帳本列的 rule_id 欄位或 rule 字串內的 C077 標記判讀。
DEFAULT_MAPPING = Path(os.path.expanduser("~/.claude/rule-review/ledger-mapping.json"))
DIRECT_ID_KEYS = ("rule_id", "rule_ids", "matched_rule_id", "matched_rule_ids", "ruleId", "ruleIds")
QUOTE_KEYS = ("quote", "original_quote", "original_sentence", "sentence", "text")


def parse_date(value):
  if not isinstance(value, str):
    return None
  try:
    return date.fromisoformat(value[:10])
  except ValueError:
    return None


def as_ids(value):
  if isinstance(value, str):
    return [value]
  if isinstance(value, list):
    return [item for item in value if isinstance(item, str)]
  return []


def load_mapping(path):
  try:
    document = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, UnicodeDecodeError, json.JSONDecodeError):
    return {}
  if isinstance(document, dict) and isinstance(document.get("mappings"), list):
    result = {}
    for row in document["mappings"]:
      if not isinstance(row, dict) or not isinstance(row.get("rule"), str):
        continue
      if row.get("confidence") == "low":
        result[row["rule"]] = []
      else:
        result[row["rule"]] = as_ids(row.get("ids"))
    return result
  if isinstance(document, dict):
    return {key: as_ids(value) for key, value in document.items() if isinstance(key, str)}
  return {}


def row_ids(row, mapping):
  ids = []
  for key in DIRECT_ID_KEYS:
    ids.extend(as_ids(row.get(key)))
  rule = row.get("rule")
  if isinstance(rule, str):
    ids.extend(mapping.get(rule, []))
    if re.search(r"(?:^|[^A-Za-z0-9])C077(?:$|[^A-Za-z0-9])", rule):
      ids.append("C077")
  return set(ids)


def row_quote(row):
  for key in QUOTE_KEYS:
    value = row.get(key)
    if isinstance(value, str):
      return value
  return ""


def read_rows(path):
  rows = []
  invalid = 0
  try:
    handle = path.open(encoding="utf-8")
  except OSError as error:
    raise RuntimeError(f"無法讀取帳本：{path}（{error}）") from error
  with handle:
    for line in handle:
      if not line.strip():
        continue
      try:
        row = json.loads(line)
      except json.JSONDecodeError:
        invalid += 1
        continue
      if isinstance(row, dict):
        rows.append(row)
      else:
        invalid += 1
  return rows, invalid


def week_bounds(day):
  start = day - timedelta(days=day.weekday())
  return start, start + timedelta(days=6)


def measure(rows, mapping, since, until):
  selected_rows = []
  invalid_dates = 0
  for row in rows:
    if row.get("kind") != "rule_violation":
      continue
    if "C077" not in row_ids(row, mapping):
      continue
    when = parse_date(row.get("date"))
    if when is None:
      invalid_dates += 1
      continue
    if since <= when <= until:
      quote = row_quote(row)
      selected_rows.append((when, quote, bool(TRIGGER_RE.search(quote))))

  def stats(items):
    denominator = len(items)
    numerator = sum(1 for _, _, matched in items if not matched)
    return {
      "numerator": numerator,
      "denominator": denominator,
      "rate": (numerator / denominator) if denominator else None,
    }

  total = stats(selected_rows)
  first_week, _ = week_bounds(since)
  last_week, _ = week_bounds(until)
  weeks = []
  current = first_week
  while current <= last_week:
    end = current + timedelta(days=6)
    weekly = stats([item for item in selected_rows if current <= item[0] <= end])
    weeks.append({"week_start": current.isoformat(), "week_end": end.isoformat(), **weekly})
    current += timedelta(days=7)
  return total, weeks, invalid_dates


def selected_week(weeks, requested):
  if requested is not None:
    start, end = week_bounds(requested)
    for row in weeks:
      if row["week_start"] == start.isoformat():
        return {**row, "in_window": True}
    return {
      "week_start": start.isoformat(),
      "week_end": end.isoformat(),
      "numerator": 0,
      "denominator": 0,
      "rate": None,
      "in_window": False,
    }
  populated = [row for row in weeks if row["denominator"] > 0]
  if populated:
    return {**populated[-1], "in_window": True}
  if weeks:
    return {**weeks[-1], "in_window": True}
  return None


def build_parser():
  parser = argparse.ArgumentParser()
  parser.add_argument("ledger", nargs="?", default=os.environ.get("RECALL_BEFORE_ANSWER_LEDGER", str(DEFAULT_LEDGER)))
  parser.add_argument("--mapping", default=os.environ.get("RECALL_BEFORE_ANSWER_MAPPING", str(DEFAULT_MAPPING)))
  parser.add_argument("--since")
  parser.add_argument("--until")
  parser.add_argument("--week")
  parser.add_argument("--days", type=int, default=30)
  return parser


def main(argv=None):
  args = build_parser().parse_args(argv)
  if args.days < 1:
    raise SystemExit("--days 必須大於 0")
  until = parse_date(args.until) if args.until else date.today()
  if until is None:
    raise SystemExit("--until 必須是 YYYY-MM-DD")
  since = parse_date(args.since) if args.since else until - timedelta(days=args.days - 1)
  if since is None:
    raise SystemExit("--since 必須是 YYYY-MM-DD")
  if since > until:
    raise SystemExit("--since 不得晚於 --until")
  requested_week = parse_date(args.week) if args.week else None
  if args.week and requested_week is None:
    raise SystemExit("--week 必須是 YYYY-MM-DD")

  ledger_path = Path(os.path.expanduser(args.ledger))
  mapping_path = Path(os.path.expanduser(args.mapping))
  if not mapping_path.is_file():
    local_mapping = Path(__file__).resolve().parent.parent / "rule-review" / "ledger-mapping.json"
    if local_mapping.is_file():
      mapping_path = local_mapping
  rows, invalid_rows = read_rows(ledger_path)
  total, weeks, invalid_dates = measure(rows, load_mapping(mapping_path), since, until)
  report = {
    "rule_id": "C077",
    "trigger_pattern": TRIGGER_PATTERN,
    "window": {"since": since.isoformat(), "until": until.isoformat(), "days": (until - since).days + 1},
    "ledger": str(ledger_path),
    "mapping": str(mapping_path),
    "total": total,
    "selected_week": selected_week(weeks, requested_week),
    "weeks": weeks,
    "quality": {"invalid_json_rows": invalid_rows, "invalid_dates": invalid_dates},
  }
  print(json.dumps(report, ensure_ascii=False, sort_keys=True))
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except RuntimeError as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(2)
