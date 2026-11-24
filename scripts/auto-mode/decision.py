#!/usr/bin/env python3
import argparse
import json
import sys
from typing import Literal


Approval = Literal["allow-auto", "downweight", "require-human"]
ContextMode = Literal["snapshot", "materials"]

# Callers supply nonempty action IDs; downweighted and web-gpt-pro IDs are shared with auto-mode-inject.py (SSOT).
DOWNWEIGHTED_ACTIONS = frozenset({
  "git-force-push", "git-hard-reset", "git-restore-worktree", "git-delete-branch",
  "git-rebase", "git-amend-pushed", "git-delete-repo", "git-merge-pr", "git-shared-main-push",
  "publish-outward", "upstream-pr-publish", "upstream-public-fork-push", "upstream-pr-comment",
  "company-repo-push", "company-pr-create", "send-message", "acme-db-write", "third-party-fable",
})
WEB_GPT_PRO = "web-gpt-pro"
PERSONAL_PLAN_TYPES = frozenset({"pro"})


def gpt_pro_context_mode(preflight: object) -> ContextMode | None:
  """Select the context mode for a confirmed personal workspace, or return None."""
  if not isinstance(preflight, dict) or preflight.get("status") != "ok":
    return None
  for field in ("workspaceId", "workspaceName", "planType"):
    value = preflight.get(field)
    if not isinstance(value, str) or value.strip().casefold() in {"", "unknown"}:
      return None
  if preflight["planType"].strip().casefold() not in PERSONAL_PLAN_TYPES:
    return None
  devspace = preflight.get("devspace")
  if devspace == "available":
    return "snapshot"
  if devspace in ("unavailable", "unknown"):
    return "materials"
  return None


def decide(*, stop_kind: str, has_recommendation: bool, has_default: bool, action: str,
           enabled: bool, preflight: object = None) -> Approval:
  """Decide a stop with a nonempty kind and an exact action ID."""
  if (
    enabled is not True
    or type(has_recommendation) is not bool
    or type(has_default) is not bool
    or not isinstance(stop_kind, str) or not stop_kind.strip()
    or not isinstance(action, str) or not action.strip()
  ):
    return "require-human"
  normalized_action = action.strip().casefold()
  if normalized_action in DOWNWEIGHTED_ACTIONS:
    return "downweight"
  if normalized_action == WEB_GPT_PRO:
    if action != WEB_GPT_PRO or gpt_pro_context_mode(preflight) is None:
      return "downweight"
  if action != action.strip():
    return "require-human"
  if has_recommendation is True or has_default is True:
    return "allow-auto"
  return "require-human"


def reject_json_constant(constant: str) -> None:
  raise ValueError(f"invalid JSON constant: {constant}")


def main():
  parser = argparse.ArgumentParser(allow_abbrev=False, description="Evaluate an auto mode stop from JSON on stdin.")
  parser.add_argument("command", choices=("decide",))
  parser.parse_args()
  context_mode = None
  try:
    payload = json.load(sys.stdin, parse_constant=reject_json_constant)
    if not isinstance(payload, dict):
      raise TypeError("payload must be an object")
    decision = decide(**payload)
  except (ValueError, TypeError, RecursionError):
    print(json.dumps({"decision": "require-human", "context_mode": None}))
    return 2
  if decision == "allow-auto" and payload["action"] == WEB_GPT_PRO:
    context_mode = gpt_pro_context_mode(payload.get("preflight"))
  print(json.dumps({"decision": decision, "context_mode": context_mode}))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
