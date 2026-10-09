#!/usr/bin/env python3

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path


class AuditInputError(Exception):
    pass


def load_validator():
    validator_path = Path(__file__).resolve().parent.parent / "skills" / "skill-creator" / "scripts" / "quick_validate.py"
    spec = importlib.util.spec_from_file_location("skill_quick_validate", validator_path)
    if spec is None or spec.loader is None:
        raise AuditInputError(f"validator not loadable: {validator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_skill


def inventory_paths(inventory):
    parser_path = Path(__file__).resolve().parent / "skill-inventory-paths.sh"
    result = subprocess.run(
        ["bash", str(parser_path), "--paths", str(inventory)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or "inventory parser failed"
        raise AuditInputError(message)

    raw_paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not raw_paths:
        raise AuditInputError("inventory produced zero audit-eligible paths")

    paths = [Path(path) for path in raw_paths]
    for path in paths:
        if ".." in path.parts:
            raise AuditInputError("inventory parser produced path traversal")
        if not path.is_absolute() or path.name != "SKILL.md":
            raise AuditInputError("inventory parser produced a non-canonical skill path")

    normalized_paths = [path.resolve() for path in paths]
    if len(set(normalized_paths)) != len(normalized_paths):
        raise AuditInputError("inventory parser produced normalized duplicate skill paths")
    return sorted(paths, key=str)


def escape_tsv(value):
    return str(value).replace('\\', '\\\\').replace('\t', '\\t').replace('\r', '\\r').replace('\n', '\\n')


def build_parser():
    parser = argparse.ArgumentParser(description="Audit inventory-eligible skills")
    parser.add_argument("inventory_path", nargs="?", type=Path)
    parser.add_argument("--inventory", dest="inventory_option", type=Path)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.inventory_path is not None and args.inventory_option is not None:
        print("ERROR\tuse either a positional inventory path or --inventory", file=sys.stderr)
        return 2
    inventory = args.inventory_option or args.inventory_path or Path.home() / ".claude" / "skills" / "INVENTORY.md"
    try:
        paths = inventory_paths(inventory)
        validate_skill = load_validator()
    except (AuditInputError, OSError, ImportError) as error:
        print("SUMMARY\ttotal=0\tpass=0\tfail=0")
        print(f"ERROR\t{error}", file=sys.stderr)
        return 2

    passed = 0
    failed = 0
    for skill_md in paths:
        try:
            valid, message = validate_skill(skill_md.parent)
        except Exception as error:
            valid = False
            message = f"Validator exception: {type(error).__name__}: {error}"
        status = "PASS" if valid else "FAIL"
        if valid:
            passed += 1
        else:
            failed += 1
        print(f"RESULT\t{status}\t{skill_md}\t{escape_tsv(message)}")

    print(f"SUMMARY\ttotal={len(paths)}\tpass={passed}\tfail={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
