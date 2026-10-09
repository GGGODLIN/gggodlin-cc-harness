#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

CASE_ID = "low-confidence-mark-must-survive"
REQUIRED_TERMS = ("Claude", "Cursor", "Copilot", "ChatGPT", "Codex", "Gemini")
LOW_CONFIDENCE_MARKERS = ("未經官方確認", "低信心")


def validate_response(response):
  missing = [term for term in REQUIRED_TERMS if term not in response]
  if missing:
    raise ValueError(f"missing required categories: {', '.join(missing)}")
  price_lines = [line for line in response.splitlines() if "19.99" in line]
  if not price_lines:
    raise ValueError("Gemini third-party price 19.99 is missing")
  marked = [
    line
    for line in price_lines
    if any(marker in line for marker in LOW_CONFIDENCE_MARKERS)
    and "9to5Google" in line
    and "https://9to5google.com/" in line
  ]
  if not marked:
    raise ValueError("Gemini 19.99 lacks same-line low-confidence marker and source URL")
  return len(REQUIRED_TERMS)


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
Claude 17 https://claude.com
Cursor 20 https://cursor.com
Copilot 10 https://github.com
ChatGPT Codex 20 https://chatgpt.com
Gemini ⚠️ 19.99 未經官方確認（來源：9to5Google） https://9to5google.com/article
"""
  missing_gemini = """
Claude Cursor Copilot ChatGPT Codex
"""
  missing_price = """
Claude Cursor Copilot ChatGPT Codex Gemini 官方未提供價格
"""
  unmarked_price = """
Claude Cursor Copilot ChatGPT Codex
Gemini 19.99 https://9to5google.com/article
"""
  footnote_marker = """
Claude Cursor Copilot ChatGPT Codex
Gemini 19.99 https://9to5google.com/article
低信心，來源：9to5Google
"""
  if validate_response(good) != len(REQUIRED_TERMS):
    raise ValueError("positive fixture failed")
  negatives = (
    ("missing-gemini", missing_gemini),
    ("missing-price", missing_price),
    ("unmarked-price", unmarked_price),
    ("footnote-marker", footnote_marker),
  )
  for name, fixture in negatives:
    try:
      validate_response(fixture)
    except ValueError:
      continue
    raise ValueError(f"negative fixture passed: {name}")
  print("PASS low-confidence-output self-test")
  print("PASS=5 FAIL=0")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("report", nargs="?", type=Path)
  parser.add_argument("--self-test", action="store_true")
  args = parser.parse_args()
  try:
    if args.self_test:
      self_test()
    if args.report is not None:
      terms = validate_response(response_from_report(args.report))
      print(f"PASS low-confidence-output terms={terms} report={args.report}")
    if not args.self_test and args.report is None:
      parser.error("provide --self-test or report.json")
  except (OSError, json.JSONDecodeError, ValueError) as error:
    print(f"FAIL low-confidence-output: {error}", file=sys.stderr)
    raise SystemExit(1) from error


if __name__ == "__main__":
  main()
