#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_IGNORE_FILE = "~/.claude/state/ledger-bootstrap-ignore.txt"
DEFAULT_MARKER_ROOT = "/tmp/"
SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
REMINDER_PREFIX = "此 repo 尚未建立 docs/owner/STATE.md。請執行 /init-project-docs 建立骨架；若不納管，執行 /ledger-ignore。"
LEDGER_POINTER = "## 帳本生命週期\n\n> 帳本生命週期：規則見 `~/.claude/references/ledger-lifecycle.md`；門檻以 `~/.claude/scripts/ledger-lifecycle/registry.json` 為準。"
STATE_TEMPLATE = """---
current_change: none
status: planning
next_action: 填入下一個明確動作
last_session: YYYY-MM-DD
---

## Current Position
Branch: <branch>

## Recent Decisions

## Blockers
- none

## Resume Notes
下次開 session 先讀此檔，補上目前位置與下一步。
"""
LOG_HEADERS = {
    "factcheck-log.md": "# Factcheck Log\n\n> 記錄可回溯的事實查核。\n",
    "proofread-log.md": "# Proofread Log\n\n> 記錄編輯、語氣與結構修正。\n",
    "syndication-log.md": "# Syndication Log\n\n> 記錄跨平台發布與 canonical 查核。\n",
    "friction-log.md": "# Friction Log\n\n> 記錄工作流摩擦與後續處理。\n",
}


def configured_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


def canonical_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(metadata.st_mode):
            return True
    return False


def safe_path_under(root: Path, candidate: str | Path, reject_symlinks: bool = True) -> Path:
    canonical_root = canonical_path(root)
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        raise ValueError("absolute path required")
    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(canonical_root)
    except ValueError as error:
        raise ValueError("path escapes configured root") from error
    current = path.anchor and Path(path.anchor)
    if current is None:
        raise ValueError("absolute path required")
    for index, part in enumerate(path.parts[1:]):
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        except OSError as error:
            raise ValueError("configured path cannot be inspected") from error
        if stat.S_ISLNK(metadata.st_mode):
            if reject_symlinks:
                raise ValueError("configured path contains a symlink")
            resolved_current = current.resolve(strict=False)
            try:
                resolved_current.relative_to(canonical_root)
            except ValueError:
                try:
                    canonical_root.relative_to(resolved_current)
                except ValueError as error:
                    raise ValueError("configured path symlink escapes configured root") from error
        elif index < len(path.parts) - 2 and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("configured path contains a non-directory component")
    return path


def safe_repo_path(root: Path, relative: str | Path) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("repo-relative path required")
    return safe_path_under(root, root.joinpath(relative_path))


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("GIT_"):
            environment.pop(key)
    return environment


def repo_root(cwd: str | Path) -> Path | None:
    target = canonical_path(cwd)
    try:
        result = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            env=git_environment(),
        )
    except OSError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    root = canonical_path(result.stdout.strip())
    if not root.is_dir():
        return None
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return root


def allowed_repo(root: Path) -> bool:
    home = canonical_path(Path.home())
    for relative in ("Desktop/work", "Desktop/projects"):
        base = canonical_path(home / relative)
        if root != base:
            try:
                root.relative_to(base)
            except ValueError:
                continue
            return True
    return False


def parse_ignore_file(path: Path) -> list[Path]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        raise
    paths: list[Path] = []
    seen: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line)
        if not candidate.is_absolute():
            continue
        canonical = canonical_path(candidate)
        key = str(canonical)
        if key in seen:
            continue
        seen.add(key)
        paths.append(canonical)
    return paths


def validated_ignore_file(path: str | Path | None = None) -> Path:
    candidate = Path(path).expanduser() if path is not None else configured_path(
        "LEDGER_BOOTSTRAP_IGNORE_FILE", DEFAULT_IGNORE_FILE
    )
    return safe_path_under(Path.home() / ".claude", candidate, reject_symlinks=False)


def ignore_file() -> Path:
    return validated_ignore_file()


def open_lock(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode):
            raise OSError("unsafe ignore lock")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def ignore_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    descriptor = open_lock(lock_path)
    try:
        with os.fdopen(descriptor, "a+") as handle:
            descriptor = -1
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def is_ignored(root: Path, path: Path | None = None) -> bool:
    ignore_path = validated_ignore_file(path)
    with ignore_file_lock(ignore_path):
        return str(root) in {str(item) for item in parse_ignore_file(ignore_path)}


