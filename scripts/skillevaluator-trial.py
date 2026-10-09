#!/usr/bin/env python3
"""Honest-agent trial runner and completion gate.

Threat model: this prevents accidental completion drift, not deliberate bypass by code running as the same OS user. A human permit records an explicit top-level decision but does not turn a failed Tier 1 receipt into a pass; Tier 1 failures have no count-based auto-release.
Surfaces: Locked = runner, hook wrapper, settings wiring, tests and evaluator policy; Editable = candidate SKILL.md files; Append-only = receipts and audit log; Human-controlled = exact top-level approval prompts and the disabled sentinel.
Lifecycle: bootstrap through a tested settings edit; updates use the same fixtures and exact human permit; recovery uses the disabled sentinel or an external terminal, both leaving filesystem or git evidence.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from http.client import HTTPException, IncompleteRead
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EXPECTED_VERSION = "0.3.0"
EXPECTED_COMMIT = "4dcbe371f562a8ac4bca63fce81370228a7579c7"
MAX_EMBEDDING_VECTOR_DIMENSION = 65_536
MAX_JSON_BYTES = 16 * 1024 * 1024
TIER1_CHECKS = "schema,pii,license,quality,unicode,lint"
APPROVAL_PATTERN = re.compile(r"^SkillEvaluator 放行 ([0-9a-f]{24})$")
PERMIT_TTL_SECONDS = 900
SUBPROCESS_ENV_ALLOWLIST = {
  "PATH",
  "HOME",
  "TMPDIR",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "USER",
  "LOGNAME",
  "SHELL",
  "TERM",
  "XDG_CONFIG_HOME",
  "XDG_CACHE_HOME",
  "SSL_CERT_FILE",
  "SSL_CERT_DIR",
  "REQUESTS_CA_BUNDLE",
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "NO_PROXY",
  "DOCKER_HOST",
}


def subprocess_environment(extra=None):
  environment = {key: value for key, value in os.environ.items() if key in SUBPROCESS_ENV_ALLOWLIST or key.startswith("SKILLEVALUATOR_TEST_")}
  environment.update(extra or {})
  return environment


def timeout_seconds(name, default):
  raw = os.environ.get(name)
  if raw is None:
    return default
  try:
    value = float(raw)
  except ValueError as error:
    raise ValueError(f"{name} must be numeric") from error
  if not math.isfinite(value) or value <= 0:
    raise ValueError(f"{name} must be a finite positive number")
  return value


def iso_now():
  return datetime.now(timezone.utc).isoformat()


def canonical_skill(value):
  skill = Path(value).expanduser().resolve(strict=True)
  skill_file = skill / "SKILL.md"
  if not skill.is_dir() or not is_regular_single_link(skill_file):
    raise ValueError("skill must be a directory containing a single-link regular SKILL.md")
  return skill


def is_regular_single_link(path):
  try:
    info = path.lstat()
  except OSError:
    return False
  return stat.S_ISREG(info.st_mode) and info.st_nlink == 1


def internal_policy_path():
  default = Path(__file__).with_name("skillevaluator-internal-policy.yaml")
  path = Path(os.environ.get("SKILLEVALUATOR_INTERNAL_POLICY", default)).expanduser()
  if not is_regular_single_link(path):
    raise ValueError("internal policy must be a single-link regular file")
  return path.resolve(strict=True)


def tier1_args(skill, policy):
  return [
    "validate",
    str(skill),
    "--profile",
    "external",
    "--policy",
    str(policy),
    "--tiers",
    "1",
    "--checks",
    TIER1_CHECKS,
    "--no-tier2",
    "-c",
  ]


def file_stamp(path):
  flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
  descriptor = os.open(path, flags)
  try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
      raise ValueError(f"unsafe stamp path: {path}")
    return info.st_mtime_ns, info.st_size
  finally:
    os.close(descriptor)


def parse_env_file(path):
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536:
    raise ValueError("private provider store must be a bounded single-link regular file")
  flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
  descriptor = os.open(path, flags)
  try:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_uid != os.getuid() or stat.S_IMODE(opened.st_mode) & 0o077:
      raise ValueError("private provider store must be owner-only and single-link regular")
    chunks = []
    remaining = 65537
    while remaining > 0:
      chunk = os.read(descriptor, min(8192, remaining))
      if not chunk:
        break
      chunks.append(chunk)
      remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > 65536:
      raise ValueError("private provider store is too large")
    text = data.decode("utf-8")
  finally:
    os.close(descriptor)
  values = {}
  for raw in text.splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    key = key.strip().removeprefix("export ").strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
      value = value[1:-1]
    values[key] = value
  return values


def gpt_model(key, table=Path("~/.claude/config/gpt-models.env").expanduser()):
  # 型號只在共用版本表維護；讀不到就回 None 讓呼叫端報錯，不偷偷退回某個寫死的舊型號。
  try:
    lines = table.read_text().splitlines()
  except OSError:
    return None
  pairs = (line.split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))
  return {k.strip(): v.strip() for k, v in pairs}.get(key)

def provider_env():
  keys_path = Path(os.environ.get("SKILLEVALUATOR_KEYS_FILE", "~/.cli-proxy-api/keys.env")).expanduser()
  values = parse_env_file(keys_path)
  secret = values.get("CLIPROXY_KEY_ADMIN", "").strip()
  base = values.get("CLIPROXY_BASE_URL", "http://127.0.0.1:8317").strip().rstrip("/")
  llm_model = values.get("SKILL_EVAL_LLM_MODEL") or os.environ.get("SKILL_EVAL_LLM_MODEL") or gpt_model("GPT_SOL") or ""
  embedding_base = values.get("SKILL_EVAL_EMBEDDING_BASE_URL") or os.environ.get("SKILL_EVAL_EMBEDDING_BASE_URL") or "http://127.0.0.1:11434"
  embedding_model = values.get("SKILL_EVAL_EMBEDDING_MODEL") or os.environ.get("SKILL_EVAL_EMBEDDING_MODEL") or "nomic-embed-text"
  embedding_key = values.get("SKILL_EVAL_EMBEDDING_API_KEY") or "local-no-key"
  llm_model = llm_model.strip()
  embedding_base = embedding_base.strip().rstrip("/")
  embedding_model = embedding_model.strip()
  embedding_key = embedding_key.strip()
  if not secret:
    raise ValueError("CLIPROXY_KEY_ADMIN is missing from the private provider store")
  if not base.endswith("/v1"):
    base = f"{base}/v1"
  if not embedding_base.endswith("/v1"):
    embedding_base = f"{embedding_base}/v1"
  if not llm_model or not embedding_model or not embedding_key:
    raise ValueError("provider configuration is incomplete")
  environment = {
    "SKILL_EVAL_LLM_PROVIDER": "openai-compatible",
    "SKILL_EVAL_LLM_BASE_URL": base,
    "SKILL_EVAL_LLM_MODEL": llm_model,
    "SKILL_EVAL_LLM_API_KEY": secret,
    "SKILL_EVAL_EMBEDDING_PROVIDER": "openai-compatible",
    "SKILL_EVAL_EMBEDDING_BASE_URL": embedding_base,
    "SKILL_EVAL_EMBEDDING_MODEL": embedding_model,
    "SKILL_EVAL_EMBEDDING_API_KEY": embedding_key,
  }
  secrets = [secret]
  if embedding_key not in {"local-no-key", secret}:
    secrets.append(embedding_key)
  return environment, secrets


def safe_directory(path):
  path = path.expanduser()
  if path.is_symlink():
    resolved = path.resolve(strict=True)
    if (str(path), str(resolved)) not in {("/tmp", "/private/tmp"), ("/var", "/private/var")}:
      raise ValueError(f"unsafe directory path: {path}")
    path = resolved
  else:
    path = path.resolve(strict=False)
  existing = []
  cursor = path
  while cursor != cursor.parent:
    existing.append(cursor)
    cursor = cursor.parent
  for item in reversed(existing):
    if item.exists() or item.is_symlink():
      info = item.lstat()
      if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"unsafe directory path: {item}")
    else:
      item.mkdir(mode=0o700, exist_ok=True)
      info = item.lstat()
      if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"unsafe directory path: {item}")
  return path


def safe_write(path, data):
  parent = safe_directory(path.parent)
  if path.exists() or path.is_symlink():
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
      raise ValueError(f"unsafe output path: {path}")
  fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
  try:
    with os.fdopen(fd, "w") as handle:
      handle.write(data)
      handle.flush()
      os.fsync(handle.fileno())
    os.chmod(temp_name, 0o600)
    os.replace(temp_name, path)
  finally:
    if os.path.exists(temp_name):
      os.unlink(temp_name)


def safe_write_json(path, value):
  safe_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def redact(text, secrets):
  result = text
  for secret in secrets:
    if secret:
      result = result.replace(secret, "[REDACTED]")
  return result


def contains_secret(root, secrets):
  for path in root.rglob("*"):
    if not path.is_file() or path.is_symlink():
      continue
    data = path.read_bytes()
    if any(secret.encode() in data for secret in secrets if secret):
      return True
  return False


def artifact_root_is_empty(root):
  try:
    if root.is_symlink():
      return False
    if not root.exists():
      return True
    if not root.is_dir():
      return False
    return not any(root.iterdir())
  except Exception:
    return False


def remove_artifact_root(root):
  try:
    shutil.rmtree(root)
  except Exception:
    pass
  return artifact_root_is_empty(root)


def weekly_secret_failure(args, collection, skill_count, binary, run_root, started_ns, secrets):
  scan_failed = False
  try:
    contaminated = contains_secret(run_root, secrets)
  except Exception:
    contaminated = True
    scan_failed = True
  if not contaminated:
    return None
  if remove_artifact_root(run_root):
    reason = "secret_scan_failed" if scan_failed else "secret_detected_in_artifacts"
    return weekly_infrastructure_failure(args, collection, skill_count, binary, run_root, started_ns, reason, "security", failure_target=str(run_root))
  output_root = run_root.parent / f".{run_root.name}.failure-{os.getpid()}-{time.time_ns()}"
  reason = "secret_scan_and_cleanup_failed" if scan_failed else "secret_artifact_cleanup_failed"
  return weekly_infrastructure_failure(
    args,
    collection,
    skill_count,
    binary,
    run_root,
    started_ns,
    reason,
    "security",
    output_root=output_root,
    failure_target=str(run_root),
    summary_path=output_root / "weekly-summary.md",
  )


def run_captured(command, environment, timeout):
  process = subprocess.Popen(
    command,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env=environment,
    start_new_session=True,
  )
  try:
    stdout, stderr = process.communicate(timeout=timeout)
  except subprocess.TimeoutExpired as error:
    try:
      os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
      pass
    stdout, stderr = process.communicate()
    raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from error
  return subprocess.CompletedProcess(
    command,
    process.returncode,
    stdout.decode("utf-8", "replace"),
    stderr.decode("utf-8", "replace"),
  )


def evaluator_commit(binary):
  executable = Path(binary).expanduser().resolve(strict=True)
  tool_root = executable.parent.parent
  candidates = sorted(tool_root.glob("lib/python*/site-packages/skillevaluator-*.dist-info/direct_url.json"))
  if len(candidates) != 1 or not is_regular_single_link(candidates[0]):
    raise RuntimeError("SkillEvaluator package source metadata is unavailable")
  try:
    metadata = safe_read_json(candidates[0])
  except (OSError, ValueError, json.JSONDecodeError) as error:
    raise RuntimeError("SkillEvaluator package source metadata is invalid") from error
  vcs_info = metadata.get("vcs_info") if isinstance(metadata, dict) else None
  commit = vcs_info.get("commit_id") if isinstance(vcs_info, dict) else None
  requested = vcs_info.get("requested_revision") if isinstance(vcs_info, dict) else None
  if (
    not isinstance(metadata, dict)
    or metadata.get("url") != "https://github.com/NVIDIA/SkillEvaluator.git"
    or not isinstance(vcs_info, dict)
    or vcs_info.get("vcs") != "git"
    or not isinstance(commit, str)
    or not re.fullmatch(r"[0-9a-f]{40}", commit)
    or requested != commit
  ):
    raise RuntimeError("SkillEvaluator package source metadata is invalid")
  if commit != EXPECTED_COMMIT:
    raise RuntimeError("SkillEvaluator Git commit is not the approved trial SHA")
  return commit


def run_evaluator(binary, args, environment, timeout):
  evaluator_commit(binary)
  return run_captured([binary, *args], subprocess_environment(environment), timeout)


def command_version(binary):
  evaluator_commit(binary)
  try:
    result = subprocess.run([binary, "--version"], capture_output=True, text=True, env=subprocess_environment(), timeout=timeout_seconds("SKILLEVALUATOR_VERSION_TIMEOUT_SECONDS", 15), check=False)
  except (OSError, subprocess.TimeoutExpired) as error:
    raise RuntimeError(f"SkillEvaluator version check failed: {type(error).__name__}") from error
  lines = [line.strip() for line in f"{result.stdout}\n{result.stderr}".splitlines() if line.strip()]
  matches = [match.group(1) for line in lines if (match := re.fullmatch(r"skillevaluator, version ([0-9]+\.[0-9]+\.[0-9]+)", line))]
  if result.returncode != 0 or matches != [EXPECTED_VERSION]:
    raise RuntimeError(f"SkillEvaluator version is not the pinned {EXPECTED_VERSION}")
  return EXPECTED_VERSION


def valid_report_contract(report):
  if not isinstance(report, dict):
    return False
  if not isinstance(report.get("overall_passed"), bool) or report.get("overall_status") not in {"passed", "failed", "incomplete", "error"}:
    return False
  if not isinstance(report.get("incomplete_scans"), list):
    return False
  results = report.get("results")
  if not isinstance(results, list) or not results:
    return False
  for result in results:
    if not isinstance(result, dict) or not isinstance(result.get("findings"), list) or not isinstance(result.get("summary"), dict):
      return False
    summary = result["summary"]
    checks_performed = summary.get("checks_performed")
    errors = summary.get("errors")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (checks_performed, errors)):
      return False
    legacy = result.get("legacy")
    if not isinstance(legacy, dict) or not isinstance(legacy.get("errors"), list):
      return False
  return True


def report_findings(report):
  return sum(len(result["findings"]) for result in report["results"])


def report_has_no_check_coverage(report):
  total = 0
  for result in report.get("results", []):
    value = result.get("summary", {}).get("checks_performed")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
      return True
    total += value
  return total == 0


def legacy_provider_error(error):
  if not isinstance(error, str) or not error.startswith("Context Deduplication failed:"):
    return False
  normalized = error.lower()
  return any(marker in normalized for marker in ("provider", "error code: 429", "usage_limit_reached", "rate_limit"))


def report_has_provider_evidence(report):
  if any(
    isinstance(finding, dict)
    and finding.get("category") == "CONTENT_DEDUP"
    and finding.get("check_name") in {"embedding_error", "llm_error"}
    for result in report.get("results", [])
    if isinstance(result, dict)
    for finding in result.get("findings", [])
  ):
    return True
  return any(
    legacy_provider_error(error)
    for result in report.get("results", [])
    if isinstance(result, dict)
    for error in result.get("legacy", {}).get("errors", [])
  )


def report_has_infrastructure_failure(report):
  if report.get("overall_status") in {"error", "incomplete"} or report_has_provider_evidence(report):
    return True
  for result in report.get("results", []):
    summary = result.get("summary", {})
    legacy_errors = result.get("legacy", {}).get("errors", [])
    if report.get("overall_passed") and summary.get("errors", 0) > 0:
      return True
    if any(isinstance(error, str) and not error.startswith("[") and " failed:" in error for error in legacy_errors):
      return True
  return False


def run_check(binary, args, output_dir, environment, secrets, tier):
  try:
    safe_directory(output_dir)
    result = run_evaluator(
      binary,
      [*args, "-r", "json", "-o", str(output_dir)],
      environment,
      timeout_seconds("SKILLEVALUATOR_COMMAND_TIMEOUT_SECONDS", 300),
    )
  except subprocess.TimeoutExpired as error:
    stdout = error.stdout.decode("utf-8", "replace") if isinstance(error.stdout, bytes) else error.stdout or ""
    stderr = error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else error.stderr or ""
    safe_write(output_dir / "stdout.txt", redact(stdout, secrets))
    safe_write(output_dir / "stderr.txt", redact(stderr, secrets))
    return {"status": "infrastructure_failure", "finding_count": 0, "artifact_path": None, "exit_code": 124, "reason": f"{tier}_timeout", "failure_kind": "non_provider"}
  except (OSError, RuntimeError, ValueError) as error:
    try:
      safe_write(output_dir / "stderr.txt", type(error).__name__)
    except (OSError, ValueError):
      pass
    reason = str(error) if isinstance(error, RuntimeError) else f"{tier}_process_error"
    return {"status": "infrastructure_failure", "finding_count": 0, "artifact_path": None, "exit_code": None, "reason": reason, "failure_kind": "non_provider"}
  safe_write(output_dir / "stdout.txt", redact(result.stdout, secrets))
  safe_write(output_dir / "stderr.txt", redact(result.stderr, secrets))
  reports = sorted(path for path in output_dir.glob("*.json") if is_regular_single_link(path))
  if len(reports) != 1:
    return {
      "status": "infrastructure_failure",
      "finding_count": 0,
      "artifact_path": None,
      "exit_code": result.returncode,
      "reason": f"{tier}_report_missing_or_ambiguous",
      "failure_kind": "non_provider",
    }
  try:
    report = safe_read_json(reports[0])
  except (OSError, ValueError, json.JSONDecodeError):
    return {
      "status": "infrastructure_failure",
      "finding_count": 0,
      "artifact_path": None,
      "exit_code": result.returncode,
      "reason": f"{tier}_report_invalid",
      "failure_kind": "non_provider",
    }
  if not valid_report_contract(report):
    return {
      "status": "infrastructure_failure",
      "finding_count": 0,
      "artifact_path": str(reports[0]),
      "exit_code": result.returncode,
      "reason": f"{tier}_report_contract_invalid",
      "failure_kind": "non_provider",
    }
  findings = report_findings(report)
  contradictory_exit = (
    (report["overall_passed"] and (report["overall_status"] != "passed" or result.returncode != 0))
    or (not report["overall_passed"] and result.returncode == 0)
  )
  if contradictory_exit or report["incomplete_scans"] or report_has_infrastructure_failure(report) or not report["overall_passed"] and findings == 0 or (tier == "tier1" and report_has_no_check_coverage(report)):
    status_value = "infrastructure_failure"
    reason = f"{tier}_execution_or_report_incomplete"
  elif report["overall_passed"]:
    status_value = "passed"
    reason = None
  elif tier == "tier1":
    status_value = "failed"
    reason = None
  else:
    status_value = "findings"
    reason = None
  failure_kind = "provider" if status_value == "infrastructure_failure" and report_has_provider_evidence(report) else "non_provider" if status_value == "infrastructure_failure" else None
  return {
    "status": status_value,
    "finding_count": findings,
    "artifact_path": str(reports[0]),
    "exit_code": result.returncode,
    "reason": reason,
    "failure_kind": failure_kind,
  }


def receipt_path(skill, state_root, session, edit_epoch_ns):
  identity = f"{skill}\0{session}\0{edit_epoch_ns}"
  digest = hashlib.sha256(identity.encode()).hexdigest()
  return state_root / "receipts" / f"{digest}.json"


def build_failure_receipt(skill, edit_epoch_ns, session, started_ns, started_at, reason, state_root):
  ended_ns = time.time_ns()
  path = receipt_path(skill, state_root, session, edit_epoch_ns)
  receipt = {
    "schema_version": 1,
    "kind": "edit",
    "status": "infrastructure_failure",
    "skill_path": str(skill),
    "session": session,
    "edit_epoch_ns": edit_epoch_ns,
    "run_started_ns": started_ns,
    "run_ended_ns": ended_ns,
    "run_started_at": started_at,
    "run_ended_at": iso_now(),
    "tool_version": None,
    "latency_ms": round((ended_ns - started_ns) / 1_000_000),
    "tier1": {"status": "not_run", "finding_count": 0, "artifact_path": None, "exit_code": None, "reason": reason},
    "tier2": {"status": "not_run", "finding_count": 0, "artifact_path": None, "exit_code": None, "reason": reason},
    "receipt_path": str(path),
  }
  safe_write_json(path, receipt)
  return receipt


def run_skill(args):
  started_ns = time.time_ns()
  started_at = iso_now()
  skill = canonical_skill(args.skill)
  state_root = Path(os.environ.get("SKILLEVALUATOR_TRIAL_STATE_ROOT", "~/.claude/logs/skillevaluator")).expanduser()
  artifact_root = Path(os.environ.get("SKILLEVALUATOR_TRIAL_ARTIFACT_ROOT", "~/.claude/logs/skillevaluator/artifacts")).expanduser()
  edit_epoch_ns = args.edit_epoch_ns
  skill_file = skill / "SKILL.md"
  skill_mtime_ns = skill_file.stat().st_mtime_ns
  skill_stamp_before = file_stamp(skill_file)
  if edit_epoch_ns < skill_mtime_ns:
    receipt = build_failure_receipt(skill, edit_epoch_ns, args.session, started_ns, started_at, "stale_edit_timestamp", state_root)
    print(json.dumps(receipt, ensure_ascii=False))
    return 3
  try:
    policy = internal_policy_path()
    binary = os.environ.get("SKILLEVALUATOR_BIN") or shutil.which("skillevaluator")
    if not binary:
      raise RuntimeError("skillevaluator binary is unavailable")
    version = command_version(binary)
  except (OSError, ValueError, RuntimeError) as error:
    receipt = build_failure_receipt(skill, edit_epoch_ns, args.session, started_ns, started_at, str(error), state_root)
    print(json.dumps(receipt, ensure_ascii=False))
    return 3
  try:
    environment, secrets = provider_env()
    provider_error = None
  except (OSError, ValueError) as error:
    environment, secrets = {}, []
    provider_error = str(error)
  digest = hashlib.sha256(str(skill).encode()).hexdigest()[:16]
  run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{os.getpid()}"
  run_root = artifact_root / "edit" / digest / run_id
  tier1 = run_check(
    binary,
    tier1_args(skill, policy),
    run_root / "tier1",
    {},
    [],
    "tier1",
  )
  tier2 = {
    "status": "infrastructure_failure",
    "finding_count": 0,
    "artifact_path": None,
    "exit_code": None,
    "reason": provider_error,
    "failure_kind": "provider",
  } if provider_error else run_check(
    binary,
    [
      "context-optimization-check",
      str(skill),
      "--model",
      environment["SKILL_EVAL_EMBEDDING_MODEL"],
      "--llm-model",
      environment["SKILL_EVAL_LLM_MODEL"],
    ],
    run_root / "tier2",
    environment,
    secrets,
    "tier2",
  )
  skill_changed = file_stamp(skill_file) != skill_stamp_before
  secret_leak = contains_secret(run_root, secrets)
  overall_reason = None
  if secret_leak:
    shutil.rmtree(run_root, ignore_errors=True)
    tier1 = {"status": "infrastructure_failure", "finding_count": 0, "artifact_path": None, "exit_code": tier1["exit_code"], "reason": "secret_detected_in_artifacts", "failure_kind": "non_provider"}
    tier2 = {"status": "infrastructure_failure", "finding_count": 0, "artifact_path": None, "exit_code": tier2["exit_code"], "reason": "secret_detected_in_artifacts", "failure_kind": "non_provider"}
    overall_reason = "secret_detected_in_artifacts"
  elif skill_changed:
    tier1 = {**tier1, "status": "infrastructure_failure", "reason": "skill_changed_during_run", "failure_kind": "non_provider"}
    tier2 = {**tier2, "status": "infrastructure_failure", "reason": "skill_changed_during_run", "failure_kind": "non_provider"}
    overall_reason = "skill_changed_during_run"
  if tier1["status"] == "infrastructure_failure" or tier2["status"] == "infrastructure_failure":
    status_value = "infrastructure_failure"
  elif tier1["status"] == "failed":
    status_value = "tier1_failed"
  else:
    status_value = "passed"
  ended_ns = time.time_ns()
  path = receipt_path(skill, state_root, args.session, edit_epoch_ns)
  receipt = {
    "schema_version": 1,
    "kind": "edit",
    "status": status_value,
    "skill_path": str(skill),
    "session": args.session,
    "edit_epoch_ns": edit_epoch_ns,
    "run_started_ns": started_ns,
    "run_ended_ns": ended_ns,
    "run_started_at": started_at,
    "run_ended_at": iso_now(),
    "tool_version": version,
    "reason": overall_reason,
    "latency_ms": round((ended_ns - started_ns) / 1_000_000),
    "tier1": tier1,
    "tier2": tier2,
    "receipt_path": str(path),
  }
  safe_write_json(path, receipt)
  print(json.dumps(receipt, ensure_ascii=False))
  if status_value == "passed":
    return 0
  if status_value == "tier1_failed":
    return 2
  return 3


def valid_embedding_vector(vector):
  if not isinstance(vector, list) or not vector or len(vector) > MAX_EMBEDDING_VECTOR_DIMENSION:
    return False
  maximum_component = math.sqrt(sys.float_info.max / len(vector))
  norm = 0.0
  for value in vector:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
      return False
    try:
      numeric = float(value)
    except (OverflowError, ValueError):
      return False
    if not math.isfinite(numeric) or abs(numeric) > maximum_component:
      return False
    norm = math.hypot(norm, numeric)
  return math.isfinite(norm) and norm != 0.0


def embedding_preflight(environment):
  result = {"status": "passed", "attempts": 1, "finding_count": 0, "reason": None}
  try:
    endpoint = f"{environment['SKILL_EVAL_EMBEDDING_BASE_URL'].rstrip('/')}/embeddings"
    payload = json.dumps({
      "input": ["SkillEvaluator preflight"],
      "model": environment["SKILL_EVAL_EMBEDDING_MODEL"],
      "encoding_format": "float",
    }).encode()
    request = Request(
      endpoint,
      data=payload,
      headers={
        "Authorization": f"Bearer {environment['SKILL_EVAL_EMBEDDING_API_KEY']}",
        "Content-Type": "application/json",
      },
      method="POST",
    )
    with urlopen(request, timeout=timeout_seconds("SKILLEVALUATOR_EMBEDDING_PREFLIGHT_TIMEOUT_SECONDS", 10)) as response:
      declared_length = response.headers.get("Content-Length")
      if declared_length is not None:
        declared_length = int(declared_length)
        if declared_length < 0:
          raise ValueError("embedding response length is invalid")
        if declared_length > MAX_JSON_BYTES:
          result["status"] = "infrastructure_failure"
          result["reason"] = "embedding_probe_response_too_large"
          return result
      raw_response = response.read(MAX_JSON_BYTES + 1)
    if declared_length is not None and len(raw_response) < declared_length:
      raise IncompleteRead(raw_response, declared_length - len(raw_response))
    if len(raw_response) > MAX_JSON_BYTES:
      result["status"] = "infrastructure_failure"
      result["reason"] = "embedding_probe_response_too_large"
      return result
    response_data = json.loads(raw_response.decode("utf-8"))
    vectors = response_data.get("data") if isinstance(response_data, dict) else None
    item = vectors[0] if isinstance(vectors, list) and len(vectors) == 1 and isinstance(vectors[0], dict) else None
    index = item.get("index") if item is not None else None
    vector = item.get("embedding") if item is not None else None
    if type(index) is not int or index != 0 or not valid_embedding_vector(vector):
      result["status"] = "infrastructure_failure"
      result["reason"] = "embedding_probe_invalid_response"
  except HTTPError as error:
    try:
      error.close()
    except OSError:
      pass
    result["status"] = "infrastructure_failure"
    result["reason"] = "embedding_endpoint_http_error"
  except URLError:
    result["status"] = "infrastructure_failure"
    result["reason"] = "embedding_endpoint_unreachable"
  except IncompleteRead:
    result["status"] = "infrastructure_failure"
    result["reason"] = "embedding_probe_incomplete_response"
  except HTTPException:
    result["status"] = "infrastructure_failure"
    result["reason"] = "embedding_probe_http_error"
  except (OSError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
    result["status"] = "infrastructure_failure"
    result["reason"] = "embedding_probe_failed"
  return result


def weekly_skill_result(binary, entry, run_root, environment, secrets, provider_error, policy):
  entry_name, skill = entry
  digest = hashlib.sha256(f"{entry_name}|{skill}".encode()).hexdigest()[:12]
  skill_root = run_root / "skills" / f"{entry_name}-{digest}"
  skill_file = skill / "SKILL.md"
  skill_stamp_before = file_stamp(skill_file)
  tier1 = run_check(
    binary,
    tier1_args(skill, policy),
    skill_root / "tier1",
    {},
    [],
    "tier1",
  )
  tier2 = {
    "status": "infrastructure_failure",
    "finding_count": 0,
    "artifact_path": None,
    "exit_code": None,
    "reason": provider_error,
    "failure_kind": "provider",
  } if provider_error else run_check(
    binary,
    [
      "context-optimization-check",
      str(skill),
      "--model",
      environment["SKILL_EVAL_EMBEDDING_MODEL"],
      "--llm-model",
      environment["SKILL_EVAL_LLM_MODEL"],
    ],
    skill_root / "tier2-intra",
    environment,
    secrets,
    "tier2",
  )
  if file_stamp(skill_file) != skill_stamp_before:
    changed = {
      "status": "infrastructure_failure",
      "finding_count": 0,
      "artifact_path": None,
      "exit_code": None,
      "reason": "skill_changed_during_weekly_run",
      "failure_kind": "non_provider",
    }
    tier1 = changed
    tier2 = changed
  return {
    "skill_name": entry_name,
    "skill_path": str(skill),
    "tier1": tier1,
    "tier2_intra": tier2,
  }


def count_status(items, field, statuses):
  return {status_value: sum(1 for item in items if item[field]["status"] == status_value) for status_value in statuses}


def weekly_summary(packet):
  lines = [
    "# SkillEvaluator weekly",
    "",
    "本報告是 stateless 單輪盤點，不比較前週狀態。",
    "",
    f"- Status：{packet.get('status', 'completed')}",
    f"- Reason：{packet.get('reason') or 'none'}",
    f"- Skills：{packet['skill_count']}",
    f"- Tier 1：passed {packet['tier1']['passed']} / failed {packet['tier1']['failed']} / incomplete {packet['tier1']['infrastructure_failure']}",
    f"- Tier 2 preflight：{packet['tier2_preflight']['status']}（{packet['tier2_preflight']['reason'] or 'ok'}）",
    f"- Tier 2 intra：passed {packet['tier2_intra']['passed']} / findings {packet['tier2_intra']['findings']} / infrastructure failures {packet['tier2_intra']['infrastructure_failure']}",
    f"- Tier 2 inter：{packet['tier2_inter']['status']}，findings {packet['tier2_inter']['finding_count']}",
    f"- Latency：{packet['latency_ms']} ms",
    "",
    "## Actionable findings",
  ]
  findings = []
  for item in packet["skills"]:
    if item["tier1"]["status"] == "failed":
      findings.append(f"- {item['skill_name']}：Tier 1 failed（{item['tier1']['finding_count']} finding）")
    if item["tier2_intra"]["status"] == "findings":
      findings.append(f"- {item['skill_name']}：Tier 2 intra finding（{item['tier2_intra']['finding_count']}）")
  if packet["tier2_inter"]["status"] == "findings":
    findings.append(f"- Collection：Tier 2 inter finding（{packet['tier2_inter']['finding_count']}）")
  if findings:
    lines.extend(findings[:20])
    if len(findings) > 20:
      lines.append(f"- 另有 {len(findings) - 20} 項，見 structured result。")
  else:
    lines.append("- 無")
  provider_failures = packet.get("provider_failures", [])
  non_provider_failures = packet.get("non_provider_failures", [])
  lines.extend(["", "## Provider failures"])
  if provider_failures:
    lines.extend(f"- {item['scope']}：{item['target']}（{item.get('reason') or 'unknown'}）" for item in provider_failures[:20])
    if len(provider_failures) > 20:
      lines.append(f"- 另有 {len(provider_failures) - 20} 項，見 structured result。")
  else:
    lines.append("- 無")
  lines.extend(["", "## Non-provider failures"])
  if non_provider_failures:
    lines.extend(f"- {item['scope']}：{item['target']}（{item.get('reason') or 'unknown'}）" for item in non_provider_failures[:20])
    if len(non_provider_failures) > 20:
      lines.append(f"- 另有 {len(non_provider_failures) - 20} 項，見 structured result。")
  else:
    lines.append("- 無")
  lines.extend([
    "",
    "## Native artifacts",
    f"- Root：{packet['artifact_root']}",
    f"- Structured result：{packet['result_path']}",
    "",
  ])
  return "\n".join(lines)


def weekly_infrastructure_failure(args, collection, skill_count, binary, run_root, started_ns, reason, failure_scope=None, failure_kind="non_provider", output_root=None, summary_path=None, failure_target=None):
  output_root = output_root or run_root
  result_path = output_root / "weekly-result.json"
  summary_path = Path(summary_path).expanduser() if summary_path else Path(args.summary).expanduser()
  failure = {"scope": failure_scope, "target": str(failure_target if failure_target is not None else binary), "reason": reason}
  provider_failures = [failure] if failure_scope and failure_kind == "provider" else []
  non_provider_failures = [failure] if failure_scope and failure_kind == "non_provider" else []
  packet = {
    "schema_version": 1,
    "kind": "weekly",
    "status": "infrastructure_failure",
    "date": args.date,
    "collection_path": str(collection),
    "skill_count": skill_count,
    "tool_version": None,
    "reason": reason,
    "tier1": {"passed": 0, "failed": 0, "infrastructure_failure": 0},
    "tier2_preflight": {"status": "infrastructure_failure", "attempts": 0, "finding_count": 0, "reason": reason},
    "tier2_intra": {"passed": 0, "findings": 0, "infrastructure_failure": 0, "finding_count": 0},
    "tier2_inter": {"status": "infrastructure_failure", "finding_count": 0, "artifact_path": None, "exit_code": None, "reason": reason},
    "provider_failures": provider_failures,
    "non_provider_failures": non_provider_failures,
    "latency_ms": round((time.time_ns() - started_ns) / 1_000_000),
    "artifact_root": str(output_root),
    "result_path": str(result_path),
    "summary_path": str(summary_path),
    "skills": [],
  }
  safe_write_json(result_path, packet)
  safe_write(summary_path, weekly_summary(packet))
  print(json.dumps(packet, ensure_ascii=False))
  return 3


def run_weekly(args):
  started_ns = time.time_ns()
  collection = Path(args.collection).expanduser().resolve(strict=True)
  if not collection.is_dir() or collection.is_symlink():
    raise ValueError("collection must be a regular directory")
  policy = internal_policy_path()
  skills = []
  for child in sorted(collection.iterdir(), key=lambda path: path.name):
    try:
      skill = canonical_skill(child)
    except (OSError, ValueError):
      continue
    skills.append((child.name, skill))
  try:
    environment, secrets = provider_env()
    provider_error = None
  except (OSError, ValueError) as error:
    environment, secrets = {}, []
    provider_error = str(error)
  artifact_root = Path(os.environ.get("SKILLEVALUATOR_TRIAL_ARTIFACT_ROOT", "~/.claude/logs/skillevaluator/artifacts")).expanduser()
  run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{os.getpid()}"
  run_root = artifact_root / "weekly" / args.date / run_id
  safe_directory(run_root)
  binary = os.environ.get("SKILLEVALUATOR_BIN") or shutil.which("skillevaluator")
  binary_label = binary or "skillevaluator"
  if not binary:
    return weekly_infrastructure_failure(args, collection, len(skills), binary_label, run_root, started_ns, "skillevaluator binary is unavailable", "evaluator")
  try:
    version = command_version(binary)
  except FileNotFoundError:
    return weekly_infrastructure_failure(args, collection, len(skills), binary, run_root, started_ns, "skillevaluator binary is unavailable", "evaluator")
  except (OSError, ValueError, RuntimeError) as error:
    return weekly_infrastructure_failure(args, collection, len(skills), binary, run_root, started_ns, str(error), "provenance")
  if provider_error:
    tier2_preflight = {
      "status": "infrastructure_failure",
      "attempts": 0,
      "finding_count": 0,
      "reason": provider_error,
    }
  else:
    tier2_preflight = embedding_preflight(environment)
  tier2_error = tier2_preflight["reason"] if tier2_preflight["status"] == "infrastructure_failure" else None
  with ThreadPoolExecutor(max_workers=args.workers) as executor:
    items = list(executor.map(lambda skill: weekly_skill_result(binary, skill, run_root, environment, secrets, tier2_error, policy), skills))
  if tier2_error:
    inter = {
      "status": "infrastructure_failure",
      "finding_count": 0,
      "artifact_path": None,
      "exit_code": None,
      "reason": tier2_error,
      "failure_kind": "provider",
    }
  else:
    with tempfile.TemporaryDirectory(prefix="skillevaluator-weekly-") as temporary:
      canonical_collection = Path(temporary) / "canonical-collection"
      safe_directory(canonical_collection)
      for entry_name, skill in skills:
        destination = canonical_collection / entry_name
        safe_directory(destination)
        safe_write(destination / "SKILL.md", (skill / "SKILL.md").read_text())
      inter = run_check(
        binary,
        ["similarity-check", str(canonical_collection), "--type", "skill", "--model", environment["SKILL_EVAL_EMBEDDING_MODEL"]],
        run_root / "tier2-inter",
        environment,
        secrets,
        "tier2",
      )
  secret_failure = weekly_secret_failure(args, collection, len(skills), binary, run_root, started_ns, secrets)
  if secret_failure is not None:
    return secret_failure
  provider_failures = []
  non_provider_failures = []
  for item in items:
    for field, scope in (("tier1", "tier1"), ("tier2_intra", "tier2-intra")):
      result = item[field]
      if result["status"] != "infrastructure_failure":
        continue
      reason = result.get("reason")
      failure = {"scope": scope, "target": item["skill_path"], "reason": reason}
      if result.get("failure_kind") == "provider":
        provider_failures.append(failure)
      else:
        non_provider_failures.append(failure)
  if inter["status"] == "infrastructure_failure":
    reason = inter.get("reason")
    failure = {"scope": "tier2-inter", "target": str(collection), "reason": reason}
    if inter.get("failure_kind") == "provider":
      provider_failures.append(failure)
    else:
      non_provider_failures.append(failure)
  result_path = run_root / "weekly-result.json"
  ended_ns = time.time_ns()
  has_infrastructure_failure = bool(provider_failures or non_provider_failures)
  packet_status = "infrastructure_failure" if has_infrastructure_failure else "completed"
  packet_reason = (
    tier2_preflight["reason"]
    if tier2_preflight["status"] == "infrastructure_failure"
    else non_provider_failures[0]["reason"]
    if non_provider_failures
    else "weekly_provider_failure"
    if provider_failures
    else None
  )
  packet = {
    "schema_version": 1,
    "kind": "weekly",
    "status": packet_status,
    "date": args.date,
    "collection_path": str(collection),
    "skill_count": len(skills),
    "tool_version": version,
    "reason": packet_reason,
    "tier1": count_status(items, "tier1", ["passed", "failed", "infrastructure_failure"]),
    "tier2_preflight": tier2_preflight,
    "tier2_intra": {
      **count_status(items, "tier2_intra", ["passed", "findings", "infrastructure_failure"]),
      "finding_count": sum(item["tier2_intra"]["finding_count"] for item in items),
    },
    "tier2_inter": inter,
    "provider_failures": provider_failures,
    "non_provider_failures": non_provider_failures,
    "latency_ms": round((ended_ns - started_ns) / 1_000_000),
    "artifact_root": str(run_root),
    "result_path": str(result_path),
    "summary_path": str(Path(args.summary).expanduser()),
    "skills": items,
  }
  safe_write_json(result_path, packet)
  safe_write(Path(args.summary).expanduser(), weekly_summary(packet))
  audit("weekly_completed", date=args.date, skill_count=len(skills), provider_failures=len(provider_failures), non_provider_failures=len(non_provider_failures), latency_ms=packet["latency_ms"])
  print(json.dumps(packet, ensure_ascii=False))
  return 0


def tier3_failure(skill, started_ns, reason, run_dir=None, upstream_exit_code=None):
  packet = {
    "schema_version": 1,
    "kind": "tier3",
    "status": "infrastructure_failure",
    "skill_path": str(skill),
    "reason": reason,
    "latency_ms": round((time.time_ns() - started_ns) / 1_000_000),
    "run_dir": str(run_dir) if run_dir else None,
    "upstream_exit_code": upstream_exit_code,
  }
  print(json.dumps(packet, ensure_ascii=False))
  return 3


def validate_single_eval_case(skill):
  path = skill / "evals" / "evals.json"
  try:
    dataset = safe_read_json(path)
  except (OSError, ValueError, json.JSONDecodeError) as error:
    raise ValueError("Tier 3 requires one regular evals/evals.json file") from error
  if not isinstance(dataset, list) or len(dataset) != 1 or not isinstance(dataset[0], dict):
    raise ValueError("Tier 3 runner requires exactly one eval case")
  if not isinstance(dataset[0].get("id"), str) or not dataset[0]["id"].strip() or not isinstance(dataset[0].get("question"), str) or not dataset[0]["question"].strip():
    raise ValueError("Tier 3 eval case must include non-empty id and question")


def tier3_run_directories(results_dir):
  directories = set()
  if not results_dir.exists():
    return directories
  for skill_directory in results_dir.iterdir():
    if skill_directory.is_symlink() or not skill_directory.is_dir():
      continue
    for run_directory in skill_directory.iterdir():
      if not run_directory.is_symlink() and run_directory.is_dir():
        directories.add(run_directory.resolve())
  return directories


def attempt_coverage(packet):
  expected = packet.get("expected_attempts") if isinstance(packet, dict) else None
  scored = packet.get("scored_attempts") if isinstance(packet, dict) else None
  if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (expected, scored)) or scored != expected:
    return None
  return expected


def tier3_result_complete(result_packet, summaries):
  root_attempts = attempt_coverage(result_packet)
  if not isinstance(result_packet, dict) or result_packet.get("execution_status") != "succeeded" or result_packet.get("report_status") != "complete" or root_attempts is None:
    return False
  conditions = result_packet.get("agents", {}).get("codex", {}).get("conditions")
  if not isinstance(conditions, dict):
    return False
  arm_attempts = []
  for arm, summary in zip(("with_skill", "without_skill"), summaries):
    condition = conditions.get(arm)
    condition_attempts = attempt_coverage(condition)
    summary_attempts = attempt_coverage(summary)
    if not isinstance(condition, dict) or condition.get("execution_status") != "succeeded" or condition_attempts is None:
      return False
    if not isinstance(summary, dict) or summary.get("execution_status") != "succeeded" or summary_attempts != condition_attempts:
      return False
    arm_attempts.append(condition_attempts)
  return sum(arm_attempts) == root_attempts


def purge_secret_artifacts(run_dir, secrets):
  if run_dir and run_dir.exists() and contains_secret(run_dir, secrets):
    shutil.rmtree(run_dir, ignore_errors=True)
    return True
  return False


def run_tier3(args):
  started_ns = time.time_ns()
  try:
    skill = canonical_skill(args.skill)
    validate_single_eval_case(skill)
    environment, secrets = provider_env()
    binary = os.environ.get("SKILLEVALUATOR_BIN") or shutil.which("skillevaluator")
    if not binary:
      raise RuntimeError("skillevaluator binary is unavailable")
    version = command_version(binary)
    environment = {
      **environment,
      "OPENAI_API_KEY": environment["SKILL_EVAL_LLM_API_KEY"],
      "OPENAI_BASE_URL": environment["SKILL_EVAL_LLM_BASE_URL"],
    }
    default_root = Path(os.environ.get("SKILLEVALUATOR_TRIAL_ARTIFACT_ROOT", "~/.claude/logs/skillevaluator/artifacts")).expanduser() / "tier3"
    results_dir = safe_directory(Path(args.results_dir).expanduser() if args.results_dir else default_root)
    before = tier3_run_directories(results_dir)
    command = [
      binary,
      "tier3",
      "evaluate",
      str(skill),
      "--agents",
      "codex",
      "--env-mode",
      "local",
      "--model",
      environment["SKILL_EVAL_LLM_MODEL"],
      "--agent-model",
      f"codex={environment['SKILL_EVAL_LLM_MODEL']}",
      "--n-attempts",
      "1",
      "--n-concurrent",
      "1",
      "--max-agents",
      "1",
      "--progress",
      "plain",
      "--results-dir",
      str(results_dir),
    ]
    try:
      result = run_evaluator(
        binary,
        command[1:],
        environment,
        timeout_seconds("SKILLEVALUATOR_TIER3_TIMEOUT_SECONDS", 900),
      )
    except subprocess.TimeoutExpired:
      after = tier3_run_directories(results_dir)
      for path in after - before:
        purge_secret_artifacts(path, secrets)
      return tier3_failure(skill, started_ns, "Tier 3 process timeout", upstream_exit_code=124)
    except OSError as error:
      return tier3_failure(skill, started_ns, f"Tier 3 process error: {type(error).__name__}")
    after = tier3_run_directories(results_dir)
    candidates = sorted(path for path in after - before if (path / "result.json").is_file())
    if len(candidates) != 1:
      for path in after - before:
        if path.exists() and contains_secret(path, secrets):
          shutil.rmtree(path, ignore_errors=True)
      return tier3_failure(skill, started_ns, "Tier 3 process did not create one result directory", upstream_exit_code=result.returncode)
    run_dir = candidates[0]
    result_path = run_dir / "result.json"
    html_path = run_dir / "report.html"
    summary_paths = [
      run_dir / "codex" / "with-skill" / "summary.json",
      run_dir / "codex" / "without-skill" / "summary.json",
    ]
    safe_write(run_dir / "runner.stdout.txt", redact(result.stdout, secrets))
    safe_write(run_dir / "runner.stderr.txt", redact(result.stderr, secrets))
    try:
      result_packet = safe_read_json(result_path)
      summaries = [safe_read_json(path) for path in summary_paths] if is_regular_single_link(html_path) and all(is_regular_single_link(path) for path in summary_paths) else []
    except (OSError, ValueError, json.JSONDecodeError):
      secret_found = purge_secret_artifacts(run_dir, secrets)
      reason = "secret detected in Tier 3 artifacts" if secret_found else "Tier 3 artifacts are invalid"
      return tier3_failure(skill, started_ns, reason, run_dir=None if secret_found else run_dir, upstream_exit_code=result.returncode)
    complete = len(summaries) == 2 and tier3_result_complete(result_packet, summaries)
    secret_found = purge_secret_artifacts(run_dir, secrets)
    if secret_found:
      return tier3_failure(skill, started_ns, "secret detected in Tier 3 artifacts", upstream_exit_code=result.returncode)
    if not complete:
      return tier3_failure(skill, started_ns, "Tier 3 artifacts are incomplete", run_dir=run_dir, upstream_exit_code=result.returncode)
    receipt = {
      "schema_version": 1,
      "kind": "tier3",
      "status": "completed",
      "verdict": "not_a_skill_verdict",
      "skill_path": str(skill),
      "tool_version": version,
      "upstream_exit_code": result.returncode,
      "latency_ms": round((time.time_ns() - started_ns) / 1_000_000),
      "run_dir": str(run_dir),
      "result_path": str(result_path),
      "html_path": str(html_path),
      "harbor_summary_paths": [str(path) for path in summary_paths],
    }
    receipt_path_value = run_dir / "runner-receipt.json"
    receipt["receipt_path"] = str(receipt_path_value)
    safe_write_json(receipt_path_value, receipt)
    audit("tier3_completed", skill_path=str(skill), latency_ms=receipt["latency_ms"], run_dir=str(run_dir))
    print(json.dumps(receipt, ensure_ascii=False))
    return 0
  except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
    return tier3_failure(args.skill, started_ns, str(error))


def state_root():
  return Path(os.environ.get("SKILLEVALUATOR_TRIAL_STATE_ROOT", "~/.claude/logs/skillevaluator")).expanduser()


def object_digest(value):
  return hashlib.sha256(value.encode()).hexdigest()


def safe_append_json(path, value):
  parent = safe_directory(path.parent)
  if path.exists() or path.is_symlink():
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
      raise ValueError(f"unsafe append path: {path}")
  flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
  descriptor = os.open(path, flags, 0o600)
  try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
      raise ValueError(f"unsafe append path: {path}")
    os.write(descriptor, (json.dumps(value, ensure_ascii=False) + "\n").encode())
    os.fsync(descriptor)
  finally:
    os.close(descriptor)


def audit(event, **fields):
  try:
    safe_append_json(state_root() / "audit.jsonl", {"timestamp": iso_now(), "event": event, **fields})
  except (OSError, ValueError):
    pass


def pending_path(session, skill):
  return state_root() / "pending" / object_digest(session) / f"{object_digest(str(skill))}.json"


def fallback_root():
  return Path(os.environ.get("SKILLEVALUATOR_TRIAL_FALLBACK_ROOT", "~/.claude/logs/skillevaluator-fallback")).expanduser()


def fallback_pending_path(session, skill):
  return fallback_root() / "pending" / object_digest(session) / f"{object_digest(str(skill))}.json"


def permit_path(session, approval_id):
  return state_root() / "permits" / object_digest(session) / f"{approval_id}.json"


def spent_permit_path(session, approval_id):
  return state_root() / "spent-permits" / object_digest(session) / f"{approval_id}.json"


def lock_path_for_pending(path):
  return path.parent.parent.parent / "locks" / path.parent.name / f"{path.stem}.lock"


@contextmanager
def pending_lock(path):
  lock = lock_path_for_pending(path)
  safe_directory(lock.parent)
  descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
  try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
      raise ValueError("pending lock is unsafe")
    os.fchmod(descriptor, 0o600)
    try:
      fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
      raise ValueError("pending state is locked") from error
    yield
  finally:
    try:
      fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
      os.close(descriptor)


def approval_binding(obligation, receipt):
  skill_file = Path(str(obligation.get("skill_path", ""))) / "SKILL.md"
  receipt_file = Path(str(receipt.get("receipt_path", "")))
  artifact_file = Path(str(receipt.get("tier1", {}).get("artifact_path", "")))
  if not is_regular_single_link(skill_file):
    raise ValueError("current skill must be a regular file")
  if not is_regular_single_link(receipt_file) or not is_regular_single_link(artifact_file):
    raise ValueError("approval evidence must be regular files")
  return {
    "session": obligation.get("session"),
    "skill_path": obligation.get("skill_path"),
    "edit_epoch_ns": obligation.get("edit_epoch_ns"),
    "receipt_path": str(receipt_file),
    "tier1_artifact_path": str(artifact_file),
  }


def approval_id_for(obligation, receipt):
  payload = json.dumps(approval_binding(obligation, receipt), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
  return hashlib.sha256(payload.encode()).hexdigest()[:24]


def valid_permit(obligation, receipt):
  approval_id = approval_id_for(obligation, receipt)
  session = str(obligation.get("session", ""))
  path = permit_path(session, approval_id)
  if not path.exists() and not path.is_symlink():
    return False, path, approval_id
  permit = safe_read_json(path)
  binding = approval_binding(obligation, receipt)
  required = {"schema_version", "kind", "approval_id", "issued_at", "expires_at", "consumed", *binding.keys()}
  if not isinstance(permit, dict) or set(permit) != required:
    raise ValueError("permit contract is invalid")
  if permit.get("schema_version") != 1 or permit.get("kind") != "tier1-human-override":
    raise ValueError("permit contract is invalid")
  if permit.get("approval_id") != approval_id or any(permit.get(key) != value for key, value in binding.items()):
    raise ValueError("permit binding mismatch")
  issued_at = permit.get("issued_at")
  expires_at = permit.get("expires_at")
  if permit.get("consumed") is not False or not isinstance(issued_at, str) or isinstance(expires_at, bool) or not isinstance(expires_at, int):
    raise ValueError("permit state is invalid")
  try:
    datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
  except ValueError as error:
    raise ValueError("permit issued_at is invalid") from error
  if expires_at <= int(time.time()):
    return False, path, approval_id
  return True, path, approval_id


def valid_spent_permit(obligation, receipt):
  approval_id = approval_id_for(obligation, receipt)
  session = str(obligation.get("session", ""))
  path = spent_permit_path(session, approval_id)
  if not path.exists() and not path.is_symlink():
    return False, path, approval_id
  tombstone = safe_read_json(path)
  binding = approval_binding(obligation, receipt)
  required = {"schema_version", "kind", "approval_id", "consumed_at", *binding.keys()}
  if not isinstance(tombstone, dict) or set(tombstone) != required:
    raise ValueError("spent permit contract is invalid")
  if tombstone.get("schema_version") != 1 or tombstone.get("kind") != "tier1-human-override-consumed":
    raise ValueError("spent permit contract is invalid")
  if tombstone.get("approval_id") != approval_id or any(tombstone.get(key) != value for key, value in binding.items()):
    raise ValueError("spent permit binding mismatch")
  consumed_at = tombstone.get("consumed_at")
  if not isinstance(consumed_at, str):
    raise ValueError("spent permit consumed_at is invalid")
  try:
    datetime.fromisoformat(consumed_at.replace("Z", "+00:00"))
  except ValueError as error:
    raise ValueError("spent permit consumed_at is invalid") from error
  return True, path, approval_id


def hook_output(event, message):
  return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}, ensure_ascii=False)


def posttool_hook(payload):
  tool = str(payload.get("tool_name", ""))
  file_path = str(payload.get("tool_input", {}).get("file_path", ""))
  if tool not in {"Edit", "Write"} or Path(file_path).name != "SKILL.md":
    return 0
  disabled = state_root() / "disabled"
  if disabled.exists() or disabled.is_symlink():
    print(f"SkillEvaluator trial gate disabled by {disabled}; allowing hook.", file=sys.stderr)
    return 0
  session = str(payload.get("session_id", "")).strip()
  raw_skill = Path(file_path).expanduser().parent
  try:
    skill = canonical_skill(raw_skill)
  except (OSError, ValueError) as error:
    if session:
      obligation = {
        "schema_version": 1,
        "session": session,
        "skill_path": str(raw_skill),
        "skill_name": raw_skill.name,
        "edit_epoch_ns": time.time_ns(),
        "updated_at": iso_now(),
        "state_error": f"unsafe_skill_path:{type(error).__name__}",
      }
      try:
        safe_write_json(fallback_pending_path(session, raw_skill), obligation)
      except (OSError, ValueError):
        pass
    print(hook_output("PostToolUse", f"⚠️ SkillEvaluator trial 無法安全解析 SKILL.md path；Stop gate 會 fail closed。 path={raw_skill}"))
    return 0
  edit_epoch_ns = max(time.time_ns(), (skill / "SKILL.md").stat().st_mtime_ns)
  if session:
    obligation = {
      "schema_version": 1,
      "session": session,
      "skill_path": str(skill),
      "skill_name": skill.name,
      "edit_epoch_ns": edit_epoch_ns,
      "updated_at": iso_now(),
    }
    target = pending_path(session, skill)
    try:
      with pending_lock(target):
        safe_write_json(target, obligation)
      audit("eligible_edit", session=session, skill_path=str(skill), edit_epoch_ns=edit_epoch_ns)
    except (OSError, ValueError) as error:
      audit("pending_write_failed", session=session, skill_path=str(skill), reason=type(error).__name__)
      obligation["state_error"] = type(error).__name__
      try:
        safe_write_json(fallback_pending_path(session, skill), obligation)
        message = "⚠️ SkillEvaluator trial 無法建立 primary pending obligation；已建立 fallback infrastructure marker，Stop gate 會阻擋直到 state 修復。"
      except (OSError, ValueError):
        message = "⚠️ SkillEvaluator trial 的 primary 與 fallback state 都無法寫入；Stop gate 會檢查病態 state root 並 fail closed。"
      print(hook_output("PostToolUse", f"{message} skill={skill}"))
      return 0
  command = shlex.join([
    "python3",
    str(Path(__file__).resolve()),
    "run-skill",
    "--skill",
    str(skill),
    "--edit-epoch-ns",
    str(edit_epoch_ns),
    "--session",
    session or "manual",
  ])
  message = "🔎 SkillEvaluator trial：此 SKILL.md 已建立 T1/T2 obligation。整批修改完成後執行 runner；T1 或 infrastructure failure 會由獨立 Stop hook 阻擋，T2 finding 只需在最終回報呈現。"
  print(hook_output("PostToolUse", f"{message} 指令：{command}"))
  return 0


def metadata_kind(value):
  if isinstance(value, str):
    return value.strip().lower().replace("_", "-")
  if isinstance(value, dict):
    for key in ("kind", "source", "type"):
      kind = metadata_kind(value.get(key))
      if kind:
        return kind
  return ""


def userprompt_hook(payload):
  disabled = state_root() / "disabled"
  if disabled.exists() or disabled.is_symlink():
    return 0
  prompt = payload.get("prompt") if isinstance(payload.get("prompt"), str) else ""
  session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else ""
  source = metadata_kind(payload.get("source"))
  prompt_source = metadata_kind(payload.get("promptSource") if payload.get("promptSource") is not None else payload.get("prompt_source"))
  origin_kind = metadata_kind(payload.get("origin"))
  command_name = payload.get("command_name") if isinstance(payload.get("command_name"), str) else payload.get("commandName") if isinstance(payload.get("commandName"), str) else ""
  human_sources = {"", "user", "external", "prompt", "user-prompt", "typed", "human"}
  user_type = payload.get("userType")
  if (
    not session
    or source not in human_sources
    or prompt_source not in human_sources
    or origin_kind not in human_sources
    or command_name
    or payload.get("isMeta")
    or payload.get("isSidechain")
    or payload.get("isCompactSummary")
    or payload.get("isVisibleInTranscriptOnly")
    or user_type not in {None, "external"}
  ):
    return 0
  if any(marker in prompt for marker in ["[SYSTEM NOTIFICATION", "<task-notification>", "<system-reminder>", "<command-name>"]):
    return 0
  match = APPROVAL_PATTERN.fullmatch(prompt.strip())
  if not match:
    return 0
  requested = match.group(1)
  directory = state_root() / "pending" / object_digest(session)
  if not directory.exists() or directory.is_symlink() or not directory.is_dir():
    print(hook_output("UserPromptSubmit", "SkillEvaluator approval 未建立：此 session 沒有可核准的 pending Tier 1 failure。"))
    return 0
  candidates = []
  for path in sorted(directory.glob("*.json")):
    try:
      obligation = safe_read_json(path)
      status_value, receipt, _ = receipt_state(obligation)
      if status_value == "tier1_failed" and approval_id_for(obligation, receipt) == requested:
        candidates.append(path)
    except (OSError, ValueError, json.JSONDecodeError):
      continue
  if len(candidates) != 1:
    print(hook_output("UserPromptSubmit", "SkillEvaluator approval 未建立：approval id 不存在、已失效或不唯一。"))
    return 0
  pending = candidates[0]
  try:
    with pending_lock(pending):
      obligation = safe_read_json(pending)
      status_value, receipt, _ = receipt_state(obligation)
      if status_value != "tier1_failed" or approval_id_for(obligation, receipt) != requested:
        raise ValueError("approval binding changed")
      binding = approval_binding(obligation, receipt)
      spent = spent_permit_path(session, requested)
      if spent.exists() or spent.is_symlink():
        raise ValueError("permit was already consumed")
      permit = {
        "schema_version": 1,
        "kind": "tier1-human-override",
        "approval_id": requested,
        **binding,
        "issued_at": iso_now(),
        "expires_at": int(time.time()) + PERMIT_TTL_SECONDS,
        "consumed": False,
      }
      safe_write_json(permit_path(session, requested), permit)
  except (OSError, ValueError, json.JSONDecodeError):
    print(hook_output("UserPromptSubmit", "SkillEvaluator approval 未建立：permit state 無法安全寫入或 binding 已變更。"))
    return 0
  audit("human_approval_issued", session=session, skill_path=binding["skill_path"], approval_id=requested)
  print(hook_output("UserPromptSubmit", f"SkillEvaluator human permit 已建立：{requested}；15 分鐘內下一次 Stop 會驗證並單次消耗。"))
  return 0


def safe_read_json(path):
  flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
  descriptor = os.open(path, flags)
  try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
      raise ValueError(f"unsafe input path: {path}")
    chunks = []
    while chunk := os.read(descriptor, 1024 * 1024):
      chunks.append(chunk)
      if sum(len(item) for item in chunks) > MAX_JSON_BYTES:
        raise ValueError(f"input path is too large: {path}")
    return json.loads(b"".join(chunks).decode("utf-8"))
  finally:
    os.close(descriptor)


def safe_unlink(path):
  info = path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
    raise ValueError(f"unsafe removal path: {path}")
  path.unlink()


def valid_receipt_artifact(packet):
  status_value = packet.get("status") if isinstance(packet, dict) else None
  if status_value == "infrastructure_failure":
    return True
  artifact_path = packet.get("artifact_path")
  finding_count = packet.get("finding_count")
  if status_value not in {"passed", "failed", "findings"}:
    return False
  if isinstance(finding_count, bool) or not isinstance(finding_count, int) or finding_count < 0:
    return False
  if not isinstance(artifact_path, str):
    return False
  return is_regular_single_link(Path(artifact_path))


def receipt_state(obligation):
  skill = Path(str(obligation.get("skill_path", "")))
  pending_edit = obligation.get("edit_epoch_ns")
  path = receipt_path(skill, state_root(), obligation.get("session", ""), pending_edit)
  if not path.exists() and not path.is_symlink():
    return "missing", None, "missing receipt"
  try:
    receipt = safe_read_json(path)
  except (OSError, ValueError, json.JSONDecodeError):
    return "infrastructure_failure", None, "infrastructure failure: receipt is unreadable or unsafe"
  if not isinstance(receipt, dict):
    return "infrastructure_failure", None, "infrastructure failure: receipt contract is invalid"
  receipt_edit = receipt.get("edit_epoch_ns")
  started = receipt.get("run_started_ns")
  ended = receipt.get("run_ended_ns")
  tier1_packet = receipt.get("tier1")
  tier2_packet = receipt.get("tier2")
  contract_valid = (
    receipt.get("schema_version") == 1
    and receipt.get("kind") == "edit"
    and receipt.get("session") == obligation.get("session")
    and receipt.get("skill_path") == str(skill)
    and receipt.get("receipt_path") == str(path)
    and receipt.get("tool_version") == EXPECTED_VERSION
    and isinstance(tier1_packet, dict)
    and isinstance(tier2_packet, dict)
    and all(isinstance(value, int) for value in [pending_edit, receipt_edit, started, ended])
  )
  if not contract_valid:
    return "infrastructure_failure", receipt, "infrastructure failure: receipt contract is invalid"
  skill_file = skill / "SKILL.md"
  try:
    current_skill_mtime_ns, _ = file_stamp(skill_file)
  except (OSError, ValueError):
    return "infrastructure_failure", receipt, "infrastructure failure: current skill is unreadable or unsafe"
  if current_skill_mtime_ns > started:
    return "stale", receipt, "stale receipt: skill content changed"
  if not valid_receipt_artifact(tier1_packet) or not valid_receipt_artifact(tier2_packet):
    return "infrastructure_failure", receipt, "infrastructure failure: receipt artifact binding is invalid"
  if receipt_edit != pending_edit or started < receipt_edit or ended < started:
    return "stale", receipt, "stale receipt"
  status_value = receipt.get("status")
  tier1 = tier1_packet.get("status")
  tier2 = tier2_packet.get("status")
  if status_value == "infrastructure_failure" or tier1 == "infrastructure_failure" or tier2 == "infrastructure_failure":
    return "infrastructure_failure", receipt, "infrastructure failure"
  if status_value == "tier1_failed":
    if tier1 == "failed" and tier2 in {"passed", "findings"}:
      return "tier1_failed", receipt, "Tier 1 failure"
    return "infrastructure_failure", receipt, "infrastructure failure: inconsistent Tier 1 receipt"
  if status_value != "passed" or tier1 != "passed" or tier2 not in {"passed", "findings"}:
    return "infrastructure_failure", receipt, "infrastructure failure: unsupported receipt status"
  if tier2 == "findings":
    return "tier2_findings", receipt, "Tier 2 findings"
  return "passed", receipt, "passed"


def validate_pending_obligation(obligation, session):
  if not isinstance(obligation, dict) or obligation.get("schema_version") != 1:
    raise ValueError("pending obligation contract is invalid")
  if obligation.get("session") != session or not isinstance(obligation.get("session"), str):
    raise ValueError("pending obligation session is invalid")
  if not isinstance(obligation.get("skill_path"), str) or not obligation["skill_path"]:
    raise ValueError("pending obligation skill path is invalid")
  edit_epoch_ns = obligation.get("edit_epoch_ns")
  if isinstance(edit_epoch_ns, bool) or not isinstance(edit_epoch_ns, int) or edit_epoch_ns <= 0:
    raise ValueError("pending obligation edit epoch is invalid")
  return obligation


def process_pending(path, session):
  with pending_lock(path):
    obligation = validate_pending_obligation(safe_read_json(path), session)
    status_value, receipt, reason = receipt_state(obligation)
    skill_path = obligation["skill_path"]
    if status_value == "tier1_failed":
      spent_allowed = False
      try:
        spent_allowed, spent, approval_id = valid_spent_permit(obligation, receipt)
        if spent_allowed:
          permit_allowed = True
          permit = permit_path(session, approval_id)
        else:
          permit_allowed, permit, approval_id = valid_permit(obligation, receipt)
      except (OSError, ValueError, json.JSONDecodeError):
        permit_allowed, permit, approval_id = False, None, None
      if permit_allowed:
        binding = approval_binding(obligation, receipt)
        spent = spent_permit_path(session, approval_id)
        tombstone = {
          "schema_version": 1,
          "kind": "tier1-human-override-consumed",
          "approval_id": approval_id,
          **binding,
          "consumed_at": iso_now(),
        }
        try:
          if not spent_allowed:
            if spent.exists() or spent.is_symlink():
              raise ValueError("permit was already consumed")
            safe_write_json(spent, tombstone)
          if permit.exists() or permit.is_symlink():
            safe_unlink(permit)
          current = validate_pending_obligation(safe_read_json(path), session)
          if current != obligation:
            raise ValueError("pending obligation changed during consume")
          safe_unlink(path)
        except (OSError, ValueError, json.JSONDecodeError):
          return (obligation, "infrastructure failure: approved permit consume is incomplete and will retry"), None
        audit("allowed_by_user", session=session, skill_path=skill_path, approval_id=approval_id)
        return None, f"{skill_path}（user-approved exception {approval_id}；原 Tier 1 receipt 保持 FAIL）"
      if approval_id:
        finding_count = receipt.get("tier1", {}).get("finding_count", 0)
        artifact = receipt.get("tier1", {}).get("artifact_path", "unknown")
        return None, f"{skill_path}（Tier 1 FAIL；{finding_count} finding；artifact={artifact}；等待 top-level user 決策：SkillEvaluator 放行 {approval_id}）"
    if status_value in {"passed", "tier2_findings"}:
      try:
        safe_unlink(path)
      except (OSError, ValueError):
        return (obligation, "infrastructure failure: pending obligation could not be cleared"), None
      audit("allowed", session=session, skill_path=skill_path, receipt_status=status_value)
      if status_value == "tier2_findings":
        count = receipt.get("tier2", {}).get("finding_count", 0)
        return None, f"{skill_path}（Tier 2 advisory：{count} finding）"
      return None, None
    audit("blocked", session=session, skill_path=skill_path, status=status_value)
    return (obligation, reason), None


def stop_hook(payload):
  session = str(payload.get("session_id", "")).strip()
  if not session:
    print(json.dumps({"decision": "block", "reason": "⛔ SkillEvaluator Stop gate：hook payload 缺少 session_id。"}, ensure_ascii=False))
    return 0
  disabled = state_root() / "disabled"
  if disabled.exists() or disabled.is_symlink():
    print(f"SkillEvaluator trial gate disabled by {disabled}; allowing hook.", file=sys.stderr)
    return 0
  primary_root = state_root()
  secondary_root = fallback_root()
  for root, label in ((primary_root, "primary"), (secondary_root, "fallback")):
    if (root.exists() or root.is_symlink()) and (root.is_symlink() or not root.is_dir()):
      print(json.dumps({"decision": "block", "reason": f"⛔ SkillEvaluator Stop gate：{label} state root 不安全；修復 state 或建立 disabled sentinel 後再結束。"}, ensure_ascii=False))
      return 0
  directories = []
  for root in (primary_root, secondary_root):
    directory = root / "pending" / object_digest(session)
    if not directory.exists() and not directory.is_symlink():
      continue
    if directory.is_symlink() or not directory.is_dir():
      print(json.dumps({"decision": "block", "reason": "⛔ SkillEvaluator Stop gate：pending state path 不安全；移除病態 path 或建立 disabled sentinel 後再結束。"}, ensure_ascii=False))
      return 0
    if directory not in directories:
      directories.append(directory)
  if not directories:
    return 0
  blocked = []
  advisories = []
  for directory in directories:
    try:
      entries = sorted(directory.iterdir())
    except OSError:
      print(json.dumps({"decision": "block", "reason": "⛔ SkillEvaluator Stop gate：pending state 無法枚舉；修復 state 或建立 disabled sentinel 後再結束。"}, ensure_ascii=False))
      return 0
    unexpected = [path for path in entries if path.suffix != ".json"]
    if unexpected:
      blocked.append((None, "infrastructure failure: pending directory contains unknown entries"))
    for path in (path for path in entries if path.suffix == ".json"):
      try:
        blocked_entry, advisory = process_pending(path, session)
      except (OSError, ValueError, json.JSONDecodeError):
        blocked.append((None, "infrastructure failure: pending obligation is unreadable, unsafe, or locked"))
        continue
      if blocked_entry:
        blocked.append(blocked_entry)
      if advisory:
        advisories.append(advisory)
    try:
      if directory.exists() and not any(directory.iterdir()):
        directory.rmdir()
    except OSError:
      pass
  if blocked:
    items = []
    for obligation, reason in blocked:
      if obligation is None:
        items.append(reason)
        continue
      skill_path = str(obligation.get("skill_path", "unknown"))
      edit_epoch_ns = int(obligation.get("edit_epoch_ns", 0))
      command = " ".join([
        "python3",
        shlex.quote(str(Path(__file__).resolve())),
        "run-skill",
        "--skill",
        shlex.quote(skill_path),
        "--edit-epoch-ns",
        str(edit_epoch_ns),
        "--session",
        shlex.quote(session),
      ])
      items.append(f"{skill_path}：{reason}；修復指令：{command}")
    print(json.dumps({"decision": "block", "reason": "⛔ SkillEvaluator Stop gate：" + "；".join(items)}, ensure_ascii=False))
    return 0
  if advisories:
    message = "ℹ️ SkillEvaluator completion notice：" + "；".join(advisories)
    if any("等待 top-level user 決策" in advisory for advisory in advisories):
      print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    else:
      print(hook_output("Stop", message))
  return 0


def hook_command():
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError):
    return 0
  event = str(payload.get("hook_event_name", ""))
  if event == "PostToolUse":
    return posttool_hook(payload)
  if event == "UserPromptSubmit":
    return userprompt_hook(payload)
  if event == "Stop":
    return stop_hook(payload)
  return 0


def calendar_date(value):
  if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
    raise argparse.ArgumentTypeError("date must be YYYY-MM-DD")
  try:
    datetime.strptime(value, "%Y-%m-%d")
  except ValueError as error:
    raise argparse.ArgumentTypeError("date must be a valid calendar date") from error
  return value


def parser():
  root = argparse.ArgumentParser()
  commands = root.add_subparsers(dest="command", required=True)
  edit = commands.add_parser("run-skill")
  edit.add_argument("--skill", required=True)
  edit.add_argument("--edit-epoch-ns", required=True, type=int)
  edit.add_argument("--session", default="manual")
  weekly = commands.add_parser("weekly")
  weekly.add_argument("--collection", required=True)
  weekly.add_argument("--date", required=True, type=calendar_date)
  weekly.add_argument("--summary", required=True)
  weekly.add_argument("--workers", type=int, choices=range(1, 9), default=2)
  tier3 = commands.add_parser("tier3")
  tier3.add_argument("--skill", required=True)
  tier3.add_argument("--results-dir")
  commands.add_parser("hook")
  return root


def main():
  args = parser().parse_args()
  if args.command == "run-skill":
    return run_skill(args)
  if args.command == "weekly":
    return run_weekly(args)
  if args.command == "tier3":
    return run_tier3(args)
  if args.command == "hook":
    return hook_command()
  return 64


if __name__ == "__main__":
  raise SystemExit(main())
