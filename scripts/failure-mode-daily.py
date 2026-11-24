#!/usr/bin/env python3
"""failure-mode-daily：local-analysis 每日 shell channel 的邏輯。

讀探針表「累犯決策紀錄」與「案例登記」區，輸出近 30 天登記筆數（兩種標記分開）、全窗累犯升級候選、
暫定門檻命中清單與無法解析的行；無未審個案、無新達標累犯候選且無壞行時輸出 __SILENT__。同時維護探針表檔首的一行 top-2 提醒。

並發安全（硬性驗收）：檔首行內容（不含日期）沒變就不寫；寫回前重讀整檔並核對 inode，跟讀取時不同就用新內容
重算再寫，最多 3 次，仍衝突就放棄本日改寫並在輸出標明；只改檔首那一行，決策區與登記區行數只增不減。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

DEFAULT_TAXONOMY = Path.home() / ".claude/references/failure-mode-taxonomy.md"
WINDOW_DAYS = 30
ESCALATION_THRESHOLD = 5
ESCALATION_TOP_K = 3
TAGS = ("Failure-miss", "Acceptance-miss")
CLASSES = tuple(f"F{i}" for i in range(1, 8))
DECISION_STATUSES = ("open", "deferred", "closed")
HEADER_PREFIX = "> 近 30 天最常漏："
DECISION_HEADING = "## 累犯決策紀錄"
REGISTRY_HEADING = "## 案例登記"
PROBE_ID_RE = re.compile(r"^F[1-6]\.[1-9]\d*$")
PROBE_KV_RE = re.compile(r"(?:^|\s)probe=(\S*)")
MODE_KV_RE = re.compile(r"(?:^|\s)mode=(\S*)")
PR_REF_RE = re.compile(r"^(?:PR\s*#|#|(?:(?:github|bitbucket):)?(?:github\.com|bitbucket\.org)/[^/\s]+/[^#\s]+#)(\d+)\b", re.I)
LOCAL_SHA_RE = re.compile(r"^(local:[^\s@＋]+@[0-9a-fA-F]{6,40})(?:[\s＋].*)?$")
INLINE_CODE_RE = re.compile(r"`[^`]*`")


@dataclass
class Row:
  day: date
  tag: str
  fn: str
  repo: str
  ref: str
  symptom: str
  found_at: str
  raw: str
  reviewed: bool = False
  probe: str | None = None


@dataclass
class DecisionRow:
  day: date
  target: str
  status: str


@dataclass
class EscalationCandidate:
  probe: str
  unit_count: int
  latest_day: date
  units: list[tuple[str, str]]
  total_window_units: int


@dataclass
class Parsed:
  rows: list[Row] = field(default_factory=list)
  decisions: list[DecisionRow] = field(default_factory=list)
  bad: list[str] = field(default_factory=list)


FORMAT_LINE_PREFIXES = ("每行七欄：", "每行五欄：")
HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
ROW_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \| ")


def _is_candidate(line: str) -> bool:
  # 登記區與決策區裡除了格式說明行，任何含反引號外 | 的行都當候選；不符合格式的進「無法解析」，不能靜默消失
  s = line.strip()
  if not s or s.startswith(FORMAT_LINE_PREFIXES) or HEADING_RE.match(s):
    return False
  unquoted = INLINE_CODE_RE.sub("", s) if s.startswith("- ") else s
  return "|" in unquoted


def _balanced_brackets(text: str) -> bool:
  depth = 0
  for ch in text:
    if ch == "[":
      depth += 1
    elif ch == "]":
      depth -= 1
      if depth < 0:
        return False
  return depth == 0


def _extract_reviewed_suffix(stripped: str) -> tuple[bool, bool, str, str]:
  idx = stripped.find("[reviewed")
  if idx == -1:
    return True, False, stripped, ""
  tail = stripped[idx:]
  if not tail.startswith("[reviewed ") or not tail.endswith("]") or "[reviewed" in tail[10:]:
    return False, False, stripped, ""
  inner = tail[10:-1]
  if not _balanced_brackets(inner):
    return False, False, stripped, ""
  return True, True, stripped[:idx].rstrip(), inner


def _single_valid_tag(matches: list[str], valid_fn) -> tuple[bool, str | None]:
  if len(matches) > 1:
    return False, None
  if not matches:
    return True, None
  val = matches[0]
  return (True, val) if valid_fn(val) else (False, None)


def _parse_suffix_metadata(suffix_body: str) -> tuple[bool, str | None]:
  ok_p, probe = _single_valid_tag(
    PROBE_KV_RE.findall(suffix_body),
    lambda v: v == "none" or PROBE_ID_RE.match(v) is not None,
  )
  ok_m, _ = _single_valid_tag(
    MODE_KV_RE.findall(suffix_body),
    lambda v: v in ("auto-verified", "auto-accepted"),
  )
  return (ok_p and ok_m), probe


def normalize_work_unit(repo: str, ref: str) -> tuple[str, str]:
  """對已證實同一張票、同一個 PR 或同一顆本地提交的重複紀錄去重；不同子票號維持獨立。"""
  clean_repo = repo.strip()
  clean_ref = ref.strip()
  pr_m = PR_REF_RE.match(clean_ref)
  if pr_m:
    return clean_repo, f"pr#{pr_m.group(1)}"
  local_m = LOCAL_SHA_RE.match(clean_ref)
  if local_m:
    return clean_repo, local_m.group(1)
  return clean_repo, clean_ref


def _parse_iso_day(raw_day: str, today: date | None) -> date | None:
  try:
    day = date.fromisoformat(raw_day)
  except ValueError:
    return None
  if today is not None and day > today:
    return None
  return day


def _section_lines(lines: list[str], heading: str) -> list[str]:
  start = next((i for i, l in enumerate(lines) if l.startswith(heading)), None)
  if start is None:
    return []
  end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
  return lines[start + 1:end]


def _parse_one_decision(stripped: str, today: date | None) -> DecisionRow | None:
  parts = [p.strip() for p in stripped.split(" | ")]
  if not ROW_RE.match(stripped) or len(parts) != 5:
    return None
  day = _parse_iso_day(parts[0], today)
  target, status, ref_field, reason = parts[1], parts[2], parts[3], parts[4]
  if day is None or not PROBE_ID_RE.match(target) or status not in DECISION_STATUSES:
    return None
  if not ref_field.startswith("ref=") or not reason:
    return None
  ref_val = ref_field[4:].strip()
  if not ref_val or (status == "open" and ref_val == "N-A"):
    return None
  return DecisionRow(day, target, status)


def _parse_decisions_section(lines: list[str], today: date | None, out: Parsed) -> None:
  for line in lines:
    if not _is_candidate(line):
      continue
    stripped = line.strip()
    dec = _parse_one_decision(stripped, today)
    if dec is None:
      out.bad.append(stripped)
    else:
      out.decisions.append(dec)


def parse(text: str, today: date | None = None) -> Parsed:
  out = Parsed()
  lines = text.splitlines()
  _parse_decisions_section(_section_lines(lines, DECISION_HEADING), today, out)
  reg_lines = _section_lines(lines, REGISTRY_HEADING)
  if not reg_lines:
    return out
  for line in reg_lines:
    if not _is_candidate(line):
      continue
    stripped = line.strip()
    raw_parts = stripped.split(" | ", 6)
    if not ROW_RE.match(stripped) or len(raw_parts) != 7:
      out.bad.append(stripped)
      continue
    suf_ok, reviewed, found_at, suffix_body = _extract_reviewed_suffix(raw_parts[6])
    if not suf_ok or " | " in found_at or found_at.endswith(" |"):
      out.bad.append(stripped)
      continue
    probe: str | None = None
    if reviewed:
      meta_ok, probe = _parse_suffix_metadata(suffix_body)
      if not meta_ok:
        out.bad.append(stripped)
        continue
    parts = [p.strip() for p in raw_parts[:6]] + [found_at.strip()]
    if parts[1] not in TAGS or any(not p for p in parts[3:]):
      out.bad.append(stripped)
      continue
    day = _parse_iso_day(parts[0], today)
    if day is None:
      out.bad.append(stripped)
      continue
    fn = parts[2]
    if parts[1] == "Acceptance-miss" and fn == "—":
      fn = "-"
    if fn not in CLASSES and not (fn == "-" and parts[1] == "Acceptance-miss"):
      out.bad.append(stripped)
      continue
    out.rows.append(Row(day, parts[1], fn, parts[3], parts[4], parts[5], parts[6], stripped, reviewed, probe))
  return out


def in_window(rows: list[Row], today: date) -> list[Row]:
  # 剛好 30 天前的行算在窗內
  floor = today - timedelta(days=WINDOW_DAYS)
  return [r for r in rows if floor <= r.day <= today]


def top2_text(rows: list[Row]) -> str:
  # 只算 Failure-miss：Acceptance-miss 是執行紀律問題，不該帶偏探針方向
  counts = Counter(r.fn for r in rows if r.tag == "Failure-miss")
  if not counts:
    return "（尚無登記）"
  ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
  return "、".join(f"{fn}（{n}）" for fn, n in ranked)


def header_line(rows: list[Row], today: date) -> str:
  return f"{HEADER_PREFIX}{top2_text(rows)}｜更新 {today.isoformat()}"


def _strip_date(line: str) -> str:
  return line.split("｜更新 ")[0]


def apply_header(text: str, new_header: str) -> str | None:
  """回傳改好的全文；內容（不含日期）沒變就回 None。"""
  lines = text.splitlines(keepends=True)
  eol = "\r\n" if "\r\n" in text else "\n"
  for i, l in enumerate(lines):
    if l.startswith(HEADER_PREFIX):
      if _strip_date(l.rstrip("\r\n")) == _strip_date(new_header):
        return None
      line_eol = "\r\n" if l.endswith("\r\n") else ("\n" if l.endswith("\n") else eol)
      lines[i] = new_header + line_eol
      return "".join(lines)
  try:
    rule = next(i for i, l in enumerate(lines) if l.rstrip("\r\n") == "---")
  except StopIteration:
    rule = len(lines)
  if rule == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
    lines[-1] += eol
  lines.insert(rule, new_header + eol + eol)
  return "".join(lines)


def thresholds(rows: list[Row]) -> list[str]:
  # 已 reviewed 的行不再觸發門檻：門檻是「有東西等人處理」的提醒，處理過的行重列只是噪音
  rows = [r for r in rows if not r.reviewed]
  hits: list[str] = []
  fm = [r for r in rows if r.tag == "Failure-miss"]
  by_fn = Counter(r.fn for r in fm)
  for fn in CLASSES[:-1]:  # F7 沒有問句可改，不套「同類第 2 筆」
    if by_fn.get(fn, 0) >= 2:
      hits.append(f"{fn} 同類第 2 筆（累計 {by_fn[fn]}）")
  unclassified = sum(1 for r in fm if r.fn == "F7")
  if unclassified >= 3:
    hits.append(f"F7／未分類累積 {unclassified} 筆")
  for r in rows:
    if r.tag == "Acceptance-miss":
      hits.append(f"Acceptance-miss：{r.symptom}（{r.repo}／{r.ref}）")
  return hits


def _group_probe_units(rows: list[Row]) -> dict[str, dict[tuple[str, str], tuple[date, date]]]:
  by_probe: dict[str, dict[tuple[str, str], tuple[date, date]]] = {}
  for r in rows:
    if not r.probe or r.probe == "none":
      continue
    unit = normalize_work_unit(r.repo, r.ref)
    cur = by_probe.setdefault(r.probe, {}).get(unit)
    by_probe[r.probe][unit] = (r.day, r.day) if cur is None else (min(cur[0], r.day), max(cur[1], r.day))
  return by_probe


def _effective_probe_units(
  unit_days: dict[tuple[str, str], tuple[date, date]], dec: DecisionRow | None
) -> list[tuple[tuple[str, str], date]]:
  if dec is None:
    return [(u, hi) for u, (_, hi) in unit_days.items()]
  if dec.status == "open":
    return []
  return [(u, hi) for u, (lo, hi) in unit_days.items() if lo > dec.day]


def escalation_candidates(parsed: Parsed, today: date) -> tuple[list[EscalationCandidate], dict[str, int]]:
  """對近 30 天全部成立案例（含自動與人工歸檔）計算同細項累犯去重工作單數，並依決策列篩出最多前 3 名升級候選。"""
  latest_decision = {d.target: d for d in parsed.decisions if d.day <= today}
  by_probe = _group_probe_units(in_window(parsed.rows, today))
  total_units_by_probe = {p: len(units) for p, units in by_probe.items()}
  candidates: list[EscalationCandidate] = []
  for probe, unit_days in by_probe.items():
    eff_items = _effective_probe_units(unit_days, latest_decision.get(probe))
    if len(eff_items) >= ESCALATION_THRESHOLD:
      latest_occ = max(hi for _, hi in eff_items)
      ordered_units = sorted(u for u, _ in eff_items)
      candidates.append(EscalationCandidate(probe, len(eff_items), latest_occ, ordered_units, len(unit_days)))
  candidates.sort(key=lambda c: (-c.unit_count, -c.latest_day.toordinal(), c.probe))
  return candidates[:ESCALATION_TOP_K], total_units_by_probe


def untagged_observation_totals(rows: list[Row]) -> tuple[int, int]:
  """回傳近 30 天（無細項 Acceptance-miss 獨立工作單數、F7 獨立工作單數），僅供總量觀測不進細項升級。"""
  untagged_am = {normalize_work_unit(r.repo, r.ref) for r in rows if r.tag == "Acceptance-miss" and r.probe in (None, "none")}
  f7_units = {normalize_work_unit(r.repo, r.ref) for r in rows if r.fn == "F7"}
  return len(untagged_am), len(f7_units)


def report(parsed: Parsed, today: date, header_note: str, force_report: bool = False) -> str:
  rows = in_window(parsed.rows, today)
  unreviewed = [r for r in rows if not r.reviewed]
  escalations, probe_totals = escalation_candidates(parsed, today)
  if not unreviewed and not escalations and not parsed.bad and not force_report:
    return "__SILENT__\n"
  floor = today - timedelta(days=WINDOW_DAYS)
  untagged_am_units, f7_units = untagged_observation_totals(rows)
  lines = [f"# failure-mode-daily {today.isoformat()}", "",
           f"## 近 30 天登記筆數（{floor.isoformat()} 到 {today.isoformat()}）", "",
           f"Failure-miss {sum(1 for r in rows if r.tag == 'Failure-miss')}、"
           f"Acceptance-miss {sum(1 for r in rows if r.tag == 'Acceptance-miss')}", "",
           "| 類 | Failure-miss | Acceptance-miss |", "|---|---|---|"]
  fns = [fn for fn in (*CLASSES, "-") if any(r.fn == fn for r in rows)]
  for fn in fns:
    fm = sum(1 for r in rows if r.fn == fn and r.tag == "Failure-miss")
    am = sum(1 for r in rows if r.fn == fn and r.tag == "Acceptance-miss")
    lines.append(f"| {fn} | {fm} | {am} |")
  if probe_totals or untagged_am_units or f7_units:
    lines += ["", "## 全窗累犯觀測（含已歸檔案例；同單去重）", ""]
    for probe, cnt in sorted(probe_totals.items(), key=lambda kv: (-kv[1], kv[0])):
      lines.append(f"- {probe}：{cnt} 張獨立工作單")
    lines.append(f"- 總量觀測（不入圍細項升級）：無細項 Acceptance-miss {untagged_am_units} 單、F7 {f7_units} 單")
  lines += ["", "## 累犯升級候選（近 30 天跨 ≥5 張獨立工作單，每輪最多前 3 名）", ""]
  if escalations:
    for c in escalations:
      sample = "、".join(f"{repo}:{u}" for repo, u in c.units[:5])
      lines.append(f"- {c.probe}：{c.unit_count} 張獨立工作單（全窗 {c.total_window_units} 單，最近 {c.latest_day.isoformat()}；樣本：{sample}）")
  else:
    lines.append("（無）")
  lines += ["", "## 門檻命中（三個門檻值暫定；只列不判斷）", ""]
  hits = thresholds(rows)
  lines += [f"- {h}" for h in hits] or ["（無）"]
  if parsed.bad:
    lines += ["", "## 無法解析（欄數、日期或 Fn 不對；未計入任何類）", ""]
    lines += [f"- {b}" for b in parsed.bad]
  lines += ["", "## 檔首行", "", header_note, ""]
  return "\n".join(lines)


def _atomic_write(path: Path, content: str, old_fd: int, old_len: int) -> bytes | None:
  """寫回新內容；若替換前發現 path 的 inode 已變（如外部 Edit 原子替換），刪暫存檔回 None 交外層重算。

  空窗說明：`>>` 在 replace 之後才 open 的 appender 會寫進新檔，不受影響；在 replace 之前 open 舊 inode 的
  appender，其寫入會落在舊 inode，這裡從舊 fd 讀出 old_len 之後的 bytes 補寫過去。補寫之後才寫入舊 inode 的
  極小空窗仍會丟，這是 replace 式寫法的已知邊界。
  """
  old_st = os.fstat(old_fd)
  fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fmd-")
  try:
    with os.fdopen(fd, "w", newline="") as f:
      fd = -1
      f.write(content)
    os.chmod(tmp, old_st.st_mode & 0o7777)
    if path.stat().st_ino != old_st.st_ino:
      return None
    os.replace(tmp, path)
    tmp = ""
  finally:
    if fd != -1:
      try:
        os.close(fd)
      except OSError:
        pass
    if tmp:
      try:
        os.unlink(tmp)
      except OSError:
        pass
  os.lseek(old_fd, old_len, os.SEEK_SET)
  tail = b""
  while True:
    chunk = os.read(old_fd, 1 << 16)
    if not chunk:
      break
    tail += chunk
  if tail:
    with path.open("ab") as f:
      f.write(tail)
  return tail


def run(taxonomy: Path, today: date, after_read=None, before_write=None, allow_write: bool = True) -> tuple[str, bool]:
  """回 (report_text, wrote_header)。after_read／before_write 是測試用鉤子。allow_write=False 只算不寫（回填舊日期用）。"""
  if not taxonomy.exists():
    return f"探針表不存在：{taxonomy}\n", False
  target = taxonomy.resolve()
  parse_max_day = today if allow_write else max(today, date.today())
  note = ""
  for attempt in range(1, 4):
    text = target.read_text(newline="")
    if after_read:
      after_read(text)
    parsed = parse(text, parse_max_day)
    new_text = apply_header(text, header_line(in_window(parsed.rows, today), today))
    if new_text is None:
      return report(parsed, today, "檔首行內容未變，未寫入"), False
    if not allow_write:
      return report(parsed, today, "--date 早於今天，只算不改檔首"), False
    old_fd = os.open(target, os.O_RDONLY)
    try:
      current_bytes = os.read(old_fd, os.fstat(old_fd).st_size)
      if current_bytes.decode() != text:
        note = f"第 {attempt} 次寫回前發現檔案已變，重讀後重算"
        continue
      if before_write:
        before_write(text)
      tail = _atomic_write(target, new_text, old_fd, len(current_bytes))
      if tail is None:
        note = f"第 {attempt} 次替換前發現 inode 已變，重讀後重算"
        continue
    finally:
      os.close(old_fd)
    parts = [note] if note else []
    parts.append(f"已更新檔首行（第 {attempt} 次）")
    if tail:
      parts.append(f"寫回期間補回 {tail.count(b"\n")} 行並發 append")
    return report(parsed, today, "；".join(parts)), True
  parsed = parse(target.read_text(newline=""), parse_max_day)
  return report(parsed, today, "連續 3 次寫回前檔案都被改動，放棄本日檔首改寫", force_report=True), False


def main(argv: list[str]) -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
  ap.add_argument("--date", type=date.fromisoformat, default=date.today())
  ap.add_argument("--out", type=Path)
  a = ap.parse_args(argv)
  text, _ = run(a.taxonomy, a.date, allow_write=a.date >= date.today())
  if a.out:
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text)
  else:
    sys.stdout.write(text)
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
