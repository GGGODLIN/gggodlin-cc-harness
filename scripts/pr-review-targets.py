#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path


PROFILE_SCRIPT = Path(__file__).with_name("pr-review-profile.py")
GITHUB_URL = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)$")
BITBUCKET_URL = re.compile(r"^https?://bitbucket\.org/([^/\s]+)/([^/\s]+)/pull-requests/(\d+)$")
SCP_REMOTE = re.compile(r"^(?:[^/@:]+@)?([^/:]+):(.+)$")
BARE_NUMBER = re.compile(r"^\d+$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
SAFE_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOCKFILES = (
  "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json",
  "gemfile.lock", "poetry.lock", "pipfile.lock", "cargo.lock", "go.sum", "composer.lock",
)
GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".generated.ts")
VENDORED_SEGMENTS = ("dist/", "build/", "vendor/", "node_modules/", "coverage/")
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt", ".adoc")
FILE_COUNT_THRESHOLD = 15
DIFF_LINES_THRESHOLD = 800
REVIEW_SET_CAPACITY_KEY = "review_set"
MATERIALS_DIRNAME = "materials"
SINCE_VALUE = re.compile(r"^[0-9a-f]{7,64}$")
NAME_STATUS_KINDS = {
  "A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied", "T": "type-changed",
}
REVIEW_DIFF_NAME = "review.diff"
REVIEW_DIFF_OPTIONS = (
  "--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", "-M",
)
RELATED_PR_FIELDS = (
  "target_identity", "pr", "author", "base_ref", "merge_commit", "merge_first_parent", "head",
)
DEFAULT_REPORTS_ROOT = Path(__file__).resolve().parent.parent / "pr-review-reports"
REPORT_PR_LINE = re.compile(r"^\*\*PR\*\*:.*\((https?://[^)\s]+)\)", re.MULTILINE)
REPORT_BASIS_LINE = re.compile(r"^\*\*Review input basis\*\*:(.*)$", re.MULTILINE)
REPORT_VERIFIED = re.compile(r"input_binding:\s*verified\b")
FULL_SHA = re.compile(r"(?<![0-9a-f])([0-9a-f]{40}(?:[0-9a-f]{24})?)(?![0-9a-f])")


def load_profile_module():
  spec = importlib.util.spec_from_file_location("pr_review_profile", PROFILE_SCRIPT)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


PROFILE = load_profile_module()


def sha256_text(value):
  return hashlib.sha256(value.encode("utf-8")).hexdigest()


def git(checkout, *args):
  return subprocess.run(
    ["git", "-C", str(checkout), *args],
    capture_output=True,
    text=True,
  )


def git_ok(checkout, *args):
  proc = git(checkout, *args)
  return proc.stdout.strip() if proc.returncode == 0 else None


def remote_identity(remote):
  remote = (remote or "").strip()
  if not remote:
    return None
  if "://" in remote:
    parts = urllib.parse.urlsplit(remote)
    host, path = (parts.hostname or "").lower(), parts.path
  else:
    match = SCP_REMOTE.match(remote)
    if not match:
      return None
    host, path = match.group(1).lower(), match.group(2)
  segments = [segment for segment in path.strip("/").split("/") if segment]
  if len(segments) < 2 or "." not in host:
    return None
  return host, f"{segments[-2]}/{re.sub(r'\.git$', '', segments[-1])}"


def platform_for_host(host):
  if host == "github.com" or host.endswith(".github.com"):
    return "github"
  if host == "bitbucket.org" or host.endswith(".bitbucket.org"):
    return "bitbucket"
  return host


def parse_input(item, current_repo):
  raw = str(item.get("raw") or "").strip()
  for pattern, host in ((GITHUB_URL, "github.com"), (BITBUCKET_URL, "bitbucket.org")):
    match = pattern.match(raw)
    if match:
      owner, repo, pr = match.groups()
      return {
        "host": host,
        "platform": platform_for_host(host),
        "destination_repo": f"{owner}/{repo}",
        "pr": pr,
      }, None
  if BARE_NUMBER.match(raw):
    if not item.get("named_in_conversation") or not current_repo:
      return None, "AMBIGUOUS_INPUT"
    identity = remote_identity(current_repo.get("remote"))
    if identity is None:
      return None, "AMBIGUOUS_INPUT"
    host, repo = identity
    return {
      "host": host,
      "platform": platform_for_host(host),
      "destination_repo": repo,
      "pr": raw,
    }, None
  return None, "AMBIGUOUS_INPUT"


def target_identity(parsed):
  return f"{parsed['platform']}:{parsed['host']}/{parsed['destination_repo']}#{parsed['pr']}"


def platform_key(parsed):
  return f"{parsed['host']}/{parsed['destination_repo']}#{parsed['pr']}"


