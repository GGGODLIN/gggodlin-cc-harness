#!/usr/bin/env python3

import argparse
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

LENSES = {"simplify", "failure", "repo", "compat"}
MODELS = {"opus", "fable"}
LENS_ORDER = ("simplify", "failure", "repo", "compat")
MODEL_ORDER = ("opus", "fable")
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PERMIT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def parse_time(value):
  parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
  if parsed.utcoffset() is None:
    raise ValueError("timezone required")
  return parsed


def now_utc():
  override = os.environ.get("REVIEW_SPEC_DUAL_NOW")
  return parse_time(override) if override else datetime.now(timezone.utc)


def canonical_lenses(lenses):
  selected = set(lenses)
  return [lens for lens in LENS_ORDER if lens in selected]


def seat_key(lens, model):
  return f"{lens}:{model}"


def parse_seat(value):
  parts = value.split(":")
  if len(parts) != 2 or parts[0] not in LENSES or parts[1] not in MODELS:
    return None
  return seat_key(parts[0], parts[1])


def canonical_seats(seats):
  selected = set(seats)
  return [seat_key(lens, model) for lens in LENS_ORDER for model in MODEL_ORDER if seat_key(lens, model) in selected]


def seats_for_lenses(lenses):
  return [seat_key(lens, model) for lens in canonical_lenses(lenses) for model in MODEL_ORDER]


def lenses_for_seats(seats):
  return canonical_lenses(seat.split(":", 1)[0] for seat in seats)


def build_packet(permit_id, expires_at, lens, artifact):
  return (
    f"REVIEW_SPEC_PERMIT_ID={permit_id}\n"
    f"REVIEW_SPEC_EXPIRES_AT={expires_at}\n"
    f"REVIEW_SPEC_LENS={lens}\n"
    f"REVIEW_SPEC_ARTIFACT_BEGIN={permit_id}\n"
    f"{artifact}\n"
    f"REVIEW_SPEC_ARTIFACT_END={permit_id}"
  )


def canonical_reference_packet(value):
  return value.replace("\r\n", "\n").replace("\r", "\n")


def packet_path(root, state, lens):
  return root / f"{state['session_id']}.{state['permit_id']}.{lens}.packet"


def build_packet_reference(state, lens, path):
  return (
    f"REVIEW_SPEC_PACKET_PATH={path}\n"
    f"REVIEW_SPEC_PERMIT_ID={state['permit_id']}\n"
    f"REVIEW_SPEC_EXPIRES_AT={state['expires_at']}\n"
    f"REVIEW_SPEC_LENS={lens}"
  )


def complete_read_matches(content, expected_bytes):
  if not isinstance(content, str):
    return False
  lines = content.splitlines()
  values = []
  for index, line in enumerate(lines, 1):
    prefix = f"{index}\t"
    if not line.startswith(prefix):
      return False
    values.append(line[len(prefix) :])
  return "\n".join(values).encode("utf-8") == expected_bytes


def read_trusted_file(path):
  try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  except OSError:
    return None
  try:
    metadata = os.fstat(descriptor)
    mode = stat.S_IMODE(metadata.st_mode)
    if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode) or mode & 0o022:
      return None
    with os.fdopen(descriptor, "rb") as handle:
      descriptor = -1
      return handle.read(), stat.S_IMODE(metadata.st_mode)
  finally:
    if descriptor >= 0:
      os.close(descriptor)


def trusted_file(path):
  return read_trusted_file(path) is not None


def trusted_directory(path):
  try:
    metadata = path.lstat()
  except OSError:
    return False
  mode = stat.S_IMODE(metadata.st_mode)
  return (
    metadata.st_uid == os.getuid()
    and stat.S_ISDIR(metadata.st_mode)
    and not stat.S_ISLNK(metadata.st_mode)
    and not mode & 0o022
  )


def resolve_main_transcript(session):
  if not SESSION_RE.fullmatch(session):
    return None
  projects = Path.home() / ".claude" / "projects"
  candidates = list(projects.glob(f"*/{session}.jsonl"))
  candidates = [
    path
    for path in candidates
    if trusted_directory(projects) and trusted_directory(path.parent) and trusted_file(path)
  ]
  return candidates[0] if len(candidates) == 1 else None


