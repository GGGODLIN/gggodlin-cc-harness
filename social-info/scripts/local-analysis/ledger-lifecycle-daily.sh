#!/usr/bin/env bash
set -euo pipefail

exec python3 - "$@" <<'PY'
import argparse
import fnmatch
import glob
import hashlib
import json
import os
import re
import sys
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path


METRIC_UNITS = {
    "size": {"b", "byte", "bytes", "kb", "kib", "mb", "mib"},
    "size_bytes": {"b", "byte", "bytes"},
    "main_size": {"b", "byte", "bytes", "kb", "kib", "mb", "mib"},
    "state_size": {"b", "byte", "bytes", "kb", "kib", "mb", "mib"},
    "index_size": {"b", "byte", "bytes", "kb", "kib", "mb", "mib"},
    "line_count": {"lines"},
    "lines": {"lines"},
    "entry_age": {"months"},
    "entry_age_months": {"months"},
    "age_months": {"months"},
    "status": {"state"},
    "age_since_completion": {"days"},
    "completion_age_days": {"days"},
    "directory_age": {"days"},
    "directory_age_days": {"days"},
    "file_age": {"days"},
    "age": {"days"},
    "friction_age_days": {"days"},
    "legacy_dirs_present": {"boolean"},
    "exists": {"boolean"},
}


def parse_args():
    parser = argparse.ArgumentParser()
    home = Path.home()
    parser.add_argument("--root", default=os.environ.get("LEDGER_LIFECYCLE_ROOT", str(home)))
    parser.add_argument("--registry", default=os.environ.get("LEDGER_LIFECYCLE_REGISTRY"))
    parser.add_argument("--date", default=os.environ.get("LOCAL_ANALYSIS_DATE"))
    parser.add_argument("--out", default=os.environ.get("LEDGER_LIFECYCLE_OUT"))
    return parser.parse_args()


def logical_path(path, root):
    relative = Path(path).relative_to(root)
    return "~/" + relative.as_posix()


def mapped_path(pattern, root):
    if pattern == "~":
        return root
    if pattern.startswith("~/"):
        return root / pattern[2:]
    return Path(pattern)


def has_magic(pattern):
    return any(char in pattern for char in "*?[")


def template_score(pattern):
    static = sum(1 for char in pattern if char not in "*?[]")
    wildcards = sum(1 for char in pattern if char in "*?[")
    return static, -wildcards, len(pattern)


def scan_prefix(pattern):
    parts = Path(pattern).parts
    prefix = []
    for part in parts:
        if has_magic(part):
            break
        prefix.append(part)
    return Path(*prefix)


def has_symlink_component(path):
    candidate = path.absolute()
    current = Path(candidate.anchor)
    for part in candidate.parts:
        if part == candidate.anchor:
            continue
        current /= part
        if current.is_symlink():
            return True
    return False


def canonical_path(path):
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def path_in_scan_roots(path, scan_roots):
    if has_symlink_component(path):
        return False
    canonical_candidate = canonical_path(path)
    if canonical_candidate is None:
        return False
    for pattern in scan_roots:
        prefix = scan_prefix(mapped_path(pattern[0], pattern[1]))
        if has_symlink_component(prefix):
            continue
        canonical_prefix = canonical_path(prefix)
        if canonical_prefix is None:
            continue
        try:
            canonical_candidate.relative_to(canonical_prefix)
            return True
        except ValueError:
            continue
    return False


def glob_matches(pattern, value):
    pattern_parts = pattern.split("/")
    value_parts = value.split("/")

    @lru_cache(maxsize=None)
    def match(pattern_index, value_index):
        if pattern_index == len(pattern_parts):
            return value_index == len(value_parts)
        if pattern_parts[pattern_index] == "**":
            return match(pattern_index + 1, value_index) or (
                value_index < len(value_parts) and match(pattern_index, value_index + 1)
            )
        return (
            value_index < len(value_parts)
            and fnmatch.fnmatchcase(value_parts[value_index], pattern_parts[pattern_index])
            and match(pattern_index + 1, value_index + 1)
        )

    return match(0, 0)


