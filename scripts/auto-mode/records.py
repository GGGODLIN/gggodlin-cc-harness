#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

RECORDS_DIR = Path.home() / ".claude" / "logs" / "auto-mode" / "records"
TEXT_FIELDS = ("task", "stop", "recommendation", "adopted", "reason")
RECORD_FIELDS = {*TEXT_FIELDS, "id", "disposition", "undo", "reply", "changed_value"}
DISPOSITIONS = ("followed", "downweighted")
REVIEWS = ("kept", "changed")


class RecordsUnreadable(Exception):
  pass


def load_mode():
  # An explicit sibling import works even when the caller uses python3 -I.
  spec = importlib.util.spec_from_file_location("auto_mode_switch", Path(__file__).with_name("mode.py"))
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def has_text(value):
  if not isinstance(value, str) or not value.strip():
    return False
  try:
    value.encode("utf-8")
  except UnicodeEncodeError:
    return False
  return True


def valid_reply(reply, changed_value):
  if reply == "changed":
    return has_text(changed_value)
  return reply in ("unreviewed", "kept") and changed_value is None


def valid_record(row, expected_id):
  return (
    isinstance(row, dict) and set(row) == RECORD_FIELDS and row["id"] == expected_id
    and all(has_text(row[field]) for field in TEXT_FIELDS)
    and row["reason"].splitlines() == [row["reason"]]
    and row["disposition"] in DISPOSITIONS
    and (row["undo"] is None or has_text(row["undo"]))
    and valid_reply(row["reply"], row["changed_value"])
  )


def read_records(mode, pi, dirfd, filename):
  try:
    rows = mode.read_json(pi, dirfd, filename)
  except FileNotFoundError:
    return []
  except (mode.CorruptState, pi.Blocked, OSError) as error:
    raise RecordsUnreadable from error
  if not isinstance(rows, list) or any(
    not valid_record(row, f"D{index}") for index, row in enumerate(rows, start=1)
  ):
    raise RecordsUnreadable
  return rows


def rate(numerator, denominator):
  return {
    "numerator": numerator,
    "denominator": denominator,
    "display": f"{numerator / denominator:.2%}" if denominator else "尚無可算樣本",
  }


def statistics(rows):
  followed = [row["reply"] for row in rows if row["disposition"] == "followed"]
  kept = followed.count("kept")
  changed = followed.count("changed")
  reviewed = kept + changed
  return {
    "followed": len(followed), "unreviewed": followed.count("unreviewed"), "kept": kept, "changed": changed,
    "kept_rate": rate(kept, reviewed),
    "reviewed_coverage": rate(reviewed, len(followed)),
    "downweighted_reopened": sum(row["disposition"] == "downweighted" and row["reply"] == "changed"
                                 for row in rows),
  }


def mutate(mode, pi, dirfd, key, filename, args):
  with mode.lock_state(pi, dirfd, key):
    rows = read_records(mode, pi, dirfd, filename)
    if args.command == "append":
      decision_id = f"D{len(rows) + 1}"
      row = {
        **{field: getattr(args, field) for field in TEXT_FIELDS},
        "id": decision_id, "disposition": args.disposition, "undo": args.undo,
        "reply": "unreviewed", "changed_value": None,
      }
      if not valid_record(row, decision_id):
        raise ValueError("必填欄位不可留白，理由限一行")
      rows.append(row)
    else:
      for index, existing in enumerate(rows):
        if existing["id"] == args.id:
          row = {**existing, "reply": args.reply, "changed_value": args.changed_value}
          if not valid_record(row, existing["id"]):
            raise ValueError("無效的複核狀態")
          rows[index] = row
          break
      else:
        raise ValueError("找不到決策 ID")
    mode.write_json(dirfd, filename, rows)
    return row


def run(mode, pi, key, args):
  writing = args.command in ("append", "review")
  dirfd = mode.open_root(pi, args.command == "append", root=RECORDS_DIR)
  if dirfd is None and writing:
    raise ValueError("找不到決策 ID")
  filename = f"{key}.json"
  try:
    if writing:
      return mutate(mode, pi, dirfd, key, filename, args)
    rows = []
    if dirfd is not None:
      try:
        os.stat(filename, dir_fd=dirfd, follow_symlinks=False)
      except FileNotFoundError:
        pass
      except OSError as error:
        raise RecordsUnreadable from error
      else:
        # Replacement can unlink an open snapshot before its link count is checked.
        try:
          with mode.lock_state(pi, dirfd, key, shared=True):
            rows = read_records(mode, pi, dirfd, filename)
        except (pi.Blocked, OSError) as error:
          raise RecordsUnreadable from error
    if args.command == "stats":
      return statistics(rows)
    matching = (row for row in rows if row["task"] == args.task)
    return sorted(matching, key=lambda row: row["disposition"] != "downweighted") or None
  finally:
    if dirfd is not None:
      os.close(dirfd)


def parse_args():
  parser = argparse.ArgumentParser(description="Write and review auto mode decision records.")
  commands = parser.add_subparsers(dest="command", required=True)
  scope = argparse.ArgumentParser(add_help=False)
  scope.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID"),
                     help="session ID when HC_TERMINAL_ID is absent")
  append = commands.add_parser("append", parents=[scope], allow_abbrev=False)
  for field in TEXT_FIELDS:
    append.add_argument(f"--{field}", required=True)
  append.add_argument("--disposition", choices=DISPOSITIONS, required=True)
  append.add_argument("--undo")
  review = commands.add_parser("review", parents=[scope], allow_abbrev=False)
  review.add_argument("--id", required=True)
  review.add_argument("--reply", choices=REVIEWS, required=True)
  review.add_argument("--changed-value", help="required for changed, including when reopening a downweighted decision")
  closeout = commands.add_parser("closeout", parents=[scope], allow_abbrev=False)
  closeout.add_argument("--task", required=True)
  commands.add_parser("stats", parents=[scope], allow_abbrev=False)
  args = parser.parse_args()
  if args.command == "review" and not valid_reply(args.reply, args.changed_value):
    review.error("--changed-value must be nonblank for changed and omitted for kept")
  return args


def main():
  args = parse_args()
  sys.dont_write_bytecode = True
  mode = load_mode()
  try:
    pi = mode.load_pi_mode()
  except mode.PiModeUnavailable:
    print("讀不到自決紀錄：共用身分驗證器不存在", file=sys.stderr)
    return 1
  try:
    payload = run(mode, pi, mode.state_key(pi, args.session), args)
  except RecordsUnreadable:
    print("讀不到自決紀錄：檔案損毀或無法存取", file=sys.stderr)
    return 1
  except (pi.Blocked, pi.UsageError, OSError, ValueError) as error:
    prefix = "寫入自決紀錄失敗" if args.command in ("append", "review") else "讀不到自決紀錄"
    print(f"{prefix}：{getattr(error, 'reason', error)}", file=sys.stderr)
    return 1
  if payload is not None:
    print(json.dumps(payload, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
