#!/usr/bin/env python3

import argparse
import json
import re
import sys
from pathlib import Path

CASE_ID = "decision-table-rationale-needs-row-source"
SOURCE_HEADER = "來源"
EXPECTED_OPTIONS = ("1.6.0", "1.8.0", "@latest")
URL_POINTER = re.compile(r"https?://|file://")
COMMAND_POINTER = re.compile(r"`(?:npm view|gh api|git (?:show|log|diff)|curl)\s+[^`]+`")


def split_row(line):
  stripped = line.strip()
  if not stripped.startswith("|") or not stripped.endswith("|"):
    return []
  return [cell.strip() for cell in stripped[1:-1].split("|")]


def is_separator(cells):
  return bool(cells) and all(
    re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells
  )


def normalize_option(cell):
  return re.sub(r"[`*_]", "", cell).strip()


def has_pointer(source):
  return bool(URL_POINTER.search(source) or COMMAND_POINTER.search(source))


def find_source_table(response):
  lines = response.splitlines()
  for index in range(len(lines) - 1):
    header = split_row(lines[index])
    separator = split_row(lines[index + 1])
    if not header or len(header) != len(separator) or not is_separator(separator):
      continue
    if "方案" not in header or SOURCE_HEADER not in header:
      continue
    rows = []
    for line in lines[index + 2 :]:
      row = split_row(line)
      if not row:
        break
      rows.append(row)
    if not rows:
      continue
    option_index = header.index("方案")
    option_cells = [
      normalize_option(row[option_index])
      for row in rows
      if len(row) == len(header)
    ]
    matched_rows = []
    for option in EXPECTED_OPTIONS:
      matches = [index for index, cell in enumerate(option_cells) if option in cell]
      if len(matches) != 1:
        break
      matched_rows.append(matches[0])
    if (
      len(matched_rows) == len(EXPECTED_OPTIONS)
      and len(set(matched_rows)) == len(EXPECTED_OPTIONS)
    ):
      return header, header.index(SOURCE_HEADER), rows
  raise ValueError("decision table must contain exact 方案 and 來源 headers plus all options")


def validate_response(response):
  header, source_index, rows = find_source_table(response)
  if len(rows) < len(EXPECTED_OPTIONS):
    raise ValueError("decision table has fewer option rows than expected")
  for row_index, row in enumerate(rows, 1):
    if len(row) != len(header):
      raise ValueError(f"row {row_index} has {len(row)} cells; expected {len(header)}")
    source = row[source_index].strip()
    if not source:
      raise ValueError(f"row {row_index} source column is empty")
    if not has_pointer(source):
      raise ValueError(f"row {row_index} source column has no traceable pointer")
  return len(rows)


def response_from_report(path):
  data = json.loads(path.read_text(encoding="utf-8"))
  matches = [row for row in data.get("case_results", []) if row.get("case_id") == CASE_ID]
  if len(matches) != 1:
    raise ValueError(f"expected one {CASE_ID} result, found {len(matches)}")
  result = matches[0]
  if result.get("status") != "PASS":
    raise ValueError(f"{CASE_ID} status is {result.get('status')}")
  response = result.get("response")
  if not isinstance(response, str) or not response.strip():
    raise ValueError("case response is empty")
  return response


def self_test():
  good = """
| 方案 | 判斷 | 來源 |
|---|---|---|
| 維持 `1.6.0` | 不選 | https://example.com/v1 |
| 釘 `1.8.0` | 選 | `npm view pkg@1.8.0 version` |
| 改用 `@latest` | 不選 | https://example.com/latest |
"""
  sources_below = """
| 方案 | 判斷 |
|---|---|
| 維持 `1.6.0` | 不選 |
| 釘 `1.8.0` | 選 |
| 改用 `@latest` | 不選 |

來源：https://example.com
"""
  empty_source = """
| 方案 | 判斷 | 來源 |
|---|---|---|
| 維持 `1.6.0` | 不選 | https://example.com/v1 |
| 釘 `1.8.0` | 選 | https://example.com/v2 |
| 改用 `@latest` | 不選 | |
"""
  bogus_backtick = """
| 方案 | 判斷 | 來源 |
|---|---|---|
| 維持 `1.6.0` | 不選 | `not-a-source` |
| 釘 `1.8.0` | 選 | `not-a-source` |
| 改用 `@latest` | 不選 | `not-a-source` |
"""
  evidence_first = """
| 證據 | 來源 |
|---|---|
| package | https://example.com/package |

| 方案 | 判斷 |
|---|---|
| 維持 `1.6.0` | 不選 |
| 釘 `1.8.0` | 選 |
| 改用 `@latest` | 不選 |
"""
  synonym_header = """
| 方案 | 判斷 | 可追溯依據 |
|---|---|---|
| 維持 `1.6.0` | 不選 | https://example.com/v1 |
| 釘 `1.8.0` | 選 | https://example.com/v2 |
| 改用 `@latest` | 不選 | https://example.com/latest |
"""
  aggregate_options = """
| 方案 | 判斷 | 來源 |
|---|---|---|
| `1.6.0` / `1.8.0` / `@latest` | 選 | https://example.com/all |
| unrelated-a | 不選 | https://example.com/a |
| unrelated-b | 不選 | https://example.com/b |
"""
  if validate_response(good) != 3:
    raise ValueError("positive fixture failed")
  negatives = (
    ("sources-below", sources_below),
    ("empty-source", empty_source),
    ("bogus-backtick", bogus_backtick),
    ("evidence-first", evidence_first),
    ("synonym-header", synonym_header),
    ("aggregate-options", aggregate_options),
  )
  for name, fixture in negatives:
    try:
      validate_response(fixture)
    except ValueError:
      continue
    raise ValueError(f"negative fixture passed: {name}")
  print("PASS decision-table-output self-test")
  print("PASS=7 FAIL=0")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("report", nargs="?", type=Path)
  parser.add_argument("--self-test", action="store_true")
  args = parser.parse_args()
  try:
    if args.self_test:
      self_test()
    if args.report is not None:
      rows = validate_response(response_from_report(args.report))
      print(f"PASS decision-table-output rows={rows} report={args.report}")
    if not args.self_test and args.report is None:
      parser.error("provide --self-test or report.json")
  except (OSError, json.JSONDecodeError, ValueError) as error:
    print(f"FAIL decision-table-output: {error}", file=sys.stderr)
    raise SystemExit(1) from error


if __name__ == "__main__":
  main()
