#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from path_safety import ensure_no_symlink, symlink_component

H2_RE = re.compile(r"^##\s+(.+?)\s*\((\d{4}-\d{2}-\d{2})([^)]*)\)\s*$")
DATE_H2_RE = re.compile(r"^##\s+.*\(.*\d{4}-\d{2}-\d{2}.*\)")
DETAIL_SLUG_RE = re.compile(r"^active/(.+)-(\d{4}-\d{2}-\d{2})(?:-[1-9]\d*)?\.md$")
INDEX_RE = {
    "started": re.compile(r"^-\s+started:\s+(\d{4}-\d{2}-\d{2})\s*$"),
    "status": re.compile(r"^-\s+status:\s+([^\s]+)\s*$"),
    "detail": re.compile(r"^-\s+detail:\s+`?([^`\s]+)`?\s*$"),
}
START_RE = re.compile(
    r"^-\s+\*{0,2}(?:start|started|candidate start|開案|起始)\*{0,2}\s*[:：]?\s*`?(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
STATUS_RE = re.compile(r"^-\s+(?:status|state)\s*[:=]\s*`?([^`\s]+)", re.IGNORECASE)


def slugify(title):
    normalized = unicodedata.normalize("NFKC", title).strip().lower()
    slug = re.sub(r"[\W_]+", "-", normalized, flags=re.UNICODE).strip("-")
    if not slug:
        raise ValueError(f"slug-empty:{title}")
    return slug


def parse_h2(line):
    return H2_RE.match(line.rstrip("\n"))


def parse_index(block):
    fields = {}
    for line in block[1:]:
        stripped = line.rstrip("\n")
        if not stripped:
            break
        matched = False
        for name, pattern in INDEX_RE.items():
            match = pattern.match(stripped)
            if match:
                fields[name] = match.group(1)
                matched = True
                break
        if not matched:
            break
    return fields


def details_root(details_dir):
    return ensure_no_symlink(details_dir, "details-dir").resolve()


def detail_path(details_dir, pointer):
    path = Path(pointer)
    if path.is_absolute() or ".." in path.parts or len(path.parts) < 2 or path.parts[0] != "active":
        raise ValueError(f"detail-path-invalid:{pointer}")
    root = details_root(details_dir)
    relative = Path(*path.parts[1:])
    unresolved = ensure_no_symlink(root.joinpath(relative), "detail-path")
    target = unresolved.resolve()
    if os.path.commonpath((str(root), str(target))) != str(root):
        raise ValueError(f"detail-path-invalid:{pointer}")
    return target


def find_started(block):
    for line in block[1:]:
        match = START_RE.match(line.rstrip("\n"))
        if match:
            return match.group(1)
    return None


def find_status(block):
    for line in block[1:]:
        match = STATUS_RE.match(line.rstrip("\n"))
        if match:
            return match.group(1)
    return "active"


def read_detail_identity(target):
    with target.open(encoding="utf-8") as handle:
        lines = [handle.readline().rstrip("\n"), handle.readline().rstrip("\n")]
    values = {}
    for line in lines:
        if line.startswith("detail-key: "):
            values["key"] = line[len("detail-key: "):]
        elif line.startswith("detail-title: "):
            values["title"] = line[len("detail-title: "):]
    return values


def slug_from_pointer(pointer):
    match = DETAIL_SLUG_RE.fullmatch(pointer)
    return match.group(1) if match else None


def date_from_pointer(pointer):
    match = DETAIL_SLUG_RE.fullmatch(pointer)
    return match.group(2) if match else None


def slug_from_title(title):
    match = re.fullmatch(r"(.+) \[run-(\d+)\]", title)
    if match:
        return f"{slugify(match.group(1))}-{match.group(2)}"
    return slugify(title)


def candidate_blocks(lines):
    date_shaped = [index for index, line in enumerate(lines) if DATE_H2_RE.match(line.rstrip("\n"))]
    starts = [index for index in date_shaped if parse_h2(lines[index])]
    unclassified = [lines[index].rstrip("\n") for index in date_shaped if not parse_h2(lines[index])]
    if not starts:
        return lines, [], unclassified
    prefix = lines[: starts[0]]
    accepted = [starts[0]]
    for position, start in enumerate(starts[1:], 1):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        block = lines[start:end]
        fields = parse_index(block)
        if fields or find_started(block):
            accepted.append(start)
        else:
            unclassified.append(lines[start].rstrip("\n"))
    entries = []
    for position, start in enumerate(accepted):
        end = accepted[position + 1] if position + 1 < len(accepted) else len(lines)
        entries.append({"match": parse_h2(lines[start]), "block": lines[start:end]})
    return prefix, entries, unclassified


def build_plan(active, details_dir):
    ensure_no_symlink(active, "active")
    details_root(details_dir)
    lines = active.read_text(encoding="utf-8").splitlines(keepends=True)
    prefix, entries, unclassified = candidate_blocks(lines)
    errors = [f"unclassified-h2:{line}" for line in unclassified]
    warnings = []
    slug_counts = {}
    used_slugs = set()
    reserved_targets = set()
    root = details_root(details_dir)
    for entry in entries:
        fields = parse_index(entry["block"])
        if fields.keys() >= {"started", "status", "detail"}:
            indexed_slug = slug_from_pointer(fields["detail"])
            if indexed_slug:
                used_slugs.add(indexed_slug)
                slug_counts[indexed_slug] = max(slug_counts.get(indexed_slug, 0), 1)
    plan = []
    for entry in entries:
        match = entry["match"]
        block = entry["block"]
        title, review_date, review_suffix = match.groups()
        fields = parse_index(block)
        if fields.keys() >= {"started", "status", "detail"}:
            try:
                target = detail_path(details_dir, fields["detail"])
            except ValueError as error:
                errors.append(str(error))
                continue
            if not target.is_file():
                errors.append(f"detail-missing:{fields['detail']}")
            else:
                identity = read_detail_identity(target)
                actual_slug = slug_from_pointer(fields["detail"])
                expected_slug = slug_from_title(title)
                actual_date = date_from_pointer(fields["detail"])
                if (
                    identity.get("key") != fields["detail"]
                    or identity.get("title") != title
                    or actual_slug != expected_slug
                    or actual_date != fields["started"]
                ):
                    errors.append(f"detail-mismatch:{fields['detail']}")
            reserved_targets.add(target)
            indexed_slug = slug_from_pointer(fields["detail"])
            if indexed_slug:
                used_slugs.add(indexed_slug)
                slug_counts[indexed_slug] = max(slug_counts.get(indexed_slug, 0), 1)
            plan.append({"main": block, "detail": None, "target": target, "title": title})
            continue
        if fields:
            errors.append(f"index-incomplete:{title}")
            continue
        started = find_started(block)
        if started is None:
            errors.append(f"started-missing:{title}")
            continue
        base_slug = slugify(title)
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        ordinal = slug_counts[base_slug]
        candidate_index = ordinal
        candidate_slug = base_slug if ordinal == 1 else f"{base_slug}-{ordinal}"
        duplicate = ordinal > 1
        while candidate_slug in used_slugs:
            candidate_index += 1
            candidate_slug = f"{base_slug}-{candidate_index}"
            duplicate = True
        filename = f"{candidate_slug}-{started}.md"
        target = root / filename
        while True:
            ensure_no_symlink(target, "detail-target")
            if target not in reserved_targets and not target.exists():
                break
            candidate_index += 1
            candidate_slug = f"{base_slug}-{candidate_index}"
            filename = f"{candidate_slug}-{started}.md"
            target = root / filename
            duplicate = True
        if duplicate:
            display_title = f"{title} [run-{candidate_index}]"
            warnings.append(f"duplicate-slug:{title} kept as {candidate_slug}")
        else:
            display_title = title
        used_slugs.add(candidate_slug)
        reserved_targets.add(target)
        pointer = f"active/{filename}"
        main = [
            f"## {display_title} ({review_date}{review_suffix})\n",
            f"- started: {started}\n",
            f"- status: {find_status(block)}\n",
            f"- detail: `{pointer}`\n",
            "\n",
        ]
        plan.append({
            "main": main,
            "detail": [f"detail-key: {pointer}\n", f"detail-title: {display_title}\n"] + block,
            "target": target,
            "title": title,
            "duplicate": duplicate,
            "pointer": pointer,
        })
    return prefix, plan, errors, warnings


def validate_targets(plan):
    errors = []
    seen = {}
    for item in plan:
        target = item["target"]
        previous = seen.get(target)
        if previous is not None:
            errors.append(f"detail-plan-collision:{previous}={item['title']}:{target}")
        seen[target] = item["title"]
        detail = item["detail"]
        if detail is None:
            continue
        component = symlink_component(target)
        if component is not None:
            errors.append(f"detail-target-symlink:{component}")
            continue
        if target.exists() and target.read_text(encoding="utf-8") != "".join(detail):
            errors.append(f"detail-collision:{target}")
    return errors


def write_temp(directory, data, prefix):
    safe_directory = ensure_no_symlink(directory, "temporary-directory")
    handle = tempfile.NamedTemporaryFile(mode="wb", dir=safe_directory, prefix=prefix, delete=False)
    path = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    return path


def build_output(prefix, plan):
    return "".join(prefix + [line for item in plan for line in item["main"]])


def apply_plan(active, details_dir, output, plan):
    ensure_no_symlink(active, "active")
    root = details_root(details_dir)
    for item in plan:
        ensure_no_symlink(item["target"], "detail-target")
    staging_parent = ensure_no_symlink(root.parent, "temporary-directory")
    root_existed = root.exists()
    root.mkdir(parents=True, exist_ok=True)
    original = active.read_bytes()
    if original.decode("utf-8") == output and all(item["detail"] is None or item["target"].is_file() for item in plan):
        return
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.migration-", dir=str(staging_parent)))
    staged = []
    created = []
    active_temp = None
    active_replaced = False
    try:
        for item in plan:
            detail = item["detail"]
            if detail is None or item["target"].exists():
                continue
            staged_path = write_temp(staging, "".join(detail).encode("utf-8"), ".detail-")
            staged.append((staged_path, item["target"]))
        active_temp = write_temp(active.parent, output.encode("utf-8"), f".{active.name}.migration-")
        for staged_path, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(f"detail-race:{target}")
            os.replace(staged_path, target)
            created.append(target)
        os.replace(active_temp, active)
        active_temp = None
        active_replaced = True
    except Exception as error:
        rollback_error = None
        cleanup_errors = []
        if active_replaced:
            try:
                rollback = write_temp(active.parent, original, f".{active.name}.rollback-")
                os.replace(rollback, active)
            except Exception as restore_error:
                rollback_error = restore_error
        for target in created:
            try:
                if target.exists() and not target.is_symlink():
                    target.unlink()
            except OSError as cleanup_error:
                cleanup_errors.append(f"{target}: {cleanup_error}")
        if not root_existed:
            try:
                if root.exists() and not any(root.iterdir()):
                    root.rmdir()
            except OSError as cleanup_error:
                cleanup_errors.append(f"{root}: {cleanup_error}")
        if rollback_error is not None or cleanup_errors:
            details = []
            if rollback_error is not None:
                details.append(f"restore={rollback_error}")
            if cleanup_errors:
                details.append(f"cleanup={'; '.join(cleanup_errors)}")
            raise RuntimeError(
                f"rollback-incomplete: {'; '.join(details)}; original={type(error).__name__}: {error}"
            ) from error
        raise
    finally:
        if active_temp is not None and active_temp.exists():
            active_temp.unlink()
        shutil.rmtree(staging, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--active",
        type=Path,
        default=Path("~/Desktop/projects/.claude/trials/active.md").expanduser(),
    )
    parser.add_argument(
        "--details-dir",
        type=Path,
        default=Path("~/Desktop/projects/.claude/trials/active").expanduser(),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    active = args.active.expanduser()
    details_dir = args.details_dir.expanduser()
    try:
        ensure_no_symlink(active, "active")
        details_root(details_dir)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if not active.is_file():
        print(f"active-missing:{active}", file=sys.stderr)
        return 1
    try:
        prefix, plan, errors, warnings = build_plan(active, details_dir)
        errors.extend(validate_targets(plan))
    except (OSError, UnicodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    if errors:
        return 1
    output = build_output(prefix, plan)
    print(f"entries={len(plan)} apply={str(args.apply).lower()}")
    for warning in warnings:
        print(f"WARNING {warning}")
    for item in plan:
        pointer = item.get("pointer")
        if pointer:
            print(f"PLAN {item['title']} -> {pointer}")
        else:
            print(f"CHECK {item['title']} -> existing detail")
    if args.apply:
        try:
            apply_plan(active, details_dir, output, plan)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            print(f"apply-failed:{error}", file=sys.stderr)
            return 1
        print(f"APPLIED active={active} details={details_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