def normalize_inputs(payload):
  reason_codes = []

  def note(code):
    if code not in reason_codes:
      reason_codes.append(code)

  items = payload.get("inputs")
  if not items:
    note("EMPTY_INPUT")
    return [], reason_codes
  current_repo = payload.get("current_repo")
  parsed_items = []
  seen = set()
  for item in items:
    parsed, reason = parse_input(item, current_repo)
    if reason:
      note(reason)
      continue
    declared_repo = item.get("declared_repo")
    declared_pr = item.get("declared_pr")
    if ((declared_repo is not None and str(declared_repo) != parsed["destination_repo"])
        or (declared_pr is not None and str(declared_pr) != parsed["pr"])):
      note("CONTRADICTORY_INPUT")
      continue
    identity = target_identity(parsed)
    if identity in seen:
      continue
    seen.add(identity)
    parsed_items.append(parsed)
  parsed_items.sort(key=target_identity)
  if not parsed_items and not reason_codes:
    note("EMPTY_INPUT")
  return parsed_items, reason_codes


def source_files(changed_files):
  result = []
  for value in changed_files or []:
    path = str(value)
    lowered = path.lower()
    if lowered.rsplit("/", 1)[-1] in LOCKFILES:
      continue
    if lowered.endswith(GENERATED_SUFFIXES):
      continue
    if any(segment in lowered for segment in VENDORED_SEGMENTS):
      continue
    if lowered.endswith(DOC_SUFFIXES):
      continue
    result.append(path)
  return result


def target_slug(target):
  repo = target["destination_repo"].replace("/", "-")
  return f"{target['platform']}-{target['host']}-{repo}-{target['pr']}"


def review_root_for(checkout, target, run_id, total):
  worktrees = checkout / ".worktrees"
  if total == 1:
    return worktrees / f"review-pr-{target['pr']}"
  return worktrees / f"review-pr-{run_id}" / target_slug(target)


def materials_root_for(state_root, target, run_id, total):
  base = Path(str(state_root)).expanduser() / MATERIALS_DIRNAME / run_id
  if total == 1:
    return base / f"review-pr-{target['pr']}"
  return base / target_slug(target)


def safe_slug(value):
  return bool(SAFE_SLUG.match(str(value or ""))) and ".." not in str(value)


def response_problem(parsed, response):
  if not isinstance(response, dict) or response.get("status") != "ok":
    detail = response.get("reason") if isinstance(response, dict) else None
    return "TARGET_FETCH_FAILED", f"platform fetch failed ({detail})" if detail else "platform fetch failed"
  if str(response.get("destination_repo")) != parsed["destination_repo"]:
    return "TARGET_IDENTITY_MISMATCH", f"platform reports destination {response.get('destination_repo')}"
  return None


def resolve_checkout(parsed, response, repos):
  repo_entry = (repos or {}).get(response.get("destination_repo")) or {}
  checkout_value = repo_entry.get("checkout")
  if not checkout_value:
    return None, None, ("CHECKOUT_MISSING", "no checkout configured for destination repo")
  checkout = Path(str(checkout_value)).expanduser()
  if not checkout.is_dir():
    return None, None, ("CHECKOUT_MISSING", f"checkout not found: {checkout}")

  remote = repo_entry.get("remote") or git_ok(checkout, "remote", "get-url", "origin")
  remote_here = remote_identity(remote)
  if remote_here is None:
    return None, None, ("CHECKOUT_IDENTITY_MISMATCH", f"checkout remote is not a resolvable remote: {remote}")
  if remote_here != (parsed["host"], parsed["destination_repo"]):
    return None, None, ("CHECKOUT_IDENTITY_MISMATCH",
                        f"checkout remote resolves to {remote_here[0]}/{remote_here[1]}, "
                        f"target is {parsed['host']}/{parsed['destination_repo']}")
  return checkout, remote, None


