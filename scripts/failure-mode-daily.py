#!/usr/bin/env python3
"""failure-mode-daily：local-analysis 每日 shell channel 的邏輯。

讀探針表「案例登記」區，輸出近 30 天登記筆數（兩種標記分開）、暫定門檻命中清單、無法解析的行；
無新登記時輸出 __SILENT__。同時維護探針表檔首的一行 top-2 提醒。

並發安全（硬性驗收）：檔首行內容（不含日期）沒變就不寫；寫回前重讀整檔，跟讀取時不同就用新內容
重算再寫，最多 3 次，仍衝突就放棄本日改寫並在輸出標明；只改檔首那一行，登記區行數只增不減。
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
TAGS = ("Failure-miss", "Acceptance-miss")
CLASSES = tuple(f"F{i}" for i in range(1, 8))
HEADER_PREFIX = "> 近 30 天最常漏："
REGISTRY_HEADING = "## 案例登記"
REVIEWED_SUFFIX = re.compile(r"\s*\[reviewed [^\]]*\]\s*$")


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


@dataclass
class Parsed:
  rows: list[Row] = field(default_factory=list)
  bad: list[str] = field(default_factory=list)


FORMAT_LINE_PREFIX = "每行七欄："
ROW_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \| ")


def _is_candidate(line: str) -> bool:
  # 登記區裡除了格式說明行，任何含 | 的行都當候選；不符合七欄的進「無法解析」，不能靜默消失
  s = line.strip()
  if not s or s.startswith(FORMAT_LINE_PREFIX) or s.startswith("#"):
    return False
  return "|" in s


def parse(text: str, today: date | None = None) -> Parsed:
  out = Parsed()
  lines = text.splitlines()
  try:
    start = next(i for i, l in enumerate(lines) if l.startswith(REGISTRY_HEADING))
  except StopIteration:
    return out
  for line in lines[start + 1:]:
    if not _is_candidate(line):
      continue
    stripped = line.strip()
    reviewed = REVIEWED_SUFFIX.search(stripped) is not None
    body = REVIEWED_SUFFIX.sub("", stripped)
    parts = [p.strip() for p in body.split(" | ")]
    if not ROW_RE.match(body) or len(parts) != 7 or parts[1] not in TAGS:
      out.bad.append(line.strip())
      continue
    try:
      day = date.fromisoformat(parts[0])
    except ValueError:
      out.bad.append(line.strip())
      continue
    if today is not None and day > today:
      out.bad.append(line.strip())
      continue
    fn = parts[2]
    if parts[1] == "Acceptance-miss" and fn == "—":
      fn = "-"
    if fn not in CLASSES and not (fn == "-" and parts[1] == "Acceptance-miss"):
      out.bad.append(line.strip())
      continue
    out.rows.append(Row(day, parts[1], fn, parts[3], parts[4], parts[5], parts[6], stripped, reviewed))
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
  for i, l in enumerate(lines):
    if l.startswith(HEADER_PREFIX):
      if _strip_date(l.rstrip("\n")) == _strip_date(new_header):
        return None
      lines[i] = new_header + "\n"
      return "".join(lines)
  try:
    rule = next(i for i, l in enumerate(lines) if l.rstrip("\n") == "---")
  except StopIteration:
    rule = len(lines)
  lines.insert(rule, new_header + "\n\n")
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


def report(parsed: Parsed, today: date, header_note: str, force_report: bool = False) -> str:
  rows = in_window(parsed.rows, today)
  unreviewed = [r for r in rows if not r.reviewed]
  if not unreviewed and not parsed.bad and not force_report:
    return "__SILENT__\n"
  floor = today - timedelta(days=WINDOW_DAYS)
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
  lines += ["", "## 門檻命中（三個門檻值暫定；只列不判斷）", ""]
  hits = thresholds(rows)
  lines += [f"- {h}" for h in hits] or ["（無）"]
  if parsed.bad:
    lines += ["", "## 無法解析（欄數、日期或 Fn 不對；未計入任何類）", ""]
    lines += [f"- {b}" for b in parsed.bad]
  lines += ["", "## 檔首行", "", header_note, ""]
  return "\n".join(lines)


def _atomic_write(path: Path, content: str, old_fd: int, old_len: int) -> bytes:
  """寫回新內容；回傳「重讀之後、替換之前」有人 append 到舊 inode 的尾巴 bytes（已補寫到新檔）。

  空窗說明：`>>` 在 replace 之後才 open 的 appender 會寫進新檔，不受影響；在 replace 之前 open 舊 inode 的
  appender，其寫入會落在舊 inode，這裡從舊 fd 讀出 old_len 之後的 bytes 補寫過去。補寫之後才寫入舊 inode 的
  極小空窗仍會丟，這是 replace 式寫法的已知邊界。
  """
  fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fmd-")
  with os.fdopen(fd, "w") as f:
    f.write(content)
  os.chmod(tmp, path.stat().st_mode & 0o7777)
  os.replace(tmp, path)
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
  note = ""
  for attempt in range(1, 4):
    text = taxonomy.read_text()
    if after_read:
      after_read(text)
    parsed = parse(text, today)
    new_text = apply_header(text, header_line(in_window(parsed.rows, today), today))
    if new_text is None:
      return report(parsed, today, "檔首行內容未變，未寫入"), False
    if not allow_write:
      return report(parsed, today, "--date 早於今天，只算不改檔首"), False
    old_fd = os.open(taxonomy, os.O_RDONLY)
    try:
      current_bytes = os.read(old_fd, os.fstat(old_fd).st_size)
      if current_bytes.decode() != text:
        note = f"第 {attempt} 次寫回前發現檔案已變，重讀後重算"
        continue
      if before_write:
        before_write(text)
      tail = _atomic_write(taxonomy, new_text, old_fd, len(current_bytes))
    finally:
      os.close(old_fd)
    parts = [note] if note else []
    parts.append(f"已更新檔首行（第 {attempt} 次）")
    if tail:
      parts.append(f"寫回期間補回 {tail.count(b"\n")} 行並發 append")
    return report(parsed, today, "；".join(parts)), True
  parsed = parse(taxonomy.read_text(), today)
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
