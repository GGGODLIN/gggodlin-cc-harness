#!/usr/bin/env python3
"""Build a 3-way diff review bundle for conflicted files in a merge commit or staged merge."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


LOCKFILE_NAMES = frozenset({
  "bun.lock",
  "bun.lockb",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
  "Cargo.lock",
  "uv.lock",
  "poetry.lock",
})

MANIFEST_NAMES = frozenset({
  "package.json",
  "herdr-plugin.toml",
  "Cargo.toml",
  "pyproject.toml",
})

CONFLICT_MARKER_RE = re.compile(r"^(?:<<<<<<<|=======|>>>>>>>)(?:\s|$)", re.MULTILINE)


def run_git_bytes(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
  result = subprocess.run(
    ["git", "-C", str(repo), *args],
    capture_output=True,
    check=False,
  )
  if check and result.returncode != 0:
    err = result.stderr.decode("utf-8", errors="replace").strip()
    out = result.stdout.decode("utf-8", errors="replace").strip()
    raise RuntimeError(err or out or f"git {' '.join(args)} failed")
  return result


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
  raw = run_git_bytes(repo, args, check=check)
  return subprocess.CompletedProcess(
    args=raw.args,
    returncode=raw.returncode,
    stdout=raw.stdout.decode("utf-8", errors="replace"),
    stderr=raw.stderr.decode("utf-8", errors="replace"),
  )


def find_repo_root(start: Path) -> Path:
  res = run_git(start, ["rev-parse", "--show-toplevel"])
  return Path(res.stdout.strip()).resolve()


def resolve_merge_endpoints(repo: Path, commit: str | None, staged: bool) -> tuple[str, str, str, str]:
  """Return (base_sha, ours_sha, theirs_sha, result_spec).
  result_spec is a commit SHA or ':0' for the staged index.
  """
  if staged:
    ours = run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    merge_head_path = Path(
      run_git(repo, ["rev-parse", "--path-format=absolute", "--git-path", "MERGE_HEAD"]).stdout.strip()
    )
    if not merge_head_path.is_file():
      raise RuntimeError("no in-progress merge (MERGE_HEAD not found)")
    merge_heads = [
      line.strip()
      for line in merge_head_path.read_text(encoding="utf-8", errors="replace").splitlines()
      if line.strip()
    ]
    if len(merge_heads) != 1:
      raise RuntimeError(f"staged merge must have exactly 1 MERGE_HEAD parent (found {len(merge_heads)})")
    theirs = run_git(repo, ["rev-parse", "--verify", f"{merge_heads[0]}^{{commit}}"]).stdout.strip()
    unmerged = run_git(repo, ["diff", "--name-only", "--diff-filter=U"]).stdout.strip()
    if unmerged:
      raise RuntimeError(f"unresolved conflicts remain in index: {', '.join(unmerged.splitlines())}")
    base = run_git(repo, ["merge-base", ours, theirs]).stdout.strip()
    return base, ours, theirs, ":0"

  target = commit or "HEAD"
  parents_raw = run_git(repo, ["rev-list", "--parents", "-n", "1", target]).stdout.strip().split()
  if len(parents_raw) != 3:
    raise RuntimeError(f"{target} must be a two-parent merge commit (found {len(parents_raw) - 1} parent(s))")
  res_sha, ours, theirs = parents_raw[0], parents_raw[1], parents_raw[2]
  base = run_git(repo, ["merge-base", ours, theirs]).stdout.strip()
  return base, ours, theirs, res_sha


def compute_conflicted_paths(repo: Path, ours: str, theirs: str) -> list[str]:
  res = run_git_bytes(
    repo,
    ["-c", "core.quotepath=false", "merge-tree", "--write-tree", "--name-only", "-z", ours, theirs],
    check=False,
  )
  if res.returncode not in (0, 1):
    err = res.stderr.decode("utf-8", errors="replace").strip()
    out = res.stdout.decode("utf-8", errors="replace").strip()
    raise RuntimeError(err or out or f"git merge-tree failed with exit code {res.returncode}")

  tokens = res.stdout.split(b"\x00")
  if len(tokens) < 2:
    if res.returncode == 1:
      raise RuntimeError("git merge-tree exited 1 without tree/conflict details")
    return []

  paths: list[str] = []
  msg_idx = len(tokens)
  for idx, tok in enumerate(tokens[1:], start=1):
    if tok == b"":
      msg_idx = idx + 1
      break
    paths.append(tok.decode("utf-8", errors="replace"))

  if res.returncode == 1 and not paths:
    msgs = [t.decode("utf-8", errors="replace").strip() for t in tokens[msg_idx:] if t]
    detail = "; ".join(msgs) or res.stderr.decode("utf-8", errors="replace").strip() or "pathless conflict"
    raise RuntimeError(f"git merge-tree reported conflict without conflicted file paths: {detail}")

  return sorted(set(paths))


def diff_for_path(repo: Path, left: str, right: str, path: str) -> str:
  if right == ":0":
    return run_git(repo, ["-c", "core.quotepath=false", "diff", "--cached", left, "--", path]).stdout
  return run_git(repo, ["-c", "core.quotepath=false", "diff", left, right, "--", path]).stdout


def read_blob_text(repo: Path, rev_or_index: str, path: str) -> str | None:
  spec = f":0:{path}" if rev_or_index == ":0" else f"{rev_or_index}:{path}"
  res = run_git_bytes(repo, ["show", spec], check=False)
  if res.returncode != 0:
    return None
  if b"\x00" in res.stdout:
    return None
  return res.stdout.decode("utf-8", errors="replace")


def iter_hunk_lines(diff_text: str) -> list[tuple[str, str]]:
  items: list[tuple[str, str]] = []
  in_hunk = False
  for line in diff_text.splitlines():
    if line.startswith("@@ "):
      in_hunk = True
      continue
    if line.startswith("diff --git "):
      in_hunk = False
      continue
    if not in_hunk:
      continue
    if line.startswith(("+", "-")):
      items.append((line[0], line[1:]))
  return items


def extract_changed_body_lines(diff_text: str) -> list[str]:
  changed = [content.strip() for _, content in iter_hunk_lines(diff_text)]
  return [c for c in changed if c]


def _only_package_version_changed(name: str, base_text: str | None, side_text: str | None) -> bool:
  if base_text is None or side_text is None:
    return False
  try:
    if name == "package.json":
      base_obj = json.loads(base_text)
      side_obj = json.loads(side_text)
      if not isinstance(base_obj, dict) or not isinstance(side_obj, dict):
        return False
      if not isinstance(base_obj.get("version"), str) or not isinstance(side_obj.get("version"), str):
        return False
      if base_obj.get("version") == side_obj.get("version"):
        return False
      b_rest = {k: v for k, v in base_obj.items() if k != "version"}
      s_rest = {k: v for k, v in side_obj.items() if k != "version"}
      return b_rest == s_rest

    base_toml = tomllib.loads(base_text)
    side_toml = tomllib.loads(side_text)
    if not isinstance(base_toml, dict) or not isinstance(side_toml, dict):
      return False

    candidate_paths: list[tuple[str, ...]] = []
    if name == "Cargo.toml":
      candidate_paths = [("package", "version")]
    elif name == "pyproject.toml":
      candidate_paths = [("project", "version"), ("tool", "poetry", "version")]
    elif name == "herdr-plugin.toml":
      candidate_paths = [("version",), ("plugin", "version")]

    for key_path in candidate_paths:
      b_cur: object = base_toml
      s_cur: object = side_toml
      found = True
      for key in key_path[:-1]:
        if isinstance(b_cur, dict) and isinstance(s_cur, dict) and key in b_cur and key in s_cur:
          b_cur = b_cur[key]
          s_cur = s_cur[key]
        else:
          found = False
          break
      leaf = key_path[-1]
      if not found or not isinstance(b_cur, dict) or not isinstance(s_cur, dict):
        continue
      b_ver = b_cur.get(leaf)
      s_ver = s_cur.get(leaf)
      if isinstance(b_ver, str) and isinstance(s_ver, str) and b_ver != s_ver:
        b_copy = copy.deepcopy(base_toml)
        s_copy = copy.deepcopy(side_toml)
        bt = b_copy
        st = s_copy
        for key in key_path[:-1]:
          bt = bt[key]
          st = st[key]
        del bt[leaf]
        del st[leaf]
        if b_copy == s_copy:
          return True
    return False
  except (ValueError, tomllib.TOMLDecodeError, KeyError, TypeError):
    return False


def check_mechanical_manifest(
  path: str,
  d_ours: str,
  d_theirs: str,
  ours_text: str | None,
  theirs_text: str | None,
  res_text: str | None,
  base_text: str | None = None,
) -> tuple[bool, str]:
  """Only exempt a manifest when one side's change since base is purely the version line
  and the merged result matches the other side byte-for-byte."""
  name = Path(path).name
  if name not in MANIFEST_NAMES:
    return False, "not a manifest"

  ver_re = (
    re.compile(r'^"version"\s*:\s*"[^"]+",?$')
    if name.endswith(".json")
    else re.compile(r'^version\s*=\s*"[^"]+"$')
  )

  theirs_lines = extract_changed_body_lines(d_theirs)
  ours_lines = extract_changed_body_lines(d_ours)

  if (
    theirs_lines
    and all(ver_re.match(line) for line in theirs_lines)
    and _only_package_version_changed(name, base_text, theirs_text)
    and ours_text is not None
    and res_text == ours_text
  ):
    return True, "theirs changed only version; result preserves ours byte-for-byte"
  if (
    ours_lines
    and all(ver_re.match(line) for line in ours_lines)
    and _only_package_version_changed(name, base_text, ours_text)
    and theirs_text is not None
    and res_text == theirs_text
  ):
    return True, "ours changed only version; result takes theirs byte-for-byte"
  return False, f"non-version changes present in {path}"


KV_LINE_RE = re.compile(r'^\s*"([^"]+)"\s*:\s*(.+?)\s*,?\s*$')
CHANGELOG_LEAD_RE = re.compile(r"^- \*\*([^*]+)\*\*")


def parse_kv_dictionary(text: str) -> dict[str, str] | None:
  entries: dict[str, str] = {}
  for line in text.splitlines():
    m = KV_LINE_RE.match(line)
    if m:
      key = m.group(1)
      if key in entries:
        return None
      entries[key] = m.group(2)
  return entries if len(entries) >= 10 else None


def _non_kv_lines(text: str) -> list[str]:
  return [line for line in text.splitlines() if line.strip() and not KV_LINE_RE.match(line)]


def check_mechanical_dictionary(
  path: str,
  base_text: str | None,
  ours_text: str | None,
  theirs_text: str | None,
  res_text: str | None,
) -> tuple[bool, str]:
  """Verify a translation dictionary by 3-way key-value equivalence:
  every key added by either side is present with its exact value, no key was deleted,
  no existing key was modified by both sides, and every single-side modification kept that side's value."""
  if Path(path).name in MANIFEST_NAMES:
    return False, "manifest files are not translation dictionaries"
  if not (base_text and ours_text and theirs_text and res_text):
    return False, "dictionary text unavailable"
  for txt in (base_text, ours_text, theirs_text, res_text):
    if CONFLICT_MARKER_RE.search(txt):
      return False, "conflict markers present in dictionary"
  if path.endswith(".json"):
    try:
      json.loads(res_text)
    except json.JSONDecodeError:
      return False, "invalid JSON syntax in dictionary result"
  non_kv_base = _non_kv_lines(base_text)
  if (
    _non_kv_lines(ours_text) != non_kv_base
    or _non_kv_lines(theirs_text) != non_kv_base
    or _non_kv_lines(res_text) != non_kv_base
  ):
    return False, "non-KV lines differ in dictionary"
  b_map = parse_kv_dictionary(base_text)
  o_map = parse_kv_dictionary(ours_text)
  t_map = parse_kv_dictionary(theirs_text)
  r_map = parse_kv_dictionary(res_text)
  if not (b_map and o_map and t_map and r_map):
    return False, "not a unique-key key-value dictionary"

  all_keys = set(b_map) | set(o_map) | set(t_map) | set(r_map)
  ours_added = 0
  theirs_added = 0
  single_updated = 0
  for k in all_keys:
    b_val = b_map.get(k)
    o_val = o_map.get(k)
    t_val = t_map.get(k)
    r_val = r_map.get(k)
    if r_val is None:
      return False, f"key '{k}' missing in result"
    if b_val is None:
      if o_val is not None and t_val is not None and o_val != t_val:
        return False, f"key '{k}' added by both sides with different values"
      expected = o_val if o_val is not None else t_val
      if r_val != expected:
        return False, f"added key '{k}' value altered in result"
      if o_val is not None:
        ours_added += 1
      if t_val is not None:
        theirs_added += 1
    else:
      if o_val is None or t_val is None:
        return False, f"key '{k}' deleted on one side"
      o_changed = o_val != b_val
      t_changed = t_val != b_val
      if o_changed and t_changed and o_val != t_val:
        return False, f"key '{k}' modified by both sides differently"
      expected = o_val if o_changed else (t_val if t_changed else b_val)
      if r_val != expected:
        return False, f"key '{k}' in result does not match expected 3-way value"
      if o_changed or t_changed:
        single_updated += 1

  return (
    True,
    f"dictionary verified: +{ours_added} ours keys, +{theirs_added} theirs keys, {single_updated} single-side updates, 0 collisions",
  )