def resolve_rules(payload, checkout, remote):
  profile = PROFILE.resolve(remote, payload.get("profile_path") or "")
  trunk = profile["trunk"]
  trunk_source = f"profile {profile['source']}" if trunk else None
  if not trunk:
    symbolic = git_ok(checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if symbolic:
      trunk = symbolic.split("/", 1)[1] if "/" in symbolic else symbolic
      trunk_source = "origin/HEAD"
  if not trunk:
    trunk, trunk_source = "master", "default master"
  return trunk, trunk_source, {
    "trunk": trunk,
    "spec_globs": list(profile["spec_globs"]),
    "conventions_docs": list(profile["conventions_docs"]),
    "source": profile["source"],
  }


def adjudicate_target(payload, parsed, response, repos):
  identity = target_identity(parsed)

  def failure(reason_code, detail):
    return None, {"target_identity": identity, "pr": parsed["pr"],
                  "reason_code": reason_code, "detail": detail}

  problem = response_problem(parsed, response)
  if problem:
    return failure(*problem)
  checkout, remote, problem = resolve_checkout(parsed, response, repos)
  if problem:
    return failure(*problem)

  head = str(response.get("head") or "")
  base = str(response.get("base") or "")
  if not COMMIT_SHA.match(head) or not COMMIT_SHA.match(base):
    return failure("TARGET_VERSION_MISSING", "head/base must be exact commit SHAs, not branch names")
  for label, ref, sha in (
    ("head", str(response.get("head_ref") or ""), head),
    ("base", str(response.get("base_ref") or ""), base),
  ):
    if not ref:
      return failure("TARGET_VERSION_UNRESOLVED", f"{label} ref missing from platform response")
    resolved = git_ok(checkout, "rev-parse", f"refs/remotes/origin/{ref}")
    if resolved is None:
      return failure("TARGET_VERSION_UNRESOLVED", f"origin/{ref} not present in checkout")
    if resolved != sha:
      return failure("TARGET_VERSION_MISMATCH", f"origin/{ref} is {resolved}, platform reports {sha}")
    if git_ok(checkout, "cat-file", "-e", f"{sha}^{{commit}}") is None:
      return failure("TARGET_VERSION_UNRESOLVED", f"{sha} is not a commit in the checkout")

  trunk, trunk_source, rules = resolve_rules(payload, checkout, remote)
  authored_diff_base = git_ok(checkout, "merge-base", f"refs/remotes/origin/{trunk}", head) or base
  return {
    "target_identity": identity,
    "platform": parsed["platform"],
    "host": parsed["host"],
    "destination_repo": parsed["destination_repo"],
    "pr": parsed["pr"],
    "source_repo": str(response.get("source_repo") or parsed["destination_repo"]),
    "head": head,
    "head_ref": str(response.get("head_ref") or ""),
    "base": base,
    "base_ref": str(response.get("base_ref") or ""),
    "trunk": trunk,
    "trunk_source": trunk_source,
    "authored_diff_base": authored_diff_base,
    "checkout": str(checkout),
    "changed_files": [str(path) for path in response.get("changed_files") or []],
    "diff_lines": int(response.get("diff_lines") or 0),
    "specs": [
      {"path": str(spec.get("path")), "content": str(spec.get("content") or "")}
      for spec in response.get("specs") or []
    ],
    "rules": rules,
  }, None


def git_bytes(checkout, *args):
  proc = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True)
  return proc.stdout if proc.returncode == 0 else None


def is_ancestor(checkout, ancestor, descendant):
  proc = git(checkout, "merge-base", "--is-ancestor", ancestor, descendant)
  if proc.returncode == 0:
    return True
  if proc.returncode == 1 and not proc.stderr.strip():
    return False
  return None


def name_status(checkout, old, new):
  proc = git(checkout, "diff", "--name-status", "-z", "-M", "--no-color", old, new)
  if proc.returncode != 0:
    return None
  tokens = proc.stdout.split("\0")
  entries = []
  index = 0
  while index < len(tokens) and tokens[index]:
    code = tokens[index][0]
    kind = NAME_STATUS_KINDS.get(code, "modified")
    if code in "RC":
      entries.append({"path": tokens[index + 2], "status": kind, "old_path": tokens[index + 1]})
      index += 3
    else:
      entries.append({"path": tokens[index + 1], "status": kind})
      index += 2
  return entries


def changed_line_count(diff_bytes):
  return sum(
    1 for line in diff_bytes.splitlines()
    if line[:1] in (b"+", b"-") and not line.startswith((b"+++ ", b"--- "))
  )


def repo_key(parsed):
  return parsed["platform"], parsed["host"], parsed["destination_repo"]


def range_identity(key, branch=None):
  platform, host, repo = key
  return f"range:{platform}:{host}/{repo}" + (f"@{branch}" if branch else "")


def range_slug(key):
  platform, host, repo = key
  return f"range-{platform}-{host}-{repo.replace('/', '-')}"


def adjudicate_merged_pr(parsed, response, repos):
  identity = target_identity(parsed)

  def failure(reason_code, detail):
    return None, {"target_identity": identity, "pr": parsed["pr"],
                  "reason_code": reason_code, "detail": detail}

  if parsed["platform"] != "github":
    return failure("MERGED_PLATFORM_UNSUPPORTED", "merged-PR review supports GitHub only")
  problem = response_problem(parsed, response)
  if problem:
    return failure(*problem)
  checkout, remote, problem = resolve_checkout(parsed, response, repos)
  if problem:
    return failure(*problem)

  merge = str(response.get("merge_commit") or "")
  head = str(response.get("head") or "")
  if not COMMIT_SHA.match(merge):
    return failure("MERGE_COMMIT_UNAVAILABLE", "platform reports no merge commit SHA")
  if git_ok(checkout, "cat-file", "-e", f"{merge}^{{commit}}") is None:
    return failure("MERGE_COMMIT_UNAVAILABLE", f"{merge} is not a commit in the checkout")
  parents = (git_ok(checkout, "rev-list", "--parents", "-n", "1", merge) or "").split()[1:]
  if len(parents) != 2 or parents[1] != head:
    return failure("MERGE_TOPOLOGY_UNSUPPORTED",
                   f"{merge} has {len(parents)} parent(s); only two-parent merges whose second parent "
                   f"is the PR head {head} are supported")
  landed = name_status(checkout, parents[0], merge)
  if landed is None:
    return failure("MERGE_COMMIT_UNAVAILABLE", f"cannot diff {parents[0]}..{merge}")
  return {
    "target_identity": identity,
    "pr": parsed["pr"],
    "author": str(response.get("author") or ""),
    "base_ref": str(response.get("base_ref") or ""),
    "merge_commit": merge,
    "merge_first_parent": parents[0],
    "head": head,
    "landed_files": landed,
    "checkout": str(checkout),
    "remote": remote,
  }, None