def entries_for_path(registry_entries, path, root, scan_roots):
    matches = []
    for index, entry in enumerate(registry_entries):
        pattern = entry["path"]
        mapped = mapped_path(pattern, root)
        if not has_magic(pattern):
            if mapped == path:
                matches.append((1, (len(str(pattern)), 0, len(str(pattern))), index, entry))
            continue
        if not path_in_scan_roots(path, scan_roots):
            continue
        if glob_matches(mapped.as_posix(), path.as_posix()):
            matches.append((0, template_score(pattern), index, entry))
    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], -item[1][0], -item[1][1], -item[1][2], item[2]))
    return matches[0][3]


def candidate_paths(registry_entries, root, scan_roots):
    candidates = set()
    for entry in registry_entries:
        pattern = entry["path"]
        mapped = mapped_path(pattern, root)
        if not has_magic(pattern):
            if mapped.exists() and not has_symlink_component(mapped):
                candidates.add(mapped)
            continue
        for value in glob.glob(mapped.as_posix(), recursive=True):
            path = Path(value)
            if path.exists() and path_in_scan_roots(path, scan_roots):
                candidates.add(path)
    return sorted(candidates, key=lambda path: path.as_posix())


def compare(actual, operator, expected):
    if operator == ">":
        return actual > expected
    if operator == ">=":
        return actual >= expected
    if operator == "<":
        return actual < expected
    if operator == "<=":
        return actual <= expected
    if operator in ("=", "equals"):
        return actual == expected
    if operator == "exists":
        return bool(actual) == bool(expected)
    raise ValueError(f"unsupported threshold operator: {operator}")


def display_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def stable_identity(identity):
    return re.sub(r"\d{4}-\d{2}-\d{2}", "date", identity)


def source_key(identity):
    stable = stable_identity(identity)
    value = stable.removeprefix("~/")
    if value.startswith("Desktop/work/"):
        value = "work/" + value.removeprefix("Desktop/work/")
    elif value.startswith("Desktop/projects/"):
        value = value.removeprefix("Desktop/projects/")
        if value.startswith(".claude/"):
            value = value.removeprefix(".claude/")
        else:
            value = "projects/" + value
    elif value.startswith(".claude/"):
        value = value.removeprefix(".claude/")
    readable = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]
    return f"ledger-lifecycle:{readable}-{digest}"


def size_value(path, unit):
    size = path.stat().st_size
    if unit.lower() in {"byte", "bytes", "b"}:
        return float(size)
    if unit.lower() in {"kb", "kib"}:
        return size / 1024
    if unit.lower() in {"mb", "mib"}:
        return size / (1024 * 1024)
    raise ValueError(f"unsupported size unit: {unit}")


