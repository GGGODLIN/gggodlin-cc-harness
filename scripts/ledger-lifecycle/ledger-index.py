#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from path_safety import ensure_no_symlink

UNKNOWN = "UNKNOWN"
DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
ARCHIVED_ENTRY_RE = re.compile(r"^### .*\([^)]*\d{4}-\d{2}-\d{2}[^)]*\)$")
NEW_ARCHIVED_ENTRY_RE = re.compile(r"^### .*\[結案\s+\d{4}-\d{2}-\d{2}\s+·\s+[^]]+\].*$")
PROOFREAD_ENTRY_RE = re.compile(r"^### (PR-\d+)\s+(.+)$")
FACTCHECK_ENTRY_RE = re.compile(r"^### (?:(FC-\d+)(?:\s+|$))?(.*)$")
NEW_ARCHIVED_RE = re.compile(r"^### .*\[結案\s+(\d{4}-\d{2}-\d{2})\s+·\s+([^]]+)\]")
LABEL_RE = re.compile(r"^\s*[-*]\s*\*\*([^*]+)\*\*\s*[:：]\s*(.*)$")
VERDICT_RE = re.compile(r"(?<![A-Za-z])(?:KEEP|KILL|DEFER|PASS|MERGE|DECOMMISSIONED)(?![A-Za-z])")
INDEX_PENDING = "<!-- [index-pending] -->"
INDEX_FORMATS = {
    "archived": "slug｜verdict｜結案日｜一句理由｜標題原文",
    "proofread": "編號｜文章 slug｜類型｜一句｜標題原文",
    "factcheck": "編號｜主題 slug｜判定｜一句｜標題原文",
}