def since_by_repo(values, repos):
  values = [str(value).strip() for value in values or [] if str(value).strip()]
  if not values:
    return {repo: None for repo in repos}, []
  mapping = {}
  bare = []
  for value in values:
    repo, separator, sha = value.rpartition("=")
    if separator:
      mapping[repo.lower()] = sha
    else:
      bare.append(value)
  resolved = {}
  failures = []
  for repo in repos:
    if repo.lower() in mapping:
      resolved[repo] = mapping[repo.lower()]
    elif len(repos) == 1 and len(bare) == 1:
      resolved[repo] = bare[0]
    else:
      failures.append(repo)
  return resolved, failures


def order_merges(checkout, records):
  below = {}
  for record in records:
    count = 0
    for other in records:
      if other is record:
        continue
      related = is_ancestor(checkout, other["merge_commit"], record["merge_commit"])
      if related is None:
        return None, ("ANCESTRY_CHECK_FAILED",
                      f"cannot order {other['merge_commit']} against {record['merge_commit']}")
      count += int(related)
    below[record["pr"]] = count
  ordered = sorted(records, key=lambda record: (below[record["pr"]], int(record["pr"])))
  return (ordered, sum(1 for count in below.values() if count == 0)), None


def report_candidate(path, key, checkout):
  try:
    text = path.read_text()
  except (OSError, UnicodeDecodeError):
    return None
  link = REPORT_PR_LINE.search(text)
  basis = REPORT_BASIS_LINE.search(text)
  if not link or not basis or not REPORT_VERIFIED.search(basis.group(1)):
    return None
  match = GITHUB_URL.match(link.group(1))
  platform, host, repo = key
  if platform != "github" or host != "github.com" or not match:
    return None
  if f"{match.group(1)}/{match.group(2)}".casefold() != repo.casefold():
    return None
  sha = FULL_SHA.search(basis.group(1).split("destination", 1)[0])
  if not sha:
    return None
  resolved = git_ok(checkout, "rev-parse", "--verify", "--quiet", f"{sha.group(1)}^{{commit}}")
  if resolved != sha.group(1):
    return None
  return {"path": str(path), "sha": resolved}


def start_candidates(reports_root, key, checkout):
  root = Path(str(reports_root)).expanduser()
  if not root.is_dir():
    return []
  found = (report_candidate(path.resolve(), key, checkout) for path in sorted(root.rglob("*.audit.md")))
  return sorted((candidate for candidate in found if candidate), key=lambda candidate: candidate["path"])


def bound_report_paths(values):
  return {str(Path(str(value)).expanduser().resolve()) for value in values or [] if str(value).strip()}


def choose_start(checkout, since_value, ordered, roots, candidates=(), bound=frozenset()):
  if since_value is not None:
    sha = git_ok(checkout, "rev-parse", "--verify", "--quiet", f"{since_value}^{{commit}}")
    if not SINCE_VALUE.match(since_value) or not sha:
      return None, ("SINCE_UNRESOLVED", f"--since {since_value} does not resolve to a commit SHA")
    return {"sha": sha, "source": "since", "detail": f"--since {since_value}"}, None
  chosen = [candidate for candidate in candidates if candidate["path"] in bound]
  if chosen:
    report = chosen[0]
    return {
      "sha": report["sha"],
      "source": "prior-report",
      "report": report["path"],
      "detail": f"bound prior report {report['path']}",
    }, None
  if roots != 1:
    return None, ("MERGE_ORDER_AMBIGUOUS",
                  f"{roots} merges have no earlier merge in this set; pass --since for this repo")
  earliest = ordered[0]
  return {
    "sha": earliest["merge_first_parent"],
    "source": "earliest-merge-first-parent",
    "pr": earliest["pr"],
    "merge_commit": earliest["merge_commit"],
    "detail": f"first parent of the earliest merge (PR {earliest['pr']})",
  }, None