def write_ignore_file(path: Path, paths: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{item}\n" for item in paths)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path.exists():
            temporary_path.unlink()


def add_ignore(target: str | Path, path: Path | None = None) -> Path:
    root = repo_root(target)
    if root is None:
        raise ValueError("target is not a git repo")
    if not allowed_repo(root):
        raise ValueError("repo is outside the bootstrap scope")
    ignore_path = validated_ignore_file(path)
    with ignore_file_lock(ignore_path):
        entries = parse_ignore_file(ignore_path)
        if root not in entries:
            entries.append(root)
        write_ignore_file(ignore_path, entries)
    return root


def git_path(root: Path, relative: str) -> Path:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-path", relative],
        capture_output=True,
        text=True,
        check=False,
        env=git_environment(),
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise OSError("git info path is unavailable")
    path = Path(result.stdout.strip())
    raw_path = path if path.is_absolute() else root / path
    if has_symlink_component(raw_path):
        raise OSError("git info path contains a symlink")
    return canonical_path(raw_path)


def validated_marker_root() -> Path:
    raw_path = configured_path("LEDGER_BOOTSTRAP_MARKER_ROOT", DEFAULT_MARKER_ROOT)
    if ".." in raw_path.parts:
        raise ValueError("marker root cannot contain parent traversal")
    if raw_path.parts[:2] == (raw_path.anchor, "tmp"):
        raw_path = canonical_path(Path("/tmp")).joinpath(*raw_path.parts[2:])
    elif raw_path.parts[:2] == (raw_path.anchor, "var"):
        raw_path = canonical_path(Path("/var")).joinpath(*raw_path.parts[2:])
    if has_symlink_component(raw_path):
        raise ValueError("marker root contains a symlink")
    return raw_path


def read_text_if_exists(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def append_line_content(content: str | None, line: str) -> tuple[str, bool]:
    value = content or ""
    if line in value.splitlines():
        return value, False
    prefix = value if not value or value.endswith("\n") else f"{value}\n"
    return f"{prefix}{line}\n", True


def append_block_content(content: str | None, block: str) -> tuple[str, bool]:
    value = content or ""
    if block in value:
        return value, False
    if value and not value.endswith("\n"):
        value += "\n"
    if value:
        value += "\n"
    return f"{value}{block}\n", True


def atomic_write_bytes(path: Path, payload: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path.exists():
            temporary_path.unlink()


def atomic_write_text(path: Path, content: str, mode: int = 0o644) -> None:
    atomic_write_bytes(path, content.encode("utf-8"), mode)


def missing_parent_directories(plans: list[tuple[Path, str]]) -> list[Path]:
    missing: dict[str, Path] = {}
    for path, _ in plans:
        current = path.parent
        while not current.exists():
            missing[str(current)] = current
            parent = current.parent
            if parent == current:
                break
            current = parent
    return sorted(missing.values(), key=lambda path: len(path.parts), reverse=True)


def apply_writes(plans: list[tuple[Path, str]]) -> None:
    snapshots: list[tuple[Path, bytes | None, int]] = []
    for path, _ in plans:
        if path.is_symlink():
            raise ValueError("write target is a symlink")
        if path.exists():
            metadata = path.stat()
            snapshots.append((path, path.read_bytes(), stat.S_IMODE(metadata.st_mode)))
        else:
            snapshots.append((path, None, 0o644))
    created_directories = missing_parent_directories(plans)
    try:
        for path, content in plans:
            mode = next(mode for snapshot_path, _, mode in snapshots if snapshot_path == path)
            atomic_write_text(path, content, mode)
    except Exception:
        for path, original, mode in reversed(snapshots):
            if original is None:
                if path.exists() or path.is_symlink():
                    path.unlink()
            else:
                atomic_write_bytes(path, original, mode)
        for directory in created_directories:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def init_project_docs(target: str | Path) -> dict[str, Any]:
    root = repo_root(target)
    if root is None:
        raise ValueError("target is not a git repo")
    if not allowed_repo(root):
        raise ValueError("repo is outside the bootstrap scope")
    state_path = safe_repo_path(root, Path("docs/owner/STATE.md"))
    if state_path.exists():
        raise ValueError("docs/owner/STATE.md already exists")
    log_paths = [(safe_repo_path(root, Path("docs/owner") / name), header) for name, header in LOG_HEADERS.items()]
    claude_path = safe_repo_path(root, "CLAUDE.md")
    exclude_path = git_path(root, "info/exclude")
    exclude_content, exclude_changed = append_line_content(
        read_text_if_exists(exclude_path), "docs/owner/"
    )
    claude_content, claude_changed = append_block_content(
        read_text_if_exists(claude_path), LEDGER_POINTER
    )
    plans: list[tuple[Path, str]] = [(state_path, STATE_TEMPLATE)]
    created = [str(state_path)]
    for path, header in log_paths:
        if path.exists():
            if not path.is_file():
                raise ValueError(f"ledger path is not a regular file: {path}")
            continue
        plans.append((path, header))
        created.append(str(path))
    if exclude_changed:
        plans.append((exclude_path, exclude_content))
    if claude_changed:
        plans.append((claude_path, claude_content))
    apply_writes(plans)
    return {
        "repo": str(root),
        "created": created,
        "exclude_updated": exclude_changed,
        "claude_updated": claude_changed,
    }


def gc_markers(marker_root: Path) -> None:
    marker_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "find",
            f"{marker_root}/",
            "-maxdepth",
            "1",
            "-name",
            "ledger-bootstrap-session-*",
            "-type",
            "f",
            "-mtime",
            "+1",
            "-delete",
        ],
        capture_output=True,
        check=False,
    )


def session_payload(payload: Any) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    event = payload.get("hook_event_name")
    if event is not None and event != "SessionStart":
        return None
    source = payload.get("source")
    if source is not None and source not in {"startup", "resume", "clear", "compact"}:
        return None
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
        return None
    if not isinstance(cwd, str) or not cwd:
        return None
    return {"session_id": session_id, "cwd": cwd}


def session_output(payload: Any) -> str:
    values = session_payload(payload)
    if values is None:
        return ""
    root = repo_root(values["cwd"])
    if root is None or not allowed_repo(root):
        return ""
    try:
        state_path = safe_repo_path(root, Path("docs/owner/STATE.md"))
    except ValueError:
        return ""
    if state_path.is_file():
        return ""
    try:
        if is_ignored(root):
            return ""
    except OSError:
        return ""
    try:
        marker_root = validated_marker_root()
        gc_markers(marker_root)
    except (OSError, ValueError):
        return ""
    marker = marker_root / f"ledger-bootstrap-session-{values['session_id']}"
    if marker.is_symlink() or marker.exists():
        return ""
    try:
        marker.touch(exist_ok=False)
    except (FileExistsError, OSError):
        return ""
    message = f"{REMINDER_PREFIX} repo: {root} session: {values['session_id']}"
    return json.dumps({"systemMessage": message}, ensure_ascii=False)


def print_repo_root(target: str) -> int:
    root = repo_root(target)
    if root is None:
        return 1
    print(root)
    return 0


def run_is_ignored(target: str, path: Path | None) -> int:
    root = repo_root(target)
    if root is None:
        return 1
    try:
        ignored = is_ignored(root, path)
    except OSError:
        return 2
    print("true" if ignored else "false")
    return 0 if ignored else 1


def run_add_ignore(target: str, path: Path | None) -> int:
    try:
        print(add_ignore(target, path))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


def run_init_project_docs(target: str) -> int:
    try:
        print(json.dumps(init_project_docs(target), ensure_ascii=False))
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "session":
        try:
            payload = json.load(sys.stdin)
        except (OSError, ValueError):
            return 0
        output = session_output(payload)
        if output:
            print(output)
        return 0
    if len(argv) == 3 and argv[1] == "repo-root":
        return print_repo_root(argv[2])
    if len(argv) == 3 and argv[1] == "init-project-docs":
        return run_init_project_docs(argv[2])
    if len(argv) in (3, 5) and argv[1] == "is-ignored":
        path = Path(argv[4]).expanduser() if len(argv) == 5 and argv[3] == "--ignore-file" else None
        if len(argv) == 5 and path is None:
            return 2
        return run_is_ignored(argv[2], path)
    if len(argv) in (3, 5) and argv[1] == "add-ignore":
        path = Path(argv[4]).expanduser() if len(argv) == 5 and argv[3] == "--ignore-file" else None
        if len(argv) == 5 and path is None:
            return 2
        return run_add_ignore(argv[2], path)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
