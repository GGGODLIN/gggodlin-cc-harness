#!/usr/bin/env python3
"""Build a 3-way diff review bundle for conflicted files in a merge commit or staged merge."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
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


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
  result = subprocess.run(
    ["git", "-C", str(repo), *args],
    capture_output=True,
    text=True,
    check=False,
  )
  if check and result.returncode != 0:
    msg = result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed"
    raise RuntimeError(msg)
  return result


def find_repo_root(start: Path) -> Path:
  res = run_git(start, ["rev-parse", "--show-toplevel"])
  return Path(res.stdout.strip()).resolve()


def resolve_merge_endpoints(repo: Path, commit: str | None, staged: bool) -> tuple[str, str, str, str]:
  """Return (base_sha, ours_sha, theirs_sha, result_spec).
  result_spec is a commit SHA or ':0' for the staged index.
  """
  if staged:
    ours = run_git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    theirs = run_git(repo, ["rev-parse", "MERGE_HEAD"]).stdout.strip()
    unmerged = run_git(repo, ["diff", "--name-only", "--diff-filter=U"]).stdout.strip()
    if unmerged:
      raise RuntimeError(f"unresolved conflicts remain in index: {', '.join(unmerged.splitlines())}")
    base = run_git(repo, ["merge-base", ours, theirs]).stdout.strip()
    return base, ours, theirs, ":0"

  target = commit or "HEAD"
  parents_raw = run_git(repo, ["rev-list", "--parents", "-n", "1", target]).stdout.strip().split()
  if len(parents_raw) < 3:
    raise RuntimeError(f"{target} is not a merge commit (found {len(parents_raw) - 1} parent(s))")
  res_sha, ours, theirs = parents_raw[0], parents_raw[1], parents_raw[2]
  base = run_git(repo, ["merge-base", ours, theirs]).stdout.strip()
  return base, ours, theirs, res_sha


def compute_conflicted_paths(repo: Path, ours: str, theirs: str) -> list[str]:
  res = run_git(repo, ["merge-tree", "--write-tree", "--name-only", ours, theirs], check=False)
  lines = res.stdout.splitlines()
  if not lines:
    return []
  paths: list[str] = []
  for line in lines[1:]:
    stripped = line.strip()
    if not stripped:
      break
    if stripped.startswith("Auto-merging ") or stripped.startswith("CONFLICT "):
      continue
    paths.append(stripped)
  return sorted(set(paths))


def diff_for_path(repo: Path, left: str, right: str, path: str) -> str:
  if right == ":0":
    return run_git(repo, ["diff", "--cached", left, "--", path]).stdout
  return run_git(repo, ["diff", left, right, "--", path]).stdout


def read_blob_text(repo: Path, rev_or_index: str, path: str) -> str | None:
  spec = f":{path}" if rev_or_index == ":0" else f"{rev_or_index}:{path}"
  res = run_git(repo, ["show", spec], check=False)
  if res.returncode != 0:
    return None
  return res.stdout


def extract_changed_body_lines(diff_text: str) -> list[str]:
  changed: list[str] = []
  for line in diff_text.splitlines():
    if line.startswith(("+++", "---", "@@", "diff --git", "index ")):
      continue
    if line.startswith(("+", "-")):
      changed.append(line[1:].strip())
  return [c for c in changed if c]


def check_mechanical_manifest(
  path: str,
  d_ours: str,
  d_theirs: str,
  ours_text: str | None,
  theirs_text: str | None,
  res_text: str | None,
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

  if theirs_lines and all(ver_re.match(line) for line in theirs_lines) and ours_text is not None and res_text == ours_text:
    return True, "theirs changed only version; result preserves ours byte-for-byte"
  if ours_lines and all(ver_re.match(line) for line in ours_lines) and theirs_text is not None and res_text == theirs_text:
    return True, "ours changed only version; result takes theirs byte-for-byte"
  return False, f"non-version changes present in {path}"


KV_LINE_RE = re.compile(r'^\s*"([^"]+)"\s*:\s*(.+?)\s*,?\s*$')
CHANGELOG_LEAD_RE = re.compile(r"^- \*\*([^*]+)\*\*")


def parse_kv_dictionary(text: str) -> dict[str, str] | None:
  entries: dict[str, str] = {}
  for line in text.splitlines():
    m = KV_LINE_RE.match(line)
    if m:
      entries[m.group(1)] = m.group(2)
  return entries if len(entries) >= 10 else None


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
  if not (base_text and ours_text and theirs_text and res_text):
    return False, "dictionary text unavailable"
  b_map = parse_kv_dictionary(base_text)
  o_map = parse_kv_dictionary(ours_text)
  t_map = parse_kv_dictionary(theirs_text)
  r_map = parse_kv_dictionary(res_text)
  if not (b_map and o_map and t_map and r_map):
    return False, "not a key-value dictionary"

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
) -> tuple[bool, str]:
  """Verify CHANGELOG.md when theirs only added new bullets since base, and result only
  appended those exact bold-lead bullets onto ours without deleting any line from ours."""
  if Path(path).name != "CHANGELOG.md":
    return False, "not CHANGELOG.md"

  for line in d_theirs.splitlines():
    if line.startswith("---") or line.startswith("+++"):
      continue
    if line.startswith("-") and CHANGELOG_LEAD_RE.match(line[1:]):
      return False, "theirs deletes or rewrites an existing bold-lead bullet"

  for line in d_ours_to_res.splitlines():
    if line.startswith("---") or line.startswith("+++"):
      continue
    if line.startswith("-") and line[1:].strip():
      return False, "result deletes lines that were in ours CHANGELOG.md"

  theirs_leads = [
    CHANGELOG_LEAD_RE.match(line[1:]).group(1)
    for line in d_theirs.splitlines()
    if line.startswith("+") and not line.startswith("+++") and CHANGELOG_LEAD_RE.match(line[1:])
  ]
  added_to_ours_leads = [
    CHANGELOG_LEAD_RE.match(line[1:]).group(1)
    for line in d_ours_to_res.splitlines()
    if line.startswith("+") and not line.startswith("+++") and CHANGELOG_LEAD_RE.match(line[1:])
  ]

  if sorted(theirs_leads) != sorted(added_to_ours_leads):
    return False, f"changelog lead mismatch: theirs_added={len(theirs_leads)}, result_added={len(added_to_ours_leads)}"
  return (
    True,
    f"changelog verified: +{len(theirs_leads)} theirs bold-lead bullets cleanly added onto ours, 0 deletions",
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

    ours_text = read_blob_text(repo, ours, path)
    theirs_text = read_blob_text(repo, theirs, path)
    res_text = read_blob_text(repo, result_spec, path)
    is_mech, reason = check_mechanical_manifest(path, d_ours, d_theirs, ours_text, theirs_text, res_text)
    if is_mech:
      mechanical.append({"path": path, "reason": reason})
      continue

    d_ours_to_res = diff_for_path(repo, ours, result_spec, path)
    is_cl, cl_reason = check_mechanical_changelog(path, d_theirs, d_ours_to_res)
    if is_cl:
      mechanical.append({"path": path, "reason": cl_reason})
      continue

    base_text = read_blob_text(repo, base, path)
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

  out_path = Path(args.out).resolve()
  out_path.parent.mkdir(parents=True, exist_ok=True)
  bundle_text = "\n".join(bundle_chunks)
  out_path.write_text(bundle_text, encoding="utf-8")
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