def build_range(payload, key, records, since_value, candidates=()):
  def failure(reason_code, detail, identity=None, pr=None):
    return None, None, {"target_identity": identity or range_identity(key), "pr": pr,
                        "destination_repo": key[2], "reason_code": reason_code, "detail": detail}

  branches = sorted({record["base_ref"] for record in records})
  if len(branches) != 1 or not branches[0]:
    return failure("MERGED_BRANCH_MISMATCH",
                   f"PRs in one repo must merge into one branch, got {branches}")
  branch = branches[0]
  identity = range_identity(key, branch)
  checkout = Path(records[0]["checkout"])
  end = git_ok(checkout, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}^{{commit}}")
  if not end:
    return failure("TARGET_BRANCH_UNRESOLVED", f"origin/{branch} not present in checkout", identity)
  for record in records:
    reached = is_ancestor(checkout, record["merge_commit"], end)
    if reached is None:
      return failure("ANCESTRY_CHECK_FAILED",
                     f"cannot check {record['merge_commit']} against origin/{branch} {end}",
                     identity, record["pr"])
    if not reached:
      return failure("MERGE_NOT_IN_TARGET",
                     f"{record['merge_commit']} is not an ancestor of origin/{branch} {end}",
                     identity, record["pr"])
  order, problem = order_merges(checkout, records)
  if problem:
    return failure(*problem, identity)
  ordered, roots = order
  start, problem = choose_start(checkout, since_value, ordered, roots, candidates,
                                bound_report_paths(payload.get("start_report")))
  if problem:
    return failure(*problem, identity)

  landed = set()
  for record in ordered:
    for entry in record["landed_files"]:
      landed.add(entry["path"])
      if entry.get("old_path"):
        landed.add(entry["old_path"])
  range_entries = name_status(checkout, start["sha"], end)
  if range_entries is None:
    return failure("RANGE_DIFF_FAILED", f"cannot diff {start['sha']} {end}", identity)
  entries = [entry for entry in range_entries
             if entry["path"] in landed or entry.get("old_path") in landed]
  covered = {entry["path"] for entry in entries} | {entry["old_path"] for entry in entries if entry.get("old_path")}
  excluded = [{"path": path, "reason": "no-net-diff-in-range"} for path in sorted(landed - covered)]
  diff_bytes = b""
  if entries:
    diff_bytes = git_bytes(checkout, "--literal-pathspecs", "diff", *REVIEW_DIFF_OPTIONS,
                           start["sha"], end, "--", *sorted(covered))
    if diff_bytes is None:
      return failure("RANGE_DIFF_FAILED", f"cannot produce scoped diff {start['sha']} {end}", identity)

  remote = records[0]["remote"]
  _, _, rules = resolve_rules(payload, checkout, remote)
  platform, host, repo = key
  target = {
    "kind": "range",
    "target_identity": identity,
    "platform": platform,
    "host": host,
    "destination_repo": repo,
    "source_repo": repo,
    "target_branch": branch,
    "start": start,
    "start_candidates": list(candidates),
    "end": {"sha": end, "ref": f"refs/remotes/origin/{branch}"},
    "related_prs": [
      {field: record[field] for field in RELATED_PR_FIELDS}
      for record in ordered
    ],
    "entry_files": entries,
    "excluded_files": excluded,
    "changed_files": [entry["path"] for entry in entries],
    "diff_lines": changed_line_count(diff_bytes),
    "checkout": str(checkout),
    "specs": [],
    "rules": rules,
  }
  return target, diff_bytes, None


def materialize_range(materials_root, target, diff_bytes):
  materials = materialize_target(materials_root, target)
  diff_path = materials_root / REVIEW_DIFF_NAME
  diff_path.write_bytes(diff_bytes)
  target["review_diff"] = {
    "file": str(diff_path),
    "bytes": len(diff_bytes),
    "lines": len(diff_bytes.splitlines()),
  }
  return materials


def materialize_target(materials_root, target):
  materials_root.mkdir(parents=True, exist_ok=True)
  entries = []
  for index, spec in enumerate(target["specs"]):
    digest = sha256_text(spec["content"])
    spec_path = materials_root / f"spec-{index + 1}-{Path(spec['path']).name}"
    spec_path.write_text(spec["content"])
    entries.append({
      "path": spec["path"],
      "file": str(spec_path),
      "content": spec["content"],
      "content_sha256": digest,
      "bytes": len(spec["content"].encode("utf-8")),
    })
  return {"root": str(materials_root), "specs": entries}


def build_manifest(targets):
  shared = {}
  per_target = {}
  for target in targets:
    entries = []
    for spec in target["materials"]["specs"]:
      shared_key = f"sha256:{spec['content_sha256']}"
      bucket = shared.setdefault(shared_key, {
        "key": shared_key,
        "content": spec["content"],
        "content_sha256": spec["content_sha256"],
        "bytes": spec["bytes"],
        "source_targets": [],
      })
      if target["target_identity"] not in bucket["source_targets"]:
        bucket["source_targets"].append(target["target_identity"])
        bucket["source_targets"].sort()
      entries.append({
        "path": spec["path"],
        "file": spec["file"],
        "content_sha256": spec["content_sha256"],
        "bytes": spec["bytes"],
        "shared_key": bucket["key"],
      })
    versions = (
      {"start": target["start"]["sha"], "end": target["end"]["sha"]}
      if target.get("kind") == "range" else {"head": target["head"], "base": target["base"]}
    )
    per_target[target["target_identity"]] = {
      "source_repo": target["source_repo"],
      **versions,
      "specs": entries,
      "rules": target["rules"],
      "changed_files": target["changed_files"],
      "transported_bytes": sum(entry["bytes"] for entry in entries),
    }
  return {"shared": shared, "targets": per_target}


def capacity_report(targets):
  per_target = {}
  gapped = []
  for target in targets:
    file_count = len(source_files(target["changed_files"]))
    diff_lines = target["diff_lines"]
    chunked = file_count > FILE_COUNT_THRESHOLD or diff_lines > DIFF_LINES_THRESHOLD
    per_target[target["target_identity"]] = {
      "source_file_count": file_count,
      "diff_lines": diff_lines,
      "chunked": chunked,
      "chunk_count": (file_count + FILE_COUNT_THRESHOLD - 1) // FILE_COUNT_THRESHOLD if chunked else 0,
      "threshold": {"source_files": FILE_COUNT_THRESHOLD, "diff_lines": DIFF_LINES_THRESHOLD},
    }
    if chunked:
      gapped.append(target["target_identity"])
  return per_target, gapped