def clean_value(value):
    value = re.sub(r"\*\*|`", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("｜", "/")
    return value or UNKNOWN


def first_sentence(value):
    value = clean_value(value)
    for marker in ("。", "！", "!", "？", "?"):
        position = value.find(marker)
        if position >= 0:
            return value[: position + 1]
    return value


def slugify(value):
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    chunks = []
    current = []
    for character in normalized:
        if character.isalnum():
            current.append(character)
        elif current:
            chunks.append("".join(current))
            current = []
    if current:
        chunks.append("".join(current))
    return "-".join(chunks) or UNKNOWN


def read_lines(path):
    safe_path = ensure_no_symlink(path, "read-path")
    return safe_path.read_text(encoding="utf-8").splitlines()


def entry_match(kind, line):
    if kind == "archived":
        return bool(ARCHIVED_ENTRY_RE.fullmatch(line) or NEW_ARCHIVED_ENTRY_RE.fullmatch(line))
    if kind == "proofread":
        return bool(PROOFREAD_ENTRY_RE.fullmatch(line))
    if kind == "factcheck":
        return bool(FACTCHECK_ENTRY_RE.fullmatch(line))
    raise ValueError(f"unsupported kind: {kind}")


def entry_ranges(lines, kind):
    starts = [index for index, line in enumerate(lines) if entry_match(kind, line)]
    return [(start, starts[position + 1] if position + 1 < len(starts) else len(lines)) for position, start in enumerate(starts)]


def labeled_values(body):
    values = {}
    for line in body:
        match = LABEL_RE.match(line)
        if match and match.group(1) not in values:
            values[match.group(1)] = clean_value(match.group(2))
    return values


def archived_title(anchor):
    match = NEW_ARCHIVED_RE.match(anchor)
    if match:
        value = anchor[match.end():].strip()
    else:
        value = anchor[4:].strip()
    return re.sub(r"\s*(?:\([^)]*\)|（[^）]*）)$", "", value).strip() or UNKNOWN


def archived_date(anchor):
    new_match = NEW_ARCHIVED_RE.match(anchor)
    if new_match:
        return new_match.group(1)
    dates = DATE_RE.findall(anchor)
    return dates[-1] if dates else UNKNOWN


def archived_conclusion(anchor):
    match = NEW_ARCHIVED_RE.match(anchor)
    return clean_value(match.group(2)) if match else UNKNOWN


def extract_archived_verdict(conclusion):
    if conclusion == UNKNOWN:
        return UNKNOWN
    leading = VERDICT_RE.match(conclusion)
    if leading:
        return leading.group(0)
    matches = VERDICT_RE.findall(conclusion)
    return matches[0] if matches else UNKNOWN


def archived_body_reason(body):
    for line in body:
        if not re.search(r"verdict|結案", line, re.IGNORECASE):
            continue
        value = clean_value(line)
        for separator in ("—", "–"):
            if separator in value:
                return first_sentence(value.split(separator, 1)[1])
        if "：" in value:
            value = value.split("：", 1)[1]
        elif ":" in value:
            value = value.split(":", 1)[1]
        return first_sentence(value)
    for line in body:
        value = clean_value(line)
        if value in {"---", UNKNOWN} or value.startswith("#") or value.startswith("試用週期"):
            continue
        return first_sentence(value)
    return UNKNOWN


def archived_entry(anchor, body):
    conclusion = archived_conclusion(anchor)
    verdict = extract_archived_verdict(conclusion)
    if verdict != UNKNOWN:
        reason = re.sub(rf"^{re.escape(verdict)}", "", conclusion, count=1).lstrip(" ：:—–-＋+／/")
        reason = first_sentence(reason) if reason else archived_body_reason(body)
    else:
        reason = archived_body_reason(body) if conclusion == UNKNOWN else first_sentence(conclusion)
    return {
        "id": slugify(archived_title(anchor)),
        "slug": slugify(archived_title(anchor)),
        "verdict": verdict,
        "date": archived_date(anchor),
        "reason": reason,
        "anchor": anchor,
    }


def current_topic(lines, end):
    topic = UNKNOWN
    for line in lines[:end]:
        if not line.startswith("## "):
            continue
        value = re.sub(r"^##\s+(?:子)?主題：", "", line).strip()
        if value:
            topic = value
    return topic


def topic_slug(value):
    value = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", value).strip()
    candidates = re.findall(r"[a-z0-9][a-z0-9-]{2,}", value.lower())
    return candidates[-1] if candidates else slugify(value)


def proofread_entry(anchor, body):
    match = PROOFREAD_ENTRY_RE.fullmatch(anchor)
    values = labeled_values(body)
    return {
        "id": match.group(1),
        "slug": values.get("文章", UNKNOWN),
        "article": values.get("文章", UNKNOWN),
        "classification": values.get("類別", UNKNOWN),
        "reason": first_sentence(values.get("校稿項目", values.get("修正", UNKNOWN))),
        "anchor": anchor,
    }


def factcheck_entry(anchor, body, topic):
    match = FACTCHECK_ENTRY_RE.fullmatch(anchor)
    values = labeled_values(body)
    identifier = match.group(1) or UNKNOWN
    classification = values.get("判定", UNKNOWN)
    reason = first_sentence(values.get("判定", values.get("宣稱", UNKNOWN)))
    return {
        "id": identifier,
        "topic": topic_slug(topic) if topic != UNKNOWN else UNKNOWN,
        "classification": classification,
        "reason": reason,
        "anchor": anchor,
    }


def parse_entries(source, kind):
    lines = read_lines(source)
    rows = []
    for start, end in entry_ranges(lines, kind):
        anchor = lines[start]
        body = lines[start + 1:end]
        if kind == "archived":
            rows.append(archived_entry(anchor, body))
        elif kind == "proofread":
            rows.append(proofread_entry(anchor, body))
        else:
            rows.append(factcheck_entry(anchor, body, current_topic(lines, start)))
    return rows


def index_fields(row, kind):
    if kind == "archived":
        return [row["slug"], row["verdict"], row["date"], row["reason"], row["anchor"]]
    if kind == "proofread":
        return [row["id"], row["article"], row["classification"], row["reason"], row["anchor"]]
    return [row["id"], row["topic"], row["classification"], row["reason"], row["anchor"]]


def index_line(row, kind):
    fields = index_fields(row, kind)
    return "｜".join([*(clean_value(value) for value in fields[:-1]), fields[-1]])


def index_data_lines(path):
    safe_path = ensure_no_symlink(path, "index-input")
    if not safe_path.is_file():
        return []
    rows = []
    for line in read_lines(safe_path):
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#") or trimmed.startswith("<!--") or trimmed == "---":
            continue
        rows.append(line)
    return rows


def parse_index_line(line):
    fields = line.split("｜", 4)
    if len(fields) != 5 or any(not field for field in fields):
        raise ValueError(f"index line must contain five non-empty fields: {line}")
    return fields


def write_atomic(path, text, label="write-target"):
    target = ensure_no_symlink(path, label)
    if not target.parent.is_dir():
        raise OSError(f"index parent directory does not exist: {target.parent}")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def index_header(kind, source):
    return f"# {Path(source).name} index\n# 格式：{INDEX_FORMATS[kind]}\n"


def build_index(source, output, kind):
    source_path = ensure_no_symlink(source, "source")
    output_path = ensure_no_symlink(output, "index-output")
    if source_path.resolve() == output_path.resolve():
        raise ValueError("source and index output must be different files")
    rows = parse_entries(source_path, kind)
    text = index_header(kind, source_path) + "".join(f"{index_line(row, kind)}\n" for row in rows)
    write_atomic(output_path, text, "index-output")
    return rows


def mark_pending(source, anchor):
    path = ensure_no_symlink(source, "source")
    lines = read_lines(path)
    try:
        position = lines.index(anchor)
    except ValueError as error:
        raise ValueError(f"cannot mark missing source anchor: {anchor}") from error
    next_position = position + 1
    while next_position < len(lines) and not lines[next_position].startswith("### "):
        if lines[next_position].strip() == INDEX_PENDING:
            return
        next_position += 1
    lines.insert(position + 1, INDEX_PENDING)
    write_atomic(path, "\n".join(lines) + "\n", "source")


def clear_pending(source, anchor):
    path = ensure_no_symlink(source, "source")
    lines = read_lines(path)
    try:
        position = lines.index(anchor)
    except ValueError:
        return
    end = position + 1
    while end < len(lines) and not lines[end].startswith("### "):
        end += 1
    filtered = [line for line in lines[position + 1:end] if line.strip() != INDEX_PENDING]
    if len(filtered) == end - position - 1:
        return
    updated = lines[: position + 1] + filtered + lines[end:]
    write_atomic(path, "\n".join(updated) + "\n", "source")


def append_index(source, index, kind, anchor, line):
    source_path = ensure_no_symlink(source, "source")
    index_path = ensure_no_symlink(index, "index-output")
    try:
        parse_index_line(line)
        if line.split("｜", 4)[-1] != anchor:
            raise ValueError("index line anchor does not match --anchor")
        if anchor not in read_lines(source_path):
            raise ValueError(f"source anchor not found: {anchor}")
        existing = index_data_lines(index_path)
        for existing_line in existing:
            fields = parse_index_line(existing_line)
            if fields[-1] != anchor:
                continue
            if existing_line == line:
                clear_pending(source_path, anchor)
                return "already-present"
            raise ValueError(f"index already has a different row for anchor: {anchor}")
        text = index_path.read_text(encoding="utf-8") if index_path.is_file() else index_header(kind, source_path)
        if text and not text.endswith("\n"):
            text += "\n"
        write_atomic(index_path, text + line + "\n", "index-output")
        clear_pending(source_path, anchor)
        return "appended"
    except Exception as error:
        try:
            mark_pending(source_path, anchor)
        except Exception as marker_error:
            raise RuntimeError(f"index append failed: {error}; pending marker failed: {marker_error}") from error
        raise RuntimeError(f"index append failed: {error}; source marked [index-pending]") from error


def reconcile(source, index, kind):
    source_rows = parse_entries(source, kind)
    source_anchors = [row["anchor"] for row in source_rows]
    index_lines = index_data_lines(index)
    index_rows = [parse_index_line(line) for line in index_lines]
    index_anchors = [row[-1] for row in index_rows]
    source_counts = Counter(source_anchors)
    index_counts = Counter(index_anchors)
    missing = []
    extra = []
    for anchor in source_anchors:
        if index_counts[anchor] > 0:
            index_counts[anchor] -= 1
        else:
            missing.append(anchor)
    for anchor in index_anchors:
        if source_counts[anchor] > 0:
            source_counts[anchor] -= 1
        else:
            extra.append(anchor)
    differences = len(missing) + len(extra)
    return {
        "source_count": len(source_rows),
        "index_count": len(index_rows),
        "differences": differences,
        "missing": missing,
        "extra": extra,
    }


def emit_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--kind", choices=INDEX_FORMATS, required=True)
    build.add_argument("--source", "--main", dest="source", required=True)
    build.add_argument("--output", "--index", dest="output", required=True)
    build.add_argument("--pending-anchor")
    build.add_argument("--json", action="store_true")

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--kind", choices=INDEX_FORMATS, required=True)
    inspect.add_argument("--source", "--main", dest="source", required=True)
    inspect.add_argument("--json", action="store_true")

    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--kind", choices=INDEX_FORMATS, required=True)
    reconcile_parser.add_argument("--source", "--main", dest="source", required=True)
    reconcile_parser.add_argument("--index", required=True)
    reconcile_parser.add_argument("--json", action="store_true")

    append = subparsers.add_parser("append")
    append.add_argument("--kind", choices=INDEX_FORMATS, required=True)
    append.add_argument("--source", "--main", dest="source", required=True)
    append.add_argument("--index", required=True)
    append.add_argument("--anchor", required=True)
    append.add_argument("--line", required=True)
    append.add_argument("--json", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            rows = build_index(args.source, args.output, args.kind)
            reconciliation = None
            if args.pending_anchor:
                reconciliation = reconcile(args.source, args.output, args.kind)
                if reconciliation["differences"] != 0:
                    raise RuntimeError(f"index build reconcile failed: {reconciliation}")
                clear_pending(args.source, args.pending_anchor)
            result = {"status": "pass", "kind": args.kind, "source": args.source, "index": args.output, "entries": len(rows)}
            if reconciliation is not None:
                result["reconcile"] = reconciliation
            if args.json:
                emit_json(result)
            else:
                print(f"已建立索引：{args.output}（{len(rows)} 筆）")
                if reconciliation is not None:
                    print(f"對帳差異：{reconciliation['differences']}")
            return 0
        if args.command == "inspect":
            rows = parse_entries(args.source, args.kind)
            if args.json:
                emit_json(rows)
            else:
                for row in rows:
                    print(index_line(row, args.kind))
            return 0
        if args.command == "reconcile":
            result = reconcile(args.source, args.index, args.kind)
            if args.json:
                emit_json(result)
            else:
                print(f"對帳：主檔 {result['source_count']} 筆｜索引 {result['index_count']} 筆｜差異 {result['differences']}")
                for anchor in result["missing"]:
                    print(f"缺索引：{anchor}")
                for anchor in result["extra"]:
                    print(f"多餘索引：{anchor}")
            return 0 if result["differences"] == 0 else 1
        result = append_index(args.source, args.index, args.kind, args.anchor, args.line)
        payload = {"status": "pass", "result": result, "source": args.source, "index": args.index, "anchor": args.anchor}
        if args.json:
            emit_json(payload)
        else:
            print(f"索引 append：{result}｜{args.anchor}")
        return 0
    except (OSError, ValueError, RuntimeError, UnicodeError) as error:
        if args.command == "build" and args.pending_anchor:
            try:
                ensure_no_symlink(args.source, "source")
                ensure_no_symlink(args.output, "index-output")
                mark_pending(args.source, args.pending_anchor)
                error = RuntimeError(f"index build failed: {error}; source marked [index-pending]")
            except Exception as marker_error:
                error = RuntimeError(f"index build failed: {error}; pending marker failed: {marker_error}")
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