def runtime_dir():
  return Path(
    os.environ.get(
      "REVIEW_SPEC_DUAL_RUNTIME_DIR",
      f"/private/tmp/claude-review-spec-dual-{os.getuid()}",
    )
  )


def load_permit_state(root, args, main_transcript, snapshot):
  errors = []
  if not trusted_directory(root):
    return None, ["permit-runtime"]
  trusted = read_trusted_file(root / f"{args.session}.json")
  if trusted is None or trusted[1] & 0o077:
    return None, ["permit-state"]
  try:
    state = json.loads(trusted[0])
  except (UnicodeDecodeError, json.JSONDecodeError):
    return None, ["permit-state"]
  if not isinstance(state, dict):
    return None, ["permit-state"]
  vendor = state.get("vendor", "")
  expected_opus = state.get("expected_opus_model", "")
  expected_fable = state.get("expected_fable_model", "")
  if any(not isinstance(value, str) for value in (vendor, expected_opus, expected_fable)):
    return None, ["permit-state"]
  if vendor:
    if not expected_opus or not expected_fable or expected_opus == expected_fable:
      return None, ["permit-state"]
  elif expected_opus or expected_fable:
    return None, ["permit-state"]
  authorized = state.get("authorized_lenses")
  remaining = state.get("remaining_lenses")
  authorized_seats = state.get("authorized_seats")
  selection_event_uuid = state.get("selection_event_uuid", "")
  if not isinstance(selection_event_uuid, str):
    errors.append("permit-state")
  expected_values = {
    "version": 1,
    "session_id": args.session,
    "transcript_path": str(main_transcript) if main_transcript is not None else None,
    "permit_id": args.permit_id,
    "snapshot_path": str(snapshot),
    "expires_at": args.expires_at,
    "finalized": True,
  }
  if any(state.get(key) != value for key, value in expected_values.items()):
    errors.append("permit-state")
  if not isinstance(authorized, list) or authorized != canonical_lenses(authorized) or not authorized:
    errors.append("lens-set")
  if not isinstance(remaining, list) or remaining != canonical_lenses(remaining):
    errors.append("permit-state")
  elif remaining:
    errors.append("lenses-unconsumed")

  if authorized_seats is None:
    authorized_seats = seats_for_lenses(authorized) if isinstance(authorized, list) else None
    state["authorized_seats"] = authorized_seats
  if not isinstance(authorized_seats, list) or authorized_seats != canonical_seats(authorized_seats) or not authorized_seats:
    errors.append("seat-set")
  elif isinstance(authorized, list) and lenses_for_seats(authorized_seats) != authorized:
    errors.append("seat-set")
  if isinstance(remaining, list) and isinstance(authorized_seats, list) and any(
    seat_key(lens, "fable") not in authorized_seats for lens in remaining
  ):
    errors.append("permit-state")
  return state, errors


def build_pair_results(results):
  by_seat = {seat_key(result["lens"], result["model"]): result for result in results}
  pairs = []
  for lens in canonical_lenses(result["lens"] for result in results):
    opus = by_seat.get(seat_key(lens, "opus"))
    fable = by_seat.get(seat_key(lens, "fable"))
    if opus is None or fable is None:
      continue
    pairs.append(
      {
        "lens": lens,
        "opus_agent_id": opus["agent_id"],
        "fable_agent_id": fable["agent_id"],
        "opus_model": opus["resolved_model"],
        "fable_model": fable["resolved_model"],
      }
    )
  return pairs