def aggregate_capacity_report(targets):
  file_count = sum(len(source_files(target["changed_files"])) for target in targets)
  diff_lines = sum(target["diff_lines"] for target in targets)
  chunked = file_count > FILE_COUNT_THRESHOLD or diff_lines > DIFF_LINES_THRESHOLD
  return {
    "source_file_count": file_count,
    "diff_lines": diff_lines,
    "chunked": chunked,
    "chunk_count": (file_count + FILE_COUNT_THRESHOLD - 1) // FILE_COUNT_THRESHOLD if chunked else 0,
    "target_count": len(targets),
    "threshold": {"source_files": FILE_COUNT_THRESHOLD, "diff_lines": DIFF_LINES_THRESHOLD},
  }


def division_of_labor(selection, targets, manifest):
  shared_bytes = sum(entry["bytes"] for entry in manifest["shared"].values())
  extra = [
    {"kind": "shared-material", "content_sha256": entry["content_sha256"],
     "bytes": entry["bytes"], "source_targets": entry["source_targets"]}
    for entry in manifest["shared"].values()
  ]
  conventions = {}
  for target in targets:
    for path in target["rules"]["conventions_docs"]:
      key = f"{target['destination_repo']}:{path}"
      bucket = conventions.setdefault(key, {
        "kind": "conventions", "path": path, "source_targets": [],
      })
      if target["target_identity"] not in bucket["source_targets"]:
        bucket["source_targets"].append(target["target_identity"])
        bucket["source_targets"].sort()
  extra.extend(conventions.values())
  rows = []
  seen = set()
  for cell in selection or []:
    seat = str(cell.get("seat") or "")
    if not seat or seat in seen:
      continue
    seen.add(seat)
    rows.append({
      "seat": seat,
      "angle": str(cell.get("angle") or seat),
      "primary_material": [
        {"target_identity": target["target_identity"], "changed_files": target["changed_files"]}
        for target in targets
      ],
      "extra_context": list(extra),
      "shared_bytes": shared_bytes,
    })
  return rows


def set_identity_of(targets):
  canonical = "\n".join(sorted(target["target_identity"] for target in targets))
  return f"sha256:{sha256_text(canonical)}"


def state_path_for(state_root, run_id):
  if not safe_slug(run_id):
    return None
  return Path(str(state_root)).expanduser() / f"{run_id}.json"


def write_state(path, value):
  path = Path(str(path)).expanduser()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
  return str(path)


def read_state(path):
  if not path:
    return None
  try:
    return json.loads(Path(str(path)).expanduser().read_text())
  except (OSError, ValueError, TypeError):
    return None


def dispatch_decision(state, confirmed):
  if state.get("cancelled"):
    return {"allowed": False, "reason": "cancelled"}
  if state.get("status") == "NO_NET_DIFF":
    return {"allowed": False, "reason": "no-net-diff"}
  if state.get("status") != "READY":
    return {"allowed": False, "reason": "preparation-blocked"}
  if not state.get("selection_count"):
    return {"allowed": False, "reason": "selection-required"}
  if state.get("capacity", {}).get("adjudication_required"):
    return {"allowed": False, "reason": "awaiting-adjudication"}
  if not confirmed:
    return {"allowed": False, "reason": "awaiting-confirmation"}
  return {"allowed": True, "reason": "confirmed"}


def apply_selection(state, selection, adjudication):
  selection = selection or []
  adjudication = adjudication or {}
  seats = sorted({str(cell.get("seat")) for cell in selection if cell.get("seat")})
  targets = state.get("targets") or []
  per_target, gapped = capacity_report(targets)
  review_set = aggregate_capacity_report(targets)
  unresolved = [identity for identity in gapped if identity not in adjudication]
  if review_set["chunked"] and REVIEW_SET_CAPACITY_KEY not in adjudication:
    unresolved.append(REVIEW_SET_CAPACITY_KEY)
  if not gapped and not review_set["chunked"]:
    decision = "within-threshold"
  elif unresolved:
    decision = "awaiting-adjudication"
  else:
    decision = "adjudicated"
  state["selection"] = selection
  state["selection_count"] = 1 if selection else 0
  state["dispatch_seats"] = seats
  state["division_of_labor"] = division_of_labor(selection, targets, state["material_manifest"])
  state["capacity"] = {
    "decision": decision,
    "adjudication_required": bool(unresolved),
    "targets": per_target,
    "review_set": review_set,
    "unresolved": unresolved,
    "waiting_seats": seats if unresolved else [],
    "adjudication": adjudication,
  }
  state["dispatch"] = dispatch_decision(state, confirmed=False)
  return state