def check_mechanical_changelog(
  path: str,
  d_theirs: str,
  d_ours_to_res: str,
  res_text: str | None = None,
) -> tuple[bool, str]:
  """Verify CHANGELOG.md when theirs only added new bullets since base, and result only
  appended those exact bold-lead bullets onto ours without deleting any line from ours."""
  if Path(path).name != "CHANGELOG.md":
    return False, "not CHANGELOG.md"
  if res_text is not None and CONFLICT_MARKER_RE.search(res_text):
    return False, "conflict markers present in CHANGELOG.md"

  theirs_bullets: list[str] = []
  for op, content in iter_hunk_lines(d_theirs):
    if CONFLICT_MARKER_RE.match(content):
      return False, "conflict markers present in theirs diff"
    stripped = content.strip()
    if not stripped:
      continue
    if op == "-":
      if CHANGELOG_LEAD_RE.match(content):
        return False, "theirs deletes or rewrites an existing bold-lead bullet"
      if not content.lstrip().startswith("#"):
        return False, "theirs deletes non-heading content from CHANGELOG.md"
    elif op == "+":
      if content.lstrip().startswith("#"):
        continue
      if CHANGELOG_LEAD_RE.match(content):
        theirs_bullets.append(stripped)
      else:
        return False, "theirs adds non-bold-lead content to CHANGELOG.md"

  if not theirs_bullets:
    return False, "theirs added no bold-lead bullets"

  added_to_ours_bullets: list[str] = []
  for op, content in iter_hunk_lines(d_ours_to_res):
    if op == "+" and CONFLICT_MARKER_RE.match(content):
      return False, "result introduces conflict markers"
    stripped = content.strip()
    if not stripped:
      continue
    if op == "-":
      return False, "result deletes lines that were in ours CHANGELOG.md"
    if op == "+":
      if CHANGELOG_LEAD_RE.match(content):
        added_to_ours_bullets.append(stripped)
      else:
        return False, "result adds non-bold-lead content onto ours CHANGELOG.md"

  if sorted(theirs_bullets) != sorted(added_to_ours_bullets):
    return (
      False,
      f"changelog bullet mismatch: theirs_added={len(theirs_bullets)}, result_added={len(added_to_ours_bullets)}",
    )
  return (
    True,
    f"changelog verified: +{len(theirs_bullets)} theirs bold-lead bullets cleanly added onto ours, 0 deletions",
  )


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Build a 3-way diff bundle for conflicted files in a merge commit or staged merge."
  )
  parser.add_argument("--repo", default=".", help="Path inside the target repository.")
  parser.add_argument("--commit", help="Merge commit to inspect (default: HEAD when not --staged).")
  parser.add_argument(
    "--staged",
    action="store_true",
    help="Inspect a resolved in-progress merge in the index (HEAD + MERGE_HEAD) before committing.",
  )
  parser.add_argument("--out", required=True, help="Output file path for the 3-way diff bundle.")
  parser.add_argument("--json", action="store_true", help="Print summary as JSON.")
  args = parser.parse_args()

  if args.commit and args.staged:
    parser.error("--commit and --staged are mutually exclusive")

  try:
    repo = find_repo_root(Path(args.repo).resolve())
    base, ours, theirs, result_spec = resolve_merge_endpoints(repo, args.commit, args.staged)
    conflicted = compute_conflicted_paths(repo, ours, theirs)
  except RuntimeError as err:
    print(f"error: {err}", file=sys.stderr)
    return 2

  mechanical: list[dict[str, str]] = []
  review_files: list[str] = []
  bundle_chunks: list[str] = []

  short_base = base[:8]
  short_ours = ours[:8]
  short_theirs = theirs[:8]
  short_res = "STAGED" if result_spec == ":0" else result_spec[:8]

  for path in conflicted:
    name = Path(path).name
    if name in LOCKFILE_NAMES:
      mechanical.append({"path": path, "reason": "lockfile (verify via package manager / build)"})
      continue

    d_ours = diff_for_path(repo, base, ours, path)
    d_theirs = diff_for_path(repo, base, theirs, path)
    d_res = diff_for_path(repo, base, result_spec, path)

    base_text = read_blob_text(repo, base, path)
    ours_text = read_blob_text(repo, ours, path)
    theirs_text = read_blob_text(repo, theirs, path)
    res_text = read_blob_text(repo, result_spec, path)

    if name in MANIFEST_NAMES:
      is_mech, reason = check_mechanical_manifest(
        path, d_ours, d_theirs, ours_text, theirs_text, res_text, base_text=base_text
      )
      if is_mech:
        mechanical.append({"path": path, "reason": reason})
        continue
    else:
      d_ours_to_res = diff_for_path(repo, ours, result_spec, path)
      is_cl, cl_reason = check_mechanical_changelog(path, d_theirs, d_ours_to_res, res_text=res_text)
      if is_cl:
        mechanical.append({"path": path, "reason": cl_reason})
        continue

      is_dict, dict_reason = check_mechanical_dictionary(path, base_text, ours_text, theirs_text, res_text)
      if is_dict:
        mechanical.append({"path": path, "reason": dict_reason})
        continue

    review_files.append(path)
    chunk = (
      f"================ FILE: {path} ================\n"
      f"--- 1. base..ours ({short_base}..{short_ours}) ---\n{d_ours}\n"
      f"--- 2. base..theirs ({short_base}..{short_theirs}) ---\n{d_theirs}\n"
      f"--- 3. base..result ({short_base}..{short_res}) ---\n{d_res}\n"
    )
    bundle_chunks.append(chunk)

  raw_out = Path(args.out)
  out_path = raw_out.parent.resolve() / raw_out.name
  bundle_text = "\n".join(bundle_chunks)
  tmp_path: Path | None = None
  try:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
      mode="w",
      encoding="utf-8",
      dir=out_path.parent,
      prefix=f".{out_path.name}.",
      suffix=".tmp",
      delete=False,
    ) as fp:
      tmp_path = Path(fp.name)
      fp.write(bundle_text)
    os.replace(tmp_path, out_path)
    tmp_path = None
  except OSError as err:
    if tmp_path is not None:
      try:
        tmp_path.unlink(missing_ok=True)
      except OSError:
        pass
    print(f"error: failed to write output bundle {out_path}: {err}", file=sys.stderr)
    return 2
  total_lines = bundle_text.count("\n")

  summary = {
    "repo": str(repo),
    "base": short_base,
    "ours": short_ours,
    "theirs": short_theirs,
    "result": short_res,
    "conflicted_total": len(conflicted),
    "mechanical_exempt": mechanical,
    "review_files": review_files,
    "bundle_path": str(out_path),
    "bundle_total_lines": total_lines,
  }

  if args.json:
    print(json.dumps(summary, indent=2))
  else:
    print(f"BUNDLE_PATH={out_path}")
    print(f"BUNDLE_TOTAL_LINES={total_lines}")
    print(f"CONFLICTED_TOTAL={len(conflicted)}")
    print(f"MECHANICAL_EXEMPT_COUNT={len(mechanical)}")
    for item in mechanical:
      print(f"  [mechanical] {item['path']}: {item['reason']}")
    print(f"REVIEW_FILES_COUNT={len(review_files)}")
    for path in review_files:
      print(f"  [review] {path}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
