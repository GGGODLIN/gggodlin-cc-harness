#!/usr/bin/env python3
import fnmatch
import json
import os
import re
import sys
from functools import lru_cache
from typing import Any


KINDS = {"state", "append", "residue", "pure-log", "純log"}
OPERATORS = {">", ">=", "<", "<=", "=", "exists", "equals"}
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


def diagnostic(entry: int | None, field: str, code: str, message: str) -> dict[str, Any]:
    return {"entry": entry, "field": field, "code": code, "message": message}


def validate_registry(registry: Any) -> list[dict[str, Any]]:
    errors = []
    if not isinstance(registry, dict):
        return [diagnostic(None, "registry", "type", "registry must be an object")]
    schema_version = registry.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        errors.append(diagnostic(None, "schema_version", "required", "schema_version must be an integer"))
    elif schema_version != 1:
        errors.append(diagnostic(None, "schema_version", "unsupported", "schema_version must be 1"))
    scan_roots = registry.get("scan_roots")
    if not isinstance(scan_roots, list) or not scan_roots or any(not isinstance(value, str) or not value for value in scan_roots):
        errors.append(diagnostic(None, "scan_roots", "required", "scan_roots must be a non-empty string list"))
    entries = registry.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append(diagnostic(None, "entries", "required", "entries must be a non-empty list"))
        return errors
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(diagnostic(index, "entry", "type", "entry must be an object"))
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            errors.append(diagnostic(index, "path", "required", "path must be a non-empty string"))
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            errors.append(diagnostic(index, "kind", "invalid", "kind must be a supported lifecycle class"))
        pure_log = isinstance(kind, str) and kind in {"pure-log", "純log"}
        threshold = entry.get("threshold")
        if not pure_log and (not isinstance(threshold, list) or not threshold):
            errors.append(diagnostic(index, "threshold", "required", "threshold must contain at least one rule outside pure-log"))
        if threshold is not None:
            if not isinstance(threshold, list):
                errors.append(diagnostic(index, "threshold", "type", "threshold must be a list"))
            else:
                for threshold_index, item in enumerate(threshold):
                    field = f"threshold[{threshold_index}]"
                    if not isinstance(item, dict):
                        errors.append(diagnostic(index, field, "type", "threshold item must be an object"))
                        continue
                    metric = item.get("metric")
                    if not isinstance(metric, str) or not metric:
                        errors.append(diagnostic(index, f"{field}.metric", "required", "metric must be a non-empty string"))
                    elif metric not in METRIC_UNITS:
                        errors.append(diagnostic(index, f"{field}.metric", "unsupported", "metric is not supported by the lifecycle channel"))
                    unit = item.get("unit")
                    if not isinstance(unit, str) or not unit:
                        errors.append(diagnostic(index, f"{field}.unit", "required", "unit must be a non-empty string"))
                    elif metric in METRIC_UNITS and unit.casefold() not in METRIC_UNITS[metric]:
                        errors.append(diagnostic(index, f"{field}.unit", "unsupported", "unit is not supported for this metric"))
                    operator = item.get("operator")
                    if not isinstance(operator, str) or operator not in OPERATORS:
                        errors.append(diagnostic(index, f"{field}.operator", "invalid", "operator is not supported"))
                    if "value" not in item or item["value"] is None:
                        errors.append(diagnostic(index, f"{field}.value", "required", "value is required"))
                    elif isinstance(item["value"], (list, dict)):
                        errors.append(diagnostic(index, f"{field}.value", "type", "value must be a scalar"))
        action = entry.get("action")
        if pure_log:
            if action is not None and (not isinstance(action, str) or not action):
                errors.append(diagnostic(index, "action", "type", "action must be a non-empty string or null"))
        elif not isinstance(action, str) or not action:
            errors.append(diagnostic(index, "action", "required", "action must be a non-empty string outside pure-log"))
        for optional in ("retirement", "owner"):
            if optional in entry and entry[optional] is not None and not isinstance(entry[optional], str):
                errors.append(diagnostic(index, optional, "type", f"{optional} must be a string or null"))
        if "known_paths" in entry:
            known_paths = entry["known_paths"]
            if not isinstance(known_paths, list) or any(not isinstance(value, str) or not value for value in known_paths):
                errors.append(diagnostic(index, "known_paths", "type", "known_paths must be a string list"))
        if "index_path" in entry:
            index_path = entry["index_path"]
            if index_path is not None and (not isinstance(index_path, str) or not index_path):
                errors.append(diagnostic(index, "index_path", "type", "index_path must be a non-empty string or null"))
        if "index_relation" in entry:
            relation = entry["index_relation"]
            if not isinstance(relation, dict):
                errors.append(diagnostic(index, "index_relation", "type", "index_relation must be an object"))
            else:
                relation_path = relation.get("path")
                if relation_path is not None and (not isinstance(relation_path, str) or not relation_path):
                    errors.append(diagnostic(index, "index_relation.path", "type", "index_relation.path must be a non-empty string or null"))
                for relation_field in ("entry_pattern", "format"):
                    if relation_field in relation and (not isinstance(relation[relation_field], str) or not relation[relation_field]):
                        errors.append(diagnostic(index, f"index_relation.{relation_field}", "type", f"index_relation.{relation_field} must be a non-empty string"))
                pattern = relation.get("entry_pattern")
                if isinstance(pattern, str) and pattern:
                    try:
                        re.compile(pattern)
                    except re.error as error:
                        errors.append(diagnostic(index, "index_relation.entry_pattern", "invalid", f"index_relation.entry_pattern is not a valid regex: {error}"))
                if "anchor_field" in relation and (not isinstance(relation["anchor_field"], int) or isinstance(relation["anchor_field"], bool) or relation["anchor_field"] < 1):
                    errors.append(diagnostic(index, "index_relation.anchor_field", "type", "index_relation.anchor_field must be a positive integer"))
                if entry.get("index_path") is not None and relation_path is not None and entry["index_path"] != relation_path:
                    errors.append(diagnostic(index, "index_relation.path", "mismatch", "index_relation.path must match index_path"))
    return errors


