import os
from pathlib import Path


def _uncollapsed_abs_path(path):
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty-path")
    expanded = os.path.expanduser(raw)
    if expanded.startswith("//"):
        expanded = "/" + expanded.lstrip("/")
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
        expanded = os.fspath(candidate)
        if expanded.startswith("//"):
            expanded = "/" + expanded.lstrip("/")
        candidate = Path(expanded)
    return candidate


def is_system_alias(current):
    return (
        (current == Path("/tmp") and os.path.realpath("/tmp") == "/private/tmp")
        or (current == Path("/var") and os.path.realpath("/var") == "/private/var")
    )


def absolute_lexical_path(path):
    return Path(os.path.abspath(os.fspath(_uncollapsed_abs_path(path))))


def symlink_component(path):
    candidate = _uncollapsed_abs_path(path)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        if part == ".":
            continue
        if part == "..":
            current = current.parent
            continue
        current = current / part
        if is_system_alias(current):
            continue
        if current.is_symlink():
            return current
    return None


def ensure_no_symlink(path, label):
    component = symlink_component(path)
    if component is not None:
        raise ValueError(f"{label}-symlink:{component}")
    return absolute_lexical_path(path)
