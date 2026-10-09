#!/usr/bin/env python3
"""Summarize and extract compact merge-conflict context from a Git repository."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


START_RE = re.compile(r"^<<<<<<<(?: (.*))?$")
BASE_RE = re.compile(r"^\|\|\|\|\|\|\|(?: (.*))?$")
END_RE = re.compile(r"^>>>>>>>(?: (.*))?$")


def find_repo_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "not a git repository"
        raise RuntimeError(message)
    return Path(result.stdout.strip()).resolve()


def display_path(path: str) -> str:
    return path.encode("utf-8", errors="backslashreplace").decode("utf-8")


def get_unmerged_entries(repo_root: Path) -> dict[str, dict[int, dict[str, str]]]:
    entries: dict[str, dict[int, dict[str, str]]] = {}
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-u", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip() or "unknown git error"
        raise RuntimeError(f"git ls-files -u -z failed: {message}")
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", 1)
        mode, object_id, stage_text = metadata.decode("ascii").split()
        path = os.fsdecode(path_bytes)
        file_entry = entries.setdefault(path, {})
        file_entry[int(stage_text)] = {"mode": mode, "object_id": object_id}
    return entries


def read_text_file(repo_root: Path, path: str) -> list[str] | None:
    parts = Path(path).parts
    if not parts:
        return None
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(repo_root, directory_flags)
    except OSError:
        return None
    descriptor: int | None = None
    try:
        for component in parts[:-1]:
            component_stat = os.stat(component, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISDIR(component_stat.st_mode):
                return None
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_stat = os.stat(parts[-1], dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(file_stat.st_mode):
            return None
        descriptor = os.open(parts[-1], file_flags, dir_fd=directory_fd)
    except OSError:
        return None
    finally:
        os.close(directory_fd)
    if descriptor is None:
        return None
    try:
        with os.fdopen(descriptor, encoding="utf-8", errors="replace") as file:
            text = file.read()
    except OSError:
        return None
    if "\x00" in text:
        return None
    return text.splitlines()


def get_local_object_source(repo_root: Path) -> tuple[Path, str] | None:
    common_dir = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    object_format = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--show-object-format"],
        capture_output=True,
        text=True,
        check=False,
    )
    if common_dir.returncode != 0 or object_format.returncode != 0:
        return None
    return Path(common_dir.stdout.strip()) / "objects", object_format.stdout.strip()


def build_stage_preview(
    reader_git_dir: Path | None,
    object_directory: Path | None,
    entry: dict[str, str] | None,
    max_lines: int,
) -> dict[str, object]:
    if entry is None:
        return {"status": "missing"}
    mode = entry["mode"]
    object_id = entry["object_id"]
    identity = {"mode": mode, "object_id": object_id}
    if mode == "160000":
        return {**identity, "status": "gitlink", "commit": object_id}
    if reader_git_dir is None or object_directory is None:
        return {**identity, "status": "unavailable"}
    result = subprocess.run(
        ["git", f"--git-dir={reader_git_dir}", "cat-file", "blob", object_id],
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(object_directory),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if result.returncode != 0:
        return {**identity, "status": "unavailable"}
    if b"\x00" in result.stdout:
        return {**identity, "status": "binary", "size": len(result.stdout)}
    lines = result.stdout.decode("utf-8", errors="replace").splitlines()
    return {**identity, "status": "text", "lines": truncate_lines(lines, max_lines)}


def truncate_lines(lines: list[str], max_lines: int) -> list[str]:
    if len(lines) <= max_lines:
        return lines
    omitted = len(lines) - max_lines
    return [*lines[:max_lines], f"... ({omitted} more lines omitted)"]


def build_diff(
    left_lines: list[str],
    right_lines: list[str],
    left_label: str,
    right_label: str,
    max_lines: int,
) -> list[str]:
    diff = list(
        difflib.unified_diff(
            left_lines,
            right_lines,
            fromfile=left_label,
            tofile=right_label,
            lineterm="",
        )
    )
    if not diff:
        diff = ["(no textual diff)"]
    return truncate_lines(diff, max_lines)


def classify_conflict(stages: list[int], marker_hunks: int) -> str:
    stage_set = set(stages)
    if stage_set == {2, 3}:
        return "add/add"
    if stage_set == {1, 2}:
        return "deleted-by-them"
    if stage_set == {1, 3}:
        return "deleted-by-us"
    if marker_hunks:
        return "text"
    if stage_set == {1, 2, 3}:
        return "index-only"
    return "unmerged"


def normalize_requested_path(repo_root: Path, raw_path: str) -> str:
    path = Path(raw_path)
    candidate = Path(os.path.abspath(path if path.is_absolute() else repo_root / path))
    try:
        return str(candidate.relative_to(repo_root))
    except ValueError as error:
        raise RuntimeError(f"path is outside repository: {display_path(raw_path)}") from error


def parse_conflict_hunks(lines: list[str], context: int) -> tuple[list[dict[str, object]], str | None]:
    hunks: list[dict[str, object]] = []
    index = 0
    while index < len(lines):
        start_match = START_RE.match(lines[index])
        if not start_match:
            index += 1
            continue

        start_index = index
        ours_label = start_match.group(1) or "ours"
        index += 1
        ours: list[str] = []
        base: list[str] = []
        theirs: list[str] = []
        base_label: str | None = None
        theirs_label = "theirs"

        while index < len(lines):
            base_match = BASE_RE.match(lines[index])
            if base_match:
                base_label = base_match.group(1) or "base"
                index += 1
                while index < len(lines) and lines[index] != "=======":
                    base.append(lines[index])
                    index += 1
                break
            if lines[index] == "=======":
                break
            ours.append(lines[index])
            index += 1

        if index >= len(lines) or lines[index] != "=======":
            return hunks, f"unterminated conflict starting at line {start_index + 1}"

        index += 1
        end_index = index
        while index < len(lines):
            end_match = END_RE.match(lines[index])
            if end_match:
                theirs_label = end_match.group(1) or "theirs"
                end_index = index
                index += 1
                break
            theirs.append(lines[index])
            index += 1
        else:
            return hunks, f"unterminated conflict starting at line {start_index + 1}"

        hunks.append(
            {
                "start_line": start_index + 1,
                "end_line": end_index + 1,
                "before_context": lines[max(0, start_index - context):start_index],
                "ours": ours,
                "ours_label": ours_label,
                "base": base or None,
                "base_label": base_label,
                "theirs": theirs,
                "theirs_label": theirs_label,
                "after_context": lines[index:index + context],
            }
        )

    return hunks, None


def build_summary_report(repo_root: Path, path: str, stage_entries: dict[int, dict[str, str]], context: int) -> dict[str, object]:
    has_gitlink = any(entry["mode"] == "160000" for entry in stage_entries.values())
    worktree_lines = None if has_gitlink else read_text_file(repo_root, path)
    hunks: list[dict[str, object]] = []
    parse_error = None
    if worktree_lines is not None:
        hunks, parse_error = parse_conflict_hunks(worktree_lines, context)
    stages = sorted(stage_entries)
    return {
        "path": path,
        "stages": stages,
        "stage_entries": stage_entries,
        "conflict_type": classify_conflict(stages, len(hunks)),
        "marker_hunks": len(hunks),
        "parse_error": parse_error,
        "worktree_present": worktree_lines is not None,
        "hunks": hunks,
    }


def build_index_preview(repo_root: Path, report: dict[str, object], max_lines: int) -> dict[str, object]:
    stage_entries = dict(report["stage_entries"])
    object_source = get_local_object_source(repo_root)
    with tempfile.TemporaryDirectory(prefix="conflict-object-reader-") as temp_dir:
        reader_git_dir: Path | None = None
        object_directory: Path | None = None
        if object_source is not None and object_source[1] in {"sha1", "sha256"}:
            object_directory, object_format = object_source
            candidate_reader = Path(temp_dir) / "repo.git"
            init_result = subprocess.run(
                [
                    "git",
                    "init",
                    "--bare",
                    "--quiet",
                    "--template=",
                    f"--object-format={object_format}",
                    str(candidate_reader),
                ],
                capture_output=True,
                check=False,
                env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
            )
            if init_result.returncode == 0:
                reader_git_dir = candidate_reader
        preview = {
            "ours": build_stage_preview(reader_git_dir, object_directory, stage_entries.get(2), max_lines),
            "theirs": build_stage_preview(reader_git_dir, object_directory, stage_entries.get(3), max_lines),
            "base": build_stage_preview(reader_git_dir, object_directory, stage_entries.get(1), max_lines),
        }
    ours = preview["ours"]
    theirs = preview["theirs"]
    if ours["status"] == "text" and theirs["status"] == "text":
        preview["ours_vs_theirs_diff"] = build_diff(
            list(ours["lines"]),
            list(theirs["lines"]),
            "ours",
            "theirs",
            max_lines,
        )
    return preview


def section_lines(title: str, lines: list[str] | None) -> list[str]:
    if lines is None:
        return [f"{title}:", "  (not present)"]
    if not lines:
        return [f"{title}:", "  (empty)"]
    return [f"{title}:", *[f"  {line}" for line in lines]]


def stage_section_lines(title: str, preview: dict[str, object]) -> list[str]:
    status = str(preview["status"])
    if status == "text":
        return section_lines(title, list(preview["lines"]))
    if status == "missing":
        return [f"{title}:", "  (stage missing)"]
    if status == "gitlink":
        return [f"{title}:", f"  (gitlink mode=160000 commit={preview['commit']})"]
    identity = f"mode={preview['mode']} object={preview['object_id']}"
    if status == "binary":
        return [f"{title}:", f"  (binary {identity} bytes={preview['size']})"]
    return [f"{title}:", f"  (object unavailable locally {identity})"]


def render_summary_text(repo_root: Path, reports: list[dict[str, object]]) -> str:
    lines = [f"repo: {repo_root}", f"conflicted files: {len(reports)}"]
    for report in reports:
        stages = ",".join(str(stage) for stage in report["stages"])
        lines.append(
            f"- {display_path(str(report['path']))} | type={report['conflict_type']} | stages={stages} | hunks={report['marker_hunks']}"
        )
        if report["parse_error"]:
            lines.append(f"  parse-error: {report['parse_error']}")
    lines.append("use --file <path> for compact details about one conflicted file")
    return "\n".join(lines)


def render_detail_text(
    repo_root: Path,
    report: dict[str, object],
    max_lines: int,
) -> str:
    lines = [
        f"== {display_path(str(report['path']))} ==",
        f"type: {report['conflict_type']}",
        f"stages: {', '.join(str(stage) for stage in report['stages'])}",
    ]
    parse_error = report["parse_error"]
    if parse_error:
        lines.append(f"parse-error: {parse_error}")

    hunks = report["hunks"]
    if hunks:
        lines.append(f"hunks: {len(hunks)}")
        for index, hunk in enumerate(hunks, start=1):
            ours = list(hunk["ours"])
            theirs = list(hunk["theirs"])
            diff = build_diff(
                ours,
                theirs,
                str(hunk["ours_label"]),
                str(hunk["theirs_label"]),
                max_lines,
            )
            lines.extend(
                [
                    "",
                    f"[hunk {index}] current lines {hunk['start_line']}-{hunk['end_line']}",
                    *section_lines("before", truncate_lines(list(hunk["before_context"]), max_lines)),
                    *section_lines(
                        f"ours ({hunk['ours_label']})",
                        truncate_lines(ours, max_lines),
                    ),
                ]
            )
            if hunk["base"] is not None:
                lines.extend(
                    section_lines(
                        f"base ({hunk['base_label'] or 'base'})",
                        truncate_lines(list(hunk["base"]), max_lines),
                    )
                )
            lines.extend(
                [
                    *section_lines(
                        f"theirs ({hunk['theirs_label']})",
                        truncate_lines(theirs, max_lines),
                    ),
                    *section_lines("ours vs theirs diff", diff),
                    *section_lines("after", truncate_lines(list(hunk["after_context"]), max_lines)),
                ]
            )
        return "\n".join(lines)

    preview = build_index_preview(repo_root, report, max_lines)
    lines.append("hunks: 0")
    lines.append("index preview:")
    lines.extend(stage_section_lines("ours", preview["ours"]))
    lines.extend(stage_section_lines("base", preview["base"]))
    lines.extend(stage_section_lines("theirs", preview["theirs"]))
    if "ours_vs_theirs_diff" in preview:
        lines.extend(section_lines("ours vs theirs diff", preview["ours_vs_theirs_diff"]))
    return "\n".join(lines)


def render_json(
    repo_root: Path,
    reports: list[dict[str, object]],
    include_details: bool,
    max_lines: int,
) -> str:
    files: list[dict[str, object]] = []
    for report in reports:
        file_entry: dict[str, object] = {
            "path": report["path"],
            "conflict_type": report["conflict_type"],
            "stages": report["stages"],
            "marker_hunks": report["marker_hunks"],
            "parse_error": report["parse_error"],
        }
        if include_details:
            if report["hunks"]:
                file_entry["hunks"] = [
                    {
                        "start_line": hunk["start_line"],
                        "end_line": hunk["end_line"],
                        "before_context": truncate_lines(list(hunk["before_context"]), max_lines),
                        "ours_label": hunk["ours_label"],
                        "ours": truncate_lines(list(hunk["ours"]), max_lines),
                        "base_label": hunk["base_label"],
                        "base": truncate_lines(list(hunk["base"]), max_lines) if hunk["base"] else None,
                        "theirs_label": hunk["theirs_label"],
                        "theirs": truncate_lines(list(hunk["theirs"]), max_lines),
                        "after_context": truncate_lines(list(hunk["after_context"]), max_lines),
                        "ours_vs_theirs_diff": build_diff(
                            list(hunk["ours"]),
                            list(hunk["theirs"]),
                            str(hunk["ours_label"]),
                            str(hunk["theirs_label"]),
                            max_lines,
                        ),
                    }
                    for hunk in report["hunks"]
                ]
            else:
                file_entry["index_preview"] = build_index_preview(repo_root, report, max_lines)
        files.append(file_entry)

    return json.dumps(
        {
            "repo_root": str(repo_root),
            "conflicted_files": files,
        },
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize and extract compact merge-conflict context."
    )
    parser.add_argument("--repo", default=".", help="Path inside the target repository.")
    parser.add_argument(
        "--file",
        action="append",
        help="One conflicted file to inspect in detail.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of text.",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=2,
        help="Lines of surrounding context to include around each conflict hunk.",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=40,
        help="Maximum lines to print for each section before truncating.",
    )
    args = parser.parse_args()

    if args.file and len(args.file) > 1:
        parser.error("--file may be provided only once")
    if args.context < 0:
        parser.error("--context must be non-negative")
    if args.max_lines <= 0:
        parser.error("--max-lines must be positive")

    try:
        repo_root = find_repo_root(Path(args.repo).resolve())
        entries = get_unmerged_entries(repo_root)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    try:
        validated_entries = {
            normalize_requested_path(repo_root, path): stage_entries
            for path, stage_entries in entries.items()
        }
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if len(validated_entries) != len(entries):
        print("error: conflicting paths collapse to the same repository path", file=sys.stderr)
        return 2

    reports = [
        build_summary_report(repo_root, path, validated_entries[path], args.context)
        for path in sorted(validated_entries)
    ]

    if args.file:
        try:
            requested_path = normalize_requested_path(repo_root, args.file[0])
        except RuntimeError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        known_paths = {str(report["path"]) for report in reports}
        if requested_path not in known_paths:
            print(f"error: conflicted file not found: {display_path(requested_path)}", file=sys.stderr)
            return 2
        selected_reports = [report for report in reports if report["path"] == requested_path]
    else:
        selected_reports = []

    if not reports:
        message = json.dumps({"repo_root": str(repo_root), "conflicted_files": []}, indent=2) if args.json else f"repo: {repo_root}\nconflicted files: 0"
        print(message)
        return 0

    if args.json:
        print(render_json(repo_root, selected_reports or reports, bool(selected_reports), args.max_lines))
        return 0

    if not selected_reports:
        print(render_summary_text(repo_root, reports))
        return 0

    print("\n\n".join(render_detail_text(repo_root, report, args.max_lines) for report in selected_reports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