def load_registry(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def normalize_path(value: str) -> str:
    return os.path.normpath(os.path.expanduser(value))


def has_magic(value: str) -> bool:
    return any(character in value for character in "*?[")


def glob_matches(pattern: str, value: str) -> bool:
    pattern_parts = pattern.split("/")
    value_parts = value.split("/")

    @lru_cache(maxsize=None)
    def match(pattern_index: int, value_index: int) -> bool:
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


def template_specificity(pattern: str) -> tuple[int, int, int]:
    score = 0
    recursive_count = 0
    wildcard_count = 0
    for part in pattern.split("/"):
        if part == "**":
            recursive_count += 1
            continue
        in_class = False
        for character in part:
            if in_class:
                if character == "]":
                    in_class = False
                continue
            if character == "[":
                in_class = True
                score += 2
                wildcard_count += 1
            elif character == "?":
                score += 2
                wildcard_count += 1
            elif character == "*":
                score += 1
                wildcard_count += 1
            else:
                score += 4
    return (-score, recursive_count, wildcard_count)


def resolve_entry(registry: dict[str, Any], requested_path: str) -> dict[str, Any]:
    normalized_requested = normalize_path(requested_path)
    exact = []
    templates = []
    for index, entry in enumerate(registry["entries"]):
        pattern = normalize_path(entry["path"])
        if not has_magic(pattern) and pattern == normalized_requested:
            exact.append((index, entry))
        elif has_magic(pattern) and glob_matches(pattern, normalized_requested):
            templates.append((*template_specificity(pattern), index, entry))
    if exact:
        index, entry = exact[0]
        return {"status": "pass", "matched_by": "exact", "entry_index": index, "entry": entry}
    if templates:
        _, _, _, index, entry = sorted(templates)[0]
        return {"status": "pass", "matched_by": "template", "entry_index": index, "entry": entry}
    return {"status": "not-found", "path": requested_path}


def main(argv: list[str]) -> int:
    if len(argv) == 2:
        command = "validate"
        registry_path = argv[1]
    elif len(argv) == 3 and argv[1] == "validate":
        command = argv[1]
        registry_path = argv[2]
    elif len(argv) == 4 and argv[1] == "resolve":
        command = argv[1]
        registry_path = argv[2]
    else:
        return 2
    try:
        registry = load_registry(registry_path)
    except json.JSONDecodeError as error:
        print(json.dumps({"status": "fail", "errors": [diagnostic(None, "registry", "invalid_json", f"invalid JSON: {error.msg}")]}, ensure_ascii=False))
        return 1
    except UnicodeDecodeError:
        print(json.dumps({"status": "fail", "errors": [diagnostic(None, "registry", "invalid_encoding", "registry must be UTF-8")]}, ensure_ascii=False))
        return 1
    except OSError as error:
        print(json.dumps({"status": "fail", "errors": [diagnostic(None, "registry", "read_error", str(error))]}, ensure_ascii=False))
        return 2
    errors = validate_registry(registry)
    if errors:
        print(json.dumps({"status": "fail", "errors": errors}, ensure_ascii=False))
        return 1
    if command == "validate":
        print(json.dumps({"status": "pass", "entries": len(registry["entries"])}, ensure_ascii=False))
        return 0
    result = resolve_entry(registry, argv[3])
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
