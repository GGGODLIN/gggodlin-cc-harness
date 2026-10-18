#!/usr/bin/env python3
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

RUBRICS = ("R1", "R2", "R3")


def decode_packet(value):
  return json.loads(base64.b64decode(value).decode("utf-8"))


def decode_json_packet(value, label):
  try:
    return json.loads(value)
  except (TypeError, json.JSONDecodeError) as error:
    raise ValueError(f"invalid {label} JSON") from error


def extract_packets_from_transcripts(transcripts_dir):
  primary = None
  verifier = None
  files = sorted(Path(transcripts_dir).glob("agent-*.jsonl"), key=lambda p: p.stat().st_mtime)
  require(files, f"no agent transcripts in {transcripts_dir}")
  for path in files:
    with path.open(encoding="utf-8") as handle:
      for raw_line in handle:
        try:
          row = json.loads(raw_line)
        except json.JSONDecodeError:
          continue
        content = row.get("message", {}).get("content") if isinstance(row, dict) else None
        if not isinstance(content, list):
          continue
        for item in content:
          if not (isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") == "StructuredOutput"):
            continue
          packet = item.get("input")
          if exact_keys(packet, {"eligible", "samples"}):
            primary = packet
          elif exact_keys(packet, {"missed_claims", "false_greens"}):
            verifier = packet
  require(primary is not None, "primary packet not found in transcripts")
  require(verifier is not None, "verifier packet not found in transcripts")
  return primary, verifier


def require(condition, message):
  if not condition:
    raise ValueError(message)


def exact_keys(value, keys):
  return isinstance(value, dict) and set(value) == set(keys)


def nonempty(value):
  return isinstance(value, str) and bool(value.strip())


def validate_packets(primary, verifier):
  require(exact_keys(primary, {"eligible", "samples"}), "invalid primary packet")
  require(isinstance(primary["eligible"], int) and primary["eligible"] >= 0, "invalid eligible")
  require(isinstance(primary["samples"], list), "invalid samples")
  require(len(primary["samples"]) == min(primary["eligible"], 3), "invalid sample count")
  sessions = set()
  samples_by_session = {}
  for sample in primary["samples"]:
    require(exact_keys(sample, {"session", "invoke", "path", "topic", "claims", "R1", "R2", "R3", "note"}), "invalid sample")
    require(all(nonempty(sample[key]) for key in ("session", "invoke", "path", "topic")), "empty sample identity")
    require(isinstance(sample["note"], str), "invalid note")
    require(all(sample[rubric] in {"PASS", "FAIL"} for rubric in RUBRICS), "invalid rubric status")
    require(isinstance(sample["claims"], list), "invalid claims")
    for claim in sample["claims"]:
      require(exact_keys(claim, {"quote", "source_pointer", "evidence"}), "invalid claim")
      require(all(nonempty(claim[key]) for key in ("quote", "source_pointer", "evidence")), "empty claim")
    require(sample["session"] not in sessions, "duplicate session")
    sessions.add(sample["session"])
    samples_by_session[sample["session"]] = sample

  require(exact_keys(verifier, {"missed_claims", "false_greens"}), "invalid verifier packet")
  require(isinstance(verifier["missed_claims"], list) and isinstance(verifier["false_greens"], list), "invalid verifier findings")
  for finding in verifier["missed_claims"]:
    require(exact_keys(finding, {"session", "rubric", "claim", "reason"}), "invalid missed claim")
    require(finding["session"] in sessions and finding["rubric"] in {"R2", "R3"}, "invalid missed claim target")
    require(nonempty(finding["claim"]) and nonempty(finding["reason"]), "empty missed claim")
  for finding in verifier["false_greens"]:
    require(exact_keys(finding, {"session", "rubric", "reason"}), "invalid false green")
    require(finding["session"] in sessions and finding["rubric"] in RUBRICS, "invalid false green target")
    require(nonempty(finding["reason"]), "empty false green")
    require(samples_by_session[finding["session"]][finding["rubric"]] == "PASS", "false green cannot upgrade FAIL")


def sample_identity(sample):
  return {
    "session": sample["session"],
    "invoke": sample["invoke"],
    "path": sample["path"],
  }


def run_sampler(sampler, projects, ledger, manifest, report_date):
  environment = os.environ.copy()
  environment.update({
    "RBA_DATE": report_date,
    "RBA_END": f"{report_date}T23:59:59.999Z",
    "RBA_LEDGER": str(ledger),
    "RBA_MANIFEST": str(manifest),
    "RBA_PROJECTS_DIR": str(projects),
  })
  completed = subprocess.run(
    [str(sampler)],
    check=True,
    capture_output=True,
    text=True,
    env=environment,
    timeout=120,
  )
  packet = json.loads(completed.stdout)
  require(exact_keys(packet, {"eligible", "samples"}), "invalid sampler packet")
  require(isinstance(packet["eligible"], int) and packet["eligible"] >= 0, "invalid sampler eligible")
  require(isinstance(packet["samples"], list), "invalid sampler samples")
  require(len(packet["samples"]) == min(packet["eligible"], 3), "invalid sampler sample count")
  for sample in packet["samples"]:
    require(exact_keys(sample, {"session", "invoke", "path"}), "invalid sampler sample")
    require(all(nonempty(sample[key]) for key in ("session", "invoke", "path")), "empty sampler identity")
  return packet


def validate_sampler_binding(primary, trusted):
  require(primary["eligible"] == trusted["eligible"], "primary eligible differs from sampler")
  require(
    [sample_identity(sample) for sample in primary["samples"]] == trusted["samples"],
    "primary samples differ from sampler",
  )


# batch_id 是識別鍵（同日同批的身分與去重），不是防竄改驗證；不要拿它回驗自己寫出的 manifest。
def digest(value):
  encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
  return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def batch_id(date, samples):
  identities = sorted(
    ({"session": sample["session"], "invoke": sample["invoke"]} for sample in samples),
    key=lambda item: (item["session"], item["invoke"]),
  )
  return digest({"date": date, "samples": identities})


def merge_verifier(samples, verifier):
  merged = json.loads(json.dumps(samples))
  by_session = {sample["session"]: sample for sample in merged}
  notes_by_session = {
    sample["session"]: [sample["note"]] if nonempty(sample["note"]) else []
    for sample in merged
  }
  findings = [
    (finding, True)
    for finding in verifier["missed_claims"]
  ] + [
    (finding, False)
    for finding in verifier["false_greens"]
  ]
  findings.sort(key=lambda item: (
    item[0]["session"],
    item[0]["rubric"],
    0 if item[1] else 1,
    item[0].get("claim", ""),
    item[0]["reason"],
  ))
  for finding, missed in findings:
    sample = by_session.get(finding["session"])
    rubric = finding["rubric"]
    if sample is None or rubric not in RUBRICS:
      continue
    if sample[rubric] == "PASS":
      sample[rubric] = "FAIL"
    reason = finding["reason"]
    note = f"verifier: {reason}"
    notes = notes_by_session[sample["session"]]
    if note not in notes:
      notes.append(note)
    sample["note"] = "; ".join(notes)
    if missed:
      claim = {
        "quote": finding["claim"],
        "source_pointer": "NONE",
        "evidence": reason,
      }
      if claim not in sample["claims"]:
        sample["claims"].append(claim)
  merged.sort(key=lambda sample: (sample["session"], sample["invoke"]))
  return merged


def preserve_existing_failures(samples, rows):
  existing = {
    (row.get("session"), row.get("invoke")): row
    for row in rows
    if isinstance(row, dict)
  }
  for sample in samples:
    row = existing.get((sample["session"], sample["invoke"]))
    if row is None:
      continue
    for rubric in RUBRICS:
      if row.get(rubric) == "FAIL":
        sample[rubric] = "FAIL"
    previous_note = row.get("note")
    current_note = sample["note"]
    if nonempty(previous_note):
      if not nonempty(current_note) or current_note in previous_note:
        sample["note"] = previous_note
      elif previous_note not in current_note:
        sample["note"] = f"{current_note}; previous: {previous_note}"
  return samples


def json_line(value):
  encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
  return encoded.replace(" ", "\\u2028").replace(" ", "\\u2029")


def canonical_row(date, packet, eligible, sample):
  return {
    "date": date,
    "eligible": eligible,
    "session": sample["session"],
    "invoke": sample["invoke"],
    "R1": sample["R1"],
    "R2": sample["R2"],
    "R3": sample["R3"],
    "note": sample["note"],
    "packet": packet,
  }


def previous_week_failed(rows, report_date):
  previous_date = (date.fromisoformat(report_date) - timedelta(days=7)).isoformat()
  return any(
    row.get("date") == previous_date and any(row.get(rubric) == "FAIL" for rubric in RUBRICS)
    for row in rows
  )


def single_line(value):
  flattened = re.sub(r"[\x00-\x1f\x7f  ]+", " ", value)
  return flattened.replace("⚠", "").replace("🚨", "").strip()


def render_report(date, eligible, samples, ledger_count, packet, escalate):
  fail_count = sum(sample[rubric] == "FAIL" for sample in samples for rubric in RUBRICS)
  lines = [
    "## 掃描範圍",
    f"日期：{date}",
    f"近 7 天候選 session 數：{eligible}",
    f"本週抽驗：{len(samples)} 個",
    f"ledger 累計抽驗數：{ledger_count}",
    f"<!-- rba-packet:{packet} -->",
    "",
    "## 抽驗結果",
  ]
  if not samples:
    lines.append("本週無 invoke。")
  for sample in samples:
    lines.extend([
      f"### {single_line(sample['session'][:8])} — {single_line(sample['topic'])}",
      "核心主張盤點：",
    ])
    for claim in sample["claims"]:
      lines.append(f"- 答案原句：{single_line(claim['quote'])}｜來源指針：{single_line(claim['source_pointer'])}｜證據：{single_line(claim['evidence'])}")
    lines.append(f"- R1: {sample['R1']}｜R2: {sample['R2']}｜R3: {sample['R3']}｜{single_line(sample['note'])}")
  lines.extend(["", "## 判讀"])
  if fail_count:
    marker = "🚨" if escalate else "⚠️"
    lines.append(f"{marker} 本週抽驗 {len(samples)} 個 session，共 {fail_count} 個 rubric FAIL。")
    if escalate:
      lines.append("建議升級 research-before-answer SKILL.md inline sampling verify（原 reminder 否決的方案重啟）。")
  else:
    lines.append(f"本週抽驗 {len(samples)}/{len(samples)} 乾淨。")
  return "\n".join(lines) + "\n"


def report_receipt(path):
  if not path.exists():
    return None
  report = path.read_text(encoding="utf-8")
  packet_match = re.search(r"<!-- rba-packet:([0-9a-f]{64}) -->", report)
  return packet_match.group(1) if packet_match else None


def read_manifest(path):
  if not path.exists():
    return None
  manifest = json.loads(path.read_text(encoding="utf-8"))
  # 舊 manifest 多帶一個 content 摘要欄；讀到時忽略、不驗。
  manifest = {key: value for key, value in manifest.items() if key != "content"}
  require(exact_keys(manifest, {"date", "eligible", "samples", "packet"}), "invalid manifest")
  validate_packets(
    {"eligible": manifest["eligible"], "samples": manifest["samples"]},
    {"missed_claims": [], "false_greens": []},
  )
  require(re.fullmatch(r"[0-9a-f]{64}", manifest["packet"]) is not None, "invalid manifest packet")
  return manifest


def replace_file(path, content):
  path.parent.mkdir(parents=True, exist_ok=True)
  fd, temp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
  try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
      handle.write(content)
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temp_path, path)
  finally:
    if os.path.exists(temp_path):
      os.unlink(temp_path)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--date", required=True)
  parser.add_argument("--primary-json")
  parser.add_argument("--verifier-json")
  parser.add_argument("--primary-b64")
  parser.add_argument("--verifier-b64")
  parser.add_argument("--packets-from-transcripts")
  parser.add_argument("--ledger", required=True)
  parser.add_argument("--report", required=True)
  parser.add_argument("--sampler", default=str(Path(__file__).resolve().with_name("rba-verify-sample.sh")))
  parser.add_argument("--projects", default=str(Path.home() / ".claude/projects"))
  options = parser.parse_args()

  json_mode = options.primary_json is not None or options.verifier_json is not None
  b64_mode = options.primary_b64 is not None or options.verifier_b64 is not None
  transcript_mode = options.packets_from_transcripts is not None
  require(sum((json_mode, b64_mode, transcript_mode)) == 1, "choose exactly one packet input mode")
  if json_mode:
    require(options.primary_json is not None and options.verifier_json is not None, "--primary-json and --verifier-json are required together")
    primary = decode_json_packet(options.primary_json, "primary")
    verifier = decode_json_packet(options.verifier_json, "verifier")
  elif b64_mode:
    require(bool(options.primary_b64) and bool(options.verifier_b64), "--primary-b64 and --verifier-b64 are required together")
    primary = decode_packet(options.primary_b64)
    verifier = decode_packet(options.verifier_b64)
  else:
    primary, verifier = extract_packets_from_transcripts(options.packets_from_transcripts)
  validate_packets(primary, verifier)
  ledger_path = Path(options.ledger).expanduser()
  report_path = Path(options.report).expanduser()
  manifest_path = report_path.with_suffix(".json")
  if not json_mode:
    trusted = run_sampler(Path(options.sampler).expanduser(), Path(options.projects).expanduser(), ledger_path, manifest_path, options.date)
    validate_sampler_binding(primary, trusted)
  candidate_samples = merge_verifier(primary["samples"], verifier)
  lock_path = Path(f"{ledger_path}.lock")
  lock_path.parent.mkdir(parents=True, exist_ok=True)

  with lock_path.open("a+", encoding="utf-8") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    historical = []
    historical_reviews = 0
    current_rows = []
    parsed_rows = []
    if ledger_path.exists():
      for raw_line in ledger_path.read_text(encoding="utf-8").split("\n"):
        if not raw_line:
          continue
        try:
          row = json.loads(raw_line)
        except json.JSONDecodeError:
          historical.append(raw_line)
          continue
        if not isinstance(row, dict):
          historical.append(raw_line)
          continue
        parsed_rows.append(row)
        if row.get("date") == options.date:
          require(nonempty(row.get("session")) and nonempty(row.get("invoke")), "invalid current-date ledger row")
          current_rows.append(row)
        else:
          historical.append(raw_line)
          if isinstance(row.get("session"), str):
            historical_reviews += 1

    candidate_packet = batch_id(options.date, candidate_samples)
    manifest = read_manifest(manifest_path)
    if manifest is not None:
      require(manifest["date"] == options.date, "manifest date mismatch")
      require(manifest["packet"] == candidate_packet, "rba finalizer refused a different batch for the same date")
      eligible = manifest["eligible"]
      samples = json.loads(json.dumps(manifest["samples"]))
    else:
      eligible = primary["eligible"]
      samples = candidate_samples

    samples = preserve_existing_failures(samples, current_rows)
    packet = batch_id(options.date, samples)
    manifest = {
      "date": options.date,
      "eligible": eligible,
      "samples": samples,
      "packet": packet,
    }
    existing_packets = {row.get("packet") for row in current_rows if row.get("packet")}
    if current_rows and not existing_packets:
      existing_packets.add(batch_id(options.date, current_rows))
    existing_report_packet = report_receipt(report_path)
    if existing_report_packet:
      existing_packets.add(existing_report_packet)
    if any(existing != packet for existing in existing_packets):
      raise SystemExit("rba finalizer refused a different batch for the same date")
    rows = [canonical_row(options.date, packet, eligible, sample) for sample in samples]
    ledger_lines = historical + [json_line(row) for row in rows]
    ledger_content = "\n".join(ledger_lines) + ("\n" if ledger_lines else "")
    escalate = previous_week_failed(parsed_rows, options.date)
    report_content = render_report(options.date, eligible, samples, historical_reviews + len(rows), packet, escalate)
    manifest_content = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    replace_file(manifest_path, manifest_content)
    replace_file(ledger_path, ledger_content)
    replace_file(report_path, report_content)

  print(json.dumps({"ok": True, "report_path": str(report_path)}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
  main()