def write_receipt(root, state, current, results):
  path = root / f"{state['session_id']}.{state['permit_id']}.receipt"
  authorized_seats = state.get("authorized_seats", seats_for_lenses(state["authorized_lenses"]))
  seat_order = {seat: index for index, seat in enumerate(authorized_seats)}
  ordered_results = sorted(
    results,
    key=lambda result: seat_order.get(seat_key(result["lens"], result["model"]), len(seat_order)),
  )
  payload = json.dumps(
    {
      "version": 1,
      "session_id": state["session_id"],
      "permit_id": state["permit_id"],
      "lenses": state["authorized_lenses"],
      "seats": [
        f"{result['lens']}:{result['model']}:{result['agent_id']}"
        for result in ordered_results
      ],
      "pairs": [
        f"{result['lens']}:{result['opus_agent_id']}:{result['fable_agent_id']}"
        for result in build_pair_results(results)
      ],
      "verified_at": current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    },
    ensure_ascii=False,
    separators=(",", ":"),
  )
  try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  except OSError:
    return None
  try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
      descriptor = -1
      handle.write(payload + "\n")
      handle.flush()
      os.fsync(handle.fileno())
  finally:
    if descriptor >= 0:
      os.close(descriptor)
  return path


def parse_pair(value):
  parts = value.split(":")
  if len(parts) != 3:
    return None
  lens, opus_id, fable_id = parts
  if lens not in LENSES or not AGENT_ID_RE.fullmatch(opus_id) or not AGENT_ID_RE.fullmatch(fable_id):
    return None
  return lens, opus_id, fable_id


def parse_assignment(value):
  parts = value.split(":")
  if len(parts) != 3:
    return None
  lens, model, agent_id = parts
  if parse_seat(f"{lens}:{model}") is None or not AGENT_ID_RE.fullmatch(agent_id):
    return None
  return lens, model, agent_id


def load_records(data):
  records = []
  for line in data.split(b"\n"):
    if not line.strip():
      continue
    try:
      record = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
      return None
    if not isinstance(record, dict):
      return None
    records.append(record)
  return records


