import os
from pathlib import Path

TMP_ALIAS = Path("/tmp")


def absolute_lexical_path(path):
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(os.fspath(candidate)))


def symlink_component(path):
    candidate = absolute_lexical_path(path)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current == TMP_ALIAS:
            continue
        if current.is_symlink():
            return current
    return None


def ensure_no_symlink(path, label):
    candidate = absolute_lexical_path(path)
    component = symlink_component(candidate)
    if component is not None:
        raise ValueError(f"{label}-symlink:{component}")
    return candidate