def prepare(payload):
  run_id = str(payload.get("run_id") or "")
  parsed_items, reason_codes = normalize_inputs(payload)
  state_path = state_path_for(payload.get("state_root"), run_id)
  result = {
    "status": "BLOCKED",
    "run_id": run_id,
    "targets": [],
    "failures": [],
    "reason_codes": list(reason_codes),
    "set_identity": None,
    "selection": [],
    "selection_count": 0,
    "dispatch_seats": [],
    "division_of_labor": [],
    "material_manifest": {"shared": {}, "targets": {}},
    "capacity": {
      "decision": "not-evaluated",
      "adjudication_required": False,
      "targets": {},
      "review_set": aggregate_capacity_report([]),
      "unresolved": [],
      "waiting_seats": [],
      "adjudication": {},
    },
    "dispatch": {"allowed": False, "reason": "preparation-blocked"},
    "cancelled": False,
  }
  if payload.get("merged"):
    result["no_net_diff"] = []
  if state_path is None:
    result["reason_codes"] = sorted(set([*reason_codes, "INVALID_RUN_ID"]))
    result["preparation_path"] = None
    return result
  result["preparation_path"] = str(state_path)

  if reason_codes:
    result["status"] = "NEEDS_INPUT"
    result["dispatch"] = {"allowed": False, "reason": "awaiting-correction"}
    write_state(state_path, result)
    return result

  if payload.get("merged"):
    return prepare_merged(payload, parsed_items, result, state_path, run_id)

  platform = payload.get("platform") or {}
  for parsed in parsed_items:
    response = platform.get(platform_key(parsed)) or {"status": "error", "reason": "no_platform_response"}
    target, failure = adjudicate_target(payload, parsed, response, payload.get("repos"))
    if failure:
      result["failures"].append(failure)
    else:
      result["targets"].append(target)
  if result["failures"]:
    result["targets"] = []
    write_state(state_path, result)
    return result

  total = len(result["targets"])
  for target in result["targets"]:
    target["review_root"] = str(review_root_for(Path(target["checkout"]), target, run_id, total))
    target["materials"] = materialize_target(
      materials_root_for(payload.get("state_root"), target, run_id, total), target,
    )

  result["status"] = "READY"
  result["set_identity"] = set_identity_of(result["targets"])
  result["material_manifest"] = build_manifest(result["targets"])
  result = apply_selection(result, [], {})
  write_state(state_path, result)
  return result


def prepare_merged(payload, parsed_items, result, state_path, run_id):
  platform = payload.get("platform") or {}
  groups = {}
  for parsed in parsed_items:
    response = platform.get(platform_key(parsed)) or {"status": "error", "reason": "no_platform_response"}
    record, failure = adjudicate_merged_pr(parsed, response, payload.get("repos"))
    if failure:
      result["failures"].append(failure)
    else:
      groups.setdefault(repo_key(parsed), []).append(record)
  if result["failures"]:
    write_state(state_path, result)
    return result

  since, unmapped = since_by_repo(payload.get("since"), [key[2] for key in groups])
  for key in groups:
    if key[2] in unmapped:
      result["failures"].append({
        "target_identity": range_identity(key), "pr": None, "destination_repo": key[2],
        "reason_code": "SINCE_REPO_MAPPING_REQUIRED",
        "detail": f"--since needs an explicit {key[2]}=<SHA> entry for this repo",
      })
  if result["failures"]:
    write_state(state_path, result)
    return result

  reports_root = payload.get("reports_root") or DEFAULT_REPORTS_ROOT
  candidates = {
    key: start_candidates(reports_root, key, Path(records[0]["checkout"]))
    for key, records in groups.items()
  }
  known = {candidate["path"] for found in candidates.values() for candidate in found}
  for path in sorted(bound_report_paths(payload.get("start_report")) - known):
    result["failures"].append({
      "target_identity": None, "pr": None, "destination_repo": None,
      "reason_code": "START_REPORT_NOT_CANDIDATE",
      "detail": f"bound start report {path} is not a verified start candidate for any repo in this run",
    })
  if result["failures"]:
    write_state(state_path, result)
    return result
  built = []
  for key, records in groups.items():
    target, diff_bytes, failure = build_range(payload, key, records, since[key[2]], candidates[key])
    if failure:
      result["failures"].append(failure)
    else:
      built.append((key, target, diff_bytes))
  if result["failures"]:
    write_state(state_path, result)
    return result

  for key, target, diff_bytes in built:
    if not target["entry_files"]:
      result["no_net_diff"].append({
        field: target[field] for field in (
          "target_identity", "platform", "host", "destination_repo", "target_branch",
          "start", "start_candidates", "end", "related_prs", "entry_files", "excluded_files",
        )
      } | {"status": "no-net-diff"})
      continue
    checkout = Path(target["checkout"])
    target["review_root"] = str(checkout / ".worktrees" / f"review-range-{run_id}" / range_slug(key))
    materials_root = Path(str(payload.get("state_root"))).expanduser() / MATERIALS_DIRNAME / run_id / range_slug(key)
    target["materials"] = materialize_range(materials_root, target, diff_bytes)
    result["targets"].append(target)
  result["targets"].sort(key=lambda target: target["target_identity"])
  result["no_net_diff"].sort(key=lambda entry: entry["target_identity"])

  if not result["targets"]:
    result["status"] = "NO_NET_DIFF"
    result["dispatch"] = {"allowed": False, "reason": "no-net-diff"}
    write_state(state_path, result)
    return result
  result["status"] = "READY"
  result["set_identity"] = set_identity_of(result["targets"])
  result["material_manifest"] = build_manifest(result["targets"])
  result = apply_selection(result, [], {})
  write_state(state_path, result)
  return result