def inspect_agent(path, agent_id, expected_packet, expected_reference, expected_packet_path, packet_file_valid, expected_read_bytes, require_reference=False):
  directories = (path.parent, path.parent.parent, path.parent.parent.parent)
  if any(not trusted_directory(directory) for directory in directories):
    return None, None, [f"agent-file:{agent_id}"]
  trusted = read_trusted_file(path)
  if trusted is None:
    return None, None, [f"agent-file:{agent_id}"]
  records = load_records(trusted[0])
  if records is None:
    return None, None, [f"agent-jsonl:{agent_id}"]
  errors = []
  prompt = None
  models = set()
  completed = False
  final_report = False
  packet_read_id = None
  packet_result_valid = False
  tool_action_seen = False
  for record in records:
    message = record.get("message")
    if not isinstance(message, dict):
      continue
    if record.get("agentId") != agent_id:
      errors.append(f"agent-id:{agent_id}")
      continue
    role = message.get("role")
    content = message.get("content")
    if completed and role in {"user", "assistant"}:
      errors.append(f"turn-boundary:{agent_id}")
      continue
    if role == "user" and isinstance(content, str):
      if prompt is None:
        prompt = content
      else:
        errors.append(f"turn-boundary:{agent_id}")
      continue
    if role == "user" and isinstance(content, list) and packet_read_id is not None:
      for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_result" or item.get("tool_use_id") != packet_read_id or item.get("is_error") is True:
          continue
        packet_result_valid = complete_read_matches(item.get("content"), expected_read_bytes)
      continue
    if role != "assistant" or prompt is None:
      continue
    if isinstance(content, list):
      tool_items = [item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]
      if tool_items and not tool_action_seen:
        tool_action_seen = True
        if len(tool_items) == 1 and tool_items[0].get("name") == "Read":
          item = tool_items[0]
          tool_input = item.get("input")
          if isinstance(tool_input, dict):
            raw_path = tool_input.get("file_path")
            offset = tool_input.get("offset")
            if isinstance(raw_path, str) and Path(os.path.abspath(os.path.expanduser(raw_path))) == expected_packet_path and offset in (None, 0) and "limit" not in tool_input:
              packet_read_id = item.get("id")
    model = message.get("model")
    if isinstance(model, str) and model:
      models.add(model)
    if message.get("stop_reason") != "end_turn":
      continue
    completed = True
    if record.get("attributionAgent") != "architecture-critic":
      errors.append(f"final-attribution:{agent_id}")
    if isinstance(content, list):
      final_report = any(
        isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
        and bool(item["text"].strip())
        for item in content
      )
  embedded_mode = isinstance(prompt, str) and prompt.startswith(expected_packet)
  reference_mode = isinstance(prompt, str) and prompt.startswith(expected_reference)
  if not embedded_mode and not reference_mode:
    errors.append(f"prompt-packet:{agent_id}")
  if require_reference and not reference_mode:
    errors.append(f"packet-read-required:{agent_id}")
  if reference_mode and not packet_file_valid:
    errors.append(f"packet-file:{agent_id}")
  if reference_mode and packet_read_id is None:
    errors.append(f"packet-read:{agent_id}")
  elif reference_mode and not packet_result_valid:
    errors.append(f"packet-result:{agent_id}")
  if len(models) != 1:
    errors.append(f"model-count:{agent_id}")
  if not completed:
    errors.append(f"end-turn:{agent_id}")
  elif not final_report:
    errors.append(f"report-empty:{agent_id}")
  model = next(iter(models)) if len(models) == 1 else None
  return model, prompt, errors


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--session", required=True)
  parser.add_argument("--permit-id", required=True)
  parser.add_argument("--expires-at", required=True)
  parser.add_argument("--snapshot", required=True)
  parser.add_argument("--pair", action="append")
  parser.add_argument("--seat", action="append")
  parser.add_argument("--check-only", action="store_true")
  args = parser.parse_args()

  errors = []
  results = []
  artifact = None
  state = None
  current = now_utc()
  if not PERMIT_ID_RE.fullmatch(args.permit_id):
    errors.append("permit-id-format")
  try:
    expires_at = parse_time(args.expires_at)
  except (AttributeError, TypeError, ValueError):
    errors.append("expires-at-format")
  else:
    if expires_at <= current:
      errors.append("permit-expired")
  main_transcript = resolve_main_transcript(args.session)
  if main_transcript is None:
    errors.append("main-transcript")
  snapshot = Path(os.path.abspath(os.path.expanduser(args.snapshot)))
  trusted_snapshot = read_trusted_file(snapshot) if trusted_directory(snapshot.parent) else None
  if trusted_snapshot is None:
    errors.append("snapshot-file")
  elif trusted_snapshot[1] & 0o277:
    errors.append("snapshot-permissions")
  else:
    try:
      artifact = trusted_snapshot[0].decode("utf-8")
    except UnicodeDecodeError:
      errors.append("snapshot-utf8")

  state, state_errors = load_permit_state(runtime_dir(), args, main_transcript, snapshot)
  errors.extend(state_errors)

  assignments = []
  pair_groups = []
  if not args.pair and not args.seat:
    errors.append("seat-required")
  for value in args.pair or []:
    pair = parse_pair(value)
    if pair is None:
      errors.append(f"pair-format:{value}")
      continue
    lens, opus_id, fable_id = pair
    pair_groups.append((lens, opus_id, fable_id))
    assignments.extend(((lens, "opus", opus_id), (lens, "fable", fable_id)))
  for value in args.seat or []:
    assignment = parse_assignment(value)
    if assignment is None:
      errors.append(f"seat-format:{value}")
    else:
      assignments.append(assignment)

  selected_seats = [seat_key(lens, model) for lens, model, _ in assignments]
  pair_lenses = [lens for lens, _, _ in pair_groups]
  if len(pair_lenses) != len(set(pair_lenses)):
    errors.append("duplicate-lens")
  if len(selected_seats) != len(set(selected_seats)):
    errors.append("duplicate-seat")
  agent_ids = [agent_id for _, _, agent_id in assignments]
  if len(agent_ids) != len(set(agent_ids)):
    errors.append("duplicate-agent")
  authorized_lenses = state.get("authorized_lenses") if isinstance(state, dict) else None
  if isinstance(authorized_lenses, list) and canonical_lenses(lens for lens, _, _ in assignments) != authorized_lenses:
    errors.append("lens-set-mismatch")
  authorized_seats = state.get("authorized_seats") if isinstance(state, dict) else None
  if isinstance(authorized_seats, list):
    if canonical_seats(selected_seats) != authorized_seats:
      errors.append("seat-set-mismatch")

  configuration_invalid = bool(errors)
  prompts_by_lens = {}
  if main_transcript is not None:
    subagent_dir = main_transcript.parent / args.session / "subagents"
    for lens, model, agent_id in assignments:
      expected_packet = build_packet(args.permit_id, args.expires_at, lens, artifact or "")
      expected_bytes = canonical_reference_packet(expected_packet).encode("utf-8")
      if isinstance(state, dict) and not state_errors:
        path = packet_path(runtime_dir(), state, lens)
        trusted_packet = read_trusted_file(path)
        packet_file_valid = trusted_packet is not None and not trusted_packet[1] & 0o077 and trusted_packet[0] == expected_bytes
        expected_reference = build_packet_reference(state, lens, path)
      else:
        path = runtime_dir() / ".invalid.packet"
        packet_file_valid = False
        expected_reference = "REVIEW_SPEC_INVALID_PACKET_REFERENCE"
      errors_before_seat = len(errors)
      resolved_model, prompt, agent_errors = inspect_agent(
        subagent_dir / f"agent-{agent_id}.jsonl",
        agent_id,
        expected_packet,
        expected_reference,
        path,
        packet_file_valid,
        expected_bytes,
        bool(state.get("selection_event_uuid")) if isinstance(state, dict) else False,
      )
      errors.extend(agent_errors)
      if model == "opus":
        expected_model = state.get("expected_opus_model") if isinstance(state, dict) and state.get("vendor") else None
        if expected_model:
          if resolved_model != expected_model:
            errors.append(f"opus-model:{lens}:{resolved_model or 'missing'}")
        elif not isinstance(resolved_model, str) or not resolved_model.startswith("claude-opus-"):
          errors.append(f"opus-model:{lens}:{resolved_model or 'missing'}")
      else:
        expected_model = state.get("expected_fable_model") if isinstance(state, dict) and state.get("vendor") else None
        if expected_model:
          if resolved_model != expected_model:
            errors.append(f"fable-model:{lens}:{resolved_model or 'missing'}")
        elif not isinstance(resolved_model, str) or not resolved_model.startswith("claude-fable-"):
          errors.append(f"fable-model:{lens}:{resolved_model or 'missing'}")
      results.append(
        {
          "lens": lens,
          "model": model,
          "agent_id": agent_id,
          "resolved_model": resolved_model,
          "status": "valid" if not configuration_invalid and len(errors) == errors_before_seat else "invalid",
        }
      )
      if model == "opus" and isinstance(prompt, str):
        prompts_by_lens.setdefault(lens, {})["opus"] = prompt
      if model == "fable" and isinstance(prompt, str):
        prompts_by_lens.setdefault(lens, {})["fable"] = prompt

  selected_pair_lenses = [
    lens
    for lens in lenses_for_seats(authorized_seats or [])
    if seat_key(lens, "opus") in (authorized_seats or []) and seat_key(lens, "fable") in (authorized_seats or [])
  ]
  for lens in selected_pair_lenses:
    prompts = prompts_by_lens.get(lens, {})
    if isinstance(prompts.get("opus"), str) and isinstance(prompts.get("fable"), str) and prompts["opus"] != prompts["fable"]:
      errors.append(f"pair-prompt-mismatch:{lens}")

  receipt_path = None
  if not errors and state is not None and not args.check_only:
    receipt_path = write_receipt(runtime_dir(), state, current, results)
    if receipt_path is None:
      errors.append("receipt-write")
  payload = {
    "valid": not errors,
    "seats": results,
    "pairs": build_pair_results(results),
    "errors": errors,
    "receipt_path": str(receipt_path) if receipt_path is not None else None,
  }
  print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
  raise SystemExit(0 if not errors else 3)


if __name__ == "__main__":
  main()