def entry_age_months(path, report_date):
    dates = [date.fromisoformat(value) for value in re.findall(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", path.read_text(encoding="utf-8", errors="replace"))]
    dates = [value for value in dates if value <= report_date]
    if not dates:
        return None
    oldest = min(dates)
    months = (report_date.year - oldest.year) * 12 + report_date.month - oldest.month
    if report_date.day < oldest.day:
        months -= 1
    return float(max(months, 0))


def completion_date(path):
    if path.is_file():
        candidates = [path]
    else:
        candidates = [
            path / ".completed",
            path / "COMPLETED",
            path / "completed",
            path / "COMPLETED.md",
            path / "completion.md",
            path / "status.md",
            path / "STATUS.md",
            path / "metadata.json",
            path / "manifest.json",
            path / "spec.md",
            path / "tasks.md",
        ]
    fields = ("completed_at", "completion_date", "closed_at", "finished_at", "completed")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        content = candidate.read_text(encoding="utf-8", errors="replace")
        if candidate.suffix == ".json":
            try:
                payload = json.loads(content)
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict):
                for field in fields:
                    value = payload.get(field)
                    if isinstance(value, str):
                        match = re.search(r"\d{4}-\d{2}-\d{2}", value)
                        if match is not None:
                            return date.fromisoformat(match.group(0))
        match = re.search(r"(?im)^\s*(?:completed_at|completion_date|closed_at|finished_at|completed)\s*[:=]\s*[\"']?(\d{4}-\d{2}-\d{2})", content)
        if match is not None:
            return date.fromisoformat(match.group(1))
        status = re.search(r"(?im)^\s*status\s*:\s*(closed|complete|completed)\s*$", content)
        if status is not None and candidate.name in {".completed", "COMPLETED", "completed", "status.md", "STATUS.md", "spec.md", "tasks.md"}:
            return date.fromtimestamp(candidate.stat().st_mtime)
    return None


def age_in_days(value, report_date):
    if value is None or value > report_date:
        return None
    return float((report_date - value).days)


def index_path_for(entry, root):
    relation = entry.get("index_path")
    if relation is None:
        relation = entry.get("index_file")
    if relation is None:
        relation = entry.get("index")
    if relation is None:
        relation = entry.get("index_relation")
    if isinstance(relation, dict):
        relation = relation.get("path")
    if not isinstance(relation, str) or not relation:
        return None
    return mapped_path(relation, root)


def index_entry_pattern(entry):
    relation = entry.get("index_relation")
    if isinstance(relation, dict):
        pattern = relation.get("entry_pattern") or relation.get("entry_regex")
        if isinstance(pattern, str) and pattern:
            return pattern
    pattern = entry.get("entry_pattern") or entry.get("entry_regex")
    if isinstance(pattern, str) and pattern:
        return pattern
    return r"^### .*\([^)]+[0-9]{4}-[0-9]{2}-[0-9]{2}[^)]*\)$"


def count_index_rows(path):
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or value.startswith("<!--") or value == "---":
            continue
        if value.startswith("|") and set(value.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue
        if len(rows) == 0 and "|" in value and any(token in value.lower() for token in ("id", "slug", "title", "標題")):
            continue
        rows.append(value)
    return len(rows)


def count_main_entries(path, pattern):
    regex = re.compile(pattern)
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if regex.search(line))


def is_active_trial_residue(path):
    parts = path.parts
    if "snapshot" not in parts:
        return False
    snapshot_index = len(parts) - 1 - tuple(reversed(parts)).index("snapshot")
    trial_dir = Path(*parts[:snapshot_index])
    active_path = trial_dir.parent / "active.md"
    if not active_path.is_file():
        return False
    slug = trial_dir.name
    for line in active_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^##\s+(.+?)\s+\(", line)
        if match is None:
            continue
        name = match.group(1)
        if name == slug or slug in name.split("-"):
            return True
    return False


def is_archived_trial_residue(path):
    parts = path.parts
    if parts[-3:] != ("snapshot", "before", "dirs"):
        return False
    return any(parts[index:index + 2] == ("trials", "archive") for index in range(len(parts) - 1))


def is_legacy_directory_target(path):
    if not path.is_dir():
        return False
    parts = path.parts
    if "dirs" not in parts:
        return True
    dirs_index = len(parts) - 1 - tuple(reversed(parts)).index("dirs")
    return len(parts) == dirs_index + 1


def threshold_override(entry, threshold):
    kind = re.sub(r"[^A-Za-z0-9]+", "_", str(entry.get("kind", ""))).strip("_").upper()
    metric = re.sub(r"[^A-Za-z0-9]+", "_", str(threshold.get("metric", ""))).strip("_").upper()
    unit = re.sub(r"[^A-Za-z0-9]+", "_", str(threshold.get("unit", ""))).strip("_").upper()
    names = [
        f"LEDGER_LIFECYCLE_{kind}_{metric}_{unit}_CAP",
        f"LEDGER_LIFECYCLE_{kind}_{metric}_CAP",
        f"LEDGER_LIFECYCLE_{metric}_{unit}_CAP",
        f"LEDGER_LIFECYCLE_{metric}_CAP",
        f"LEDGER_LIFECYCLE_THRESHOLD_{metric}",
        f"LEDGER_LIFECYCLE_CAP_{metric}",
    ]
    for name in names:
        value = os.environ.get(name)
        if value is None or value == "":
            continue
        if isinstance(threshold.get("value"), bool):
            return value.lower() in {"1", "true", "yes", "on"}
        return float(value)
    return threshold["value"]


def status_value(path):
    candidates = [path] if path.is_file() else [path / "STATUS.md", path / "status.md", path / "metadata.json", path / "manifest.json"]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        content = candidate.read_text(encoding="utf-8", errors="replace")
        if candidate.suffix == ".json":
            try:
                payload = json.loads(content)
                value = payload.get("status") if isinstance(payload, dict) else None
            except (TypeError, json.JSONDecodeError):
                value = None
            if isinstance(value, str) and value:
                return value
        match = re.search(r"(?im)^\s*status\s*:\s*([^\s#]+)", content)
        if match is not None:
            return match.group(1)
    return None


FRICTION_CLOSED_TITLES = {"## 已折／已否決", "## 已折 / 已否決"}
FRICTION_ENTRY_RE = re.compile(r"^- (?P<date>\d{4}-\d{2}-\d{2})(?:\s|$)")


def friction_candidate_ages(path, report_date):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    closed_start = next((index for index, line in enumerate(lines) if line in FRICTION_CLOSED_TITLES), None)
    if closed_start is None:
        return []
    closed_end = next((index for index in range(closed_start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    cutoff = report_date - timedelta(days=90)
    ages = []
    for line in lines[closed_start + 1:closed_end]:
        match = FRICTION_ENTRY_RE.match(line)
        if match is None:
            continue
        entry_date = date.fromisoformat(match.group("date"))
        if entry_date < cutoff:
            ages.append((report_date - entry_date).days)
    return ages


def friction_metric(path, report_date):
    ages = friction_candidate_ages(path, report_date)
    if not ages:
        return None
    return max(ages), f"候選 {len(ages)} 筆；不自動退場"


def threshold_hit(path, entry, threshold, report_date, index_path):
    metric = threshold["metric"]
    unit = threshold["unit"]
    if not isinstance(metric, str) or metric not in METRIC_UNITS:
        raise ValueError(f"unsupported threshold metric: {metric}")
    if not isinstance(unit, str) or unit.casefold() not in METRIC_UNITS[metric]:
        raise ValueError(f"unsupported threshold unit for {metric}: {unit}")
    note = ""
    if metric in {"size", "size_bytes", "main_size", "state_size", "index_size"}:
        target = index_path if metric == "index_size" else path
        if target is None or not target.is_file():
            return None
        actual = size_value(target, unit)
    elif metric in {"line_count", "lines"}:
        if not path.is_file():
            return None
        actual = float(len(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    elif metric in {"entry_age", "entry_age_months", "age_months"}:
        actual = entry_age_months(path, report_date)
        if actual is None:
            return None
    elif metric == "status":
        actual = status_value(path)
        if actual is None:
            return None
    elif metric in {"age_since_completion", "completion_age_days"}:
        actual = age_in_days(completion_date(path), report_date)
        if actual is None:
            return None
    elif metric in {"directory_age", "directory_age_days", "file_age", "age"}:
        actual = age_in_days(date.fromtimestamp(path.stat().st_mtime), report_date)
        if actual is None:
            return None
    elif metric == "friction_age_days":
        result = friction_metric(path, report_date)
        if result is None:
            return None
        actual, note = result
    elif metric in {"legacy_dirs_present", "exists"}:
        actual = path.exists()
    else:
        raise ValueError(f"unsupported threshold metric: {metric}")
    expected = threshold["value"] if isinstance(threshold["value"], (bool, str)) else float(threshold["value"])
    return actual, compare(actual, threshold["operator"], expected), note


def validate_threshold_support(entries):
    for entry_index, entry in enumerate(entries):
        for threshold_index, threshold in enumerate(entry.get("threshold") or []):
            metric = threshold.get("metric")
            unit = threshold.get("unit")
            field = f"entries[{entry_index}].threshold[{threshold_index}]"
            if not isinstance(metric, str) or metric not in METRIC_UNITS:
                raise ValueError(f"{field} has unsupported threshold metric: {metric}")
            if not isinstance(unit, str) or unit.casefold() not in METRIC_UNITS[metric]:
                raise ValueError(f"{field} has unsupported threshold unit for {metric}: {unit}")


def render(report_date, hits, output):
    if not hits:
        output.write_text("__SILENT__", encoding="utf-8")
        return
    lines = [f"# Ledger lifecycle — {report_date}", "", "## 命中", "", "| 標題 | source_key | 類別 | 路徑 | 指標 | 現況 | 門檻 | 狀態 | 備註 |", "|---|---|---|---|---:|---:|---:|---|---|"]
    for hit in hits:
        lines.append("| {title} | `{source_key}` | {kind} | `{path}` | {metric} | {actual} {unit} | {operator} {expected} {unit} | {status} | {note} |".format(**hit))
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    date_text = args.date or date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        raise SystemExit("--date must be YYYY-MM-DD")
    report_date = date.fromisoformat(date_text)
    root = Path(args.root).resolve()
    registry_path = mapped_path(args.registry, root) if args.registry else root / ".claude/scripts/ledger-lifecycle/registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = registry["entries"]
    validate_threshold_support(entries)
    scan_roots = [(pattern, root) for pattern in registry.get("scan_roots", [])]
    hits = []
    for path in candidate_paths(entries, root, scan_roots):
        entry = entries_for_path(entries, path, root, scan_roots)
        if entry is None or entry.get("kind") not in {"state", "append", "residue"}:
            continue
        if entry.get("kind") in {"state", "append"} and not path.is_file():
            continue
        if entry.get("kind") == "residue" and any(item.get("metric") == "legacy_dirs_present" for item in entry.get("threshold", [])) and not is_legacy_directory_target(path):
            continue
        if entry.get("kind") == "residue" and (is_active_trial_residue(path) or is_archived_trial_residue(path)):
            continue
        identity = logical_path(path, root) if has_magic(entry["path"]) else entry["path"]
        index_path = index_path_for(entry, root) if entry.get("kind") == "append" else None
        if entry.get("kind") == "append" and index_path is not None and index_path.is_file():
            main_count = count_main_entries(path, index_entry_pattern(entry))
            index_count = count_index_rows(index_path)
            if main_count != index_count:
                hits.append({
                    "title": f"索引漂移：{stable_identity(identity)}",
                    "source_key": f"ledger-lifecycle:index-drift:{stable_identity(path.name)}",
                    "kind": entry["kind"],
                    "path": logical_path(path, root),
                    "metric": "index_drift",
                    "actual": str(index_count),
                    "unit": "行",
                    "operator": "vs",
                    "expected": str(main_count),
                    "status": "索引行數不一致",
                    "note": "",
                })
        for threshold in entry.get("threshold", []):
            effective_threshold = dict(threshold)
            effective_threshold["value"] = threshold_override(entry, threshold)
            result = threshold_hit(path, entry, effective_threshold, report_date, index_path)
            if result is None:
                continue
            actual, matched, note = result
            if not matched:
                continue
            size_metric = effective_threshold["metric"] in {"size", "size_bytes", "main_size", "state_size", "index_size"}
            size_target = index_path if effective_threshold["metric"] == "index_size" else path
            hard_failure = size_metric and size_target is not None and size_target.is_file() and size_target.stat().st_size > 256 * 1024
            hits.append({
                "title": f"超過門檻：{stable_identity(identity)}",
                "source_key": source_key(identity),
                "kind": entry["kind"],
                "path": logical_path(path, root),
                "metric": effective_threshold["metric"],
                "actual": display_number(actual),
                "unit": effective_threshold["unit"],
                "operator": effective_threshold["operator"],
                "expected": display_number(effective_threshold["value"]),
                "status": "已故障" if hard_failure else "超過門檻",
                "note": note,
            })
    if args.out:
        out = Path(args.out)
    else:
        repo = Path(os.environ.get("SOCIAL_INFO_REPO_DIR", "~/code/social-info"))
        out = repo / "reports/local-analysis" / f"{date_text}-ledger-lifecycle.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    render(date_text, hits, out)


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
PY