def finalize(payload):
  path = payload.get("preparation_path")
  state = read_state(path)
  if state is None:
    return {"status": "ERROR", "reason_codes": ["PREPARATION_NOT_FOUND"]}
  if state.get("status") != "READY":
    return {
      "status": "ERROR",
      "reason_codes": ["PREPARATION_NOT_READY"],
      "state_status": state.get("status"),
      "preparation_path": str(path),
    }
  selection = payload.get("selection")
  if selection is None:
    selection = state.get("selection") or []
  state = apply_selection(state, selection, payload.get("adjudication") or {})
  state["preparation_path"] = str(path)
  write_state(path, state)
  return state


def authorize_dispatch(payload):
  state = read_state(payload.get("preparation_path"))
  if state is None:
    return {"allowed": False, "reason": "preparation-not-found"}
  return dispatch_decision(state, bool(payload.get("confirmation")))


def cancel(payload):
  requested = payload.get("preparation_path")
  if not requested:
    return {"cancelled": False, "removed": [], "left_to_step7": [],
            "reason_codes": ["PREPARATION_NOT_FOUND"]}
  try:
    state_file = Path(str(requested)).expanduser().resolve(strict=True)
  except (OSError, RuntimeError):
    return {"cancelled": False, "removed": [], "left_to_step7": [],
            "reason_codes": ["PREPARATION_NOT_FOUND"]}
  state = read_state(state_file)
  if state is None or not state_file.is_file():
    return {"cancelled": False, "removed": [], "left_to_step7": [],
            "reason_codes": ["PREPARATION_NOT_FOUND"]}
  run_id = str(state.get("run_id") or "")
  if not safe_slug(run_id) or state_file.parent / f"{run_id}.json" != state_file:
    return {"cancelled": False, "removed": [], "left_to_step7": [],
            "reason_codes": ["STATE_RUN_ID_MISMATCH"]}

  materials_base = (state_file.parent / MATERIALS_DIRNAME / run_id)
  try:
    materials_base = materials_base.resolve(strict=False)
  except (OSError, RuntimeError):
    return {"cancelled": False, "removed": [], "left_to_step7": [],
            "reason_codes": ["STATE_RUN_ID_MISMATCH"]}

  planned = []
  for target in state.get("targets") or []:
    recorded = (target.get("materials") or {}).get("root")
    if not recorded:
      continue
    try:
      root = Path(str(recorded)).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
      return {"cancelled": False, "removed": [], "left_to_step7": [],
              "reason_codes": ["STATE_MATERIALS_OUT_OF_SCOPE"]}
    if root == materials_base or not root.is_relative_to(materials_base):
      return {"cancelled": False, "removed": [], "left_to_step7": [],
              "reason_codes": ["STATE_MATERIALS_OUT_OF_SCOPE"]}
    planned.append((str(recorded), root))

  left_to_step7 = [target.get("review_root") for target in state.get("targets") or []
                   if target.get("review_root")]
  removed = []
  for recorded, root in planned:
    if root.is_dir():
      shutil.rmtree(root, ignore_errors=True)
    if not root.exists():
      removed.append(recorded)
  if materials_base.is_dir() and not any(materials_base.iterdir()):
    materials_base.rmdir()
  state["status"] = "CANCELLED"
  state["cancelled"] = True
  state["targets"] = []
  state["division_of_labor"] = []
  state["material_manifest"] = {"shared": {}, "targets": {}}
  state["capacity"]["review_set"] = aggregate_capacity_report([])
  state["capacity"]["unresolved"] = []
  state["capacity"]["waiting_seats"] = []
  state["dispatch"] = {"allowed": False, "reason": "cancelled"}
  write_state(state_file, state)
  return {
    "cancelled": True,
    "removed": removed,
    "left_to_step7": left_to_step7,
    "reason_codes": [],
  }


def main(argv=None):
  parser = argparse.ArgumentParser()
  parser.add_argument("mode", choices=("prepare", "finalize", "cancel", "authorize-dispatch"))
  args = parser.parse_args(argv)
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError, UnicodeDecodeError):
    json.dump({"status": "ERROR", "reason_codes": ["INVALID_INPUT_JSON"]}, sys.stdout)
    sys.stdout.write("\n")
    return 1
  if args.mode == "prepare":
    result = prepare(payload)
  elif args.mode == "finalize":
    result = finalize(payload)
  elif args.mode == "cancel":
    result = cancel(payload)
  else:
    result = authorize_dispatch(payload)
  json.dump(result, sys.stdout, ensure_ascii=False)
  sys.stdout.write("\n")
  return 0 if result.get("status") != "ERROR" else 1


if __name__ == "__main__":
  sys.exit(main())
