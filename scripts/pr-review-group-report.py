#!/usr/bin/env python3

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path


CLAUDE_ROOT = Path(__file__).resolve().parent.parent
MUTATION_CORE = CLAUDE_ROOT / "skills/bitbucket-pr-mutation/scripts/bitbucket_pr_workflow/core.py"
SCHEMA_LINE = "**Report projection schema**: 3"
SET_IDENTITY_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
LOCATIONS_TITLE = "跨目標位置"
LOCATION_HEADERS = ("group_id", "finding_uid", "target_identity", "file", "line", "source")
ZERO_FINDING_MARKER = "本輪零 finding：跨目標位置表沒有資料列，這是正常結果，不是表格損壞。"
PRIOR_REVIEW_TITLE = "上一輪 findings 對帳"
INLINE_TITLE = "Inline Comments per Finding"
SUMMARY_NOTICE = "auto-fix 只是處置建議；沒有使用者另行下令，不修改 code、commit、push 或 PR。"
LINE_SENTINEL = "需人工確認（anchor 未在綁定來源中比中或證據 binding 失效）"
CC_SOURCES = ("cc",)
NON_CC_SOURCES = ("codex", "gemini", "web")
C4_SOURCE = "spec-compliance"
ACTIONS = ("auto-fix", "ask-user", "no-op")
ACTIONABLE_ACTIONS = ("auto-fix", "ask-user")
VERIFICATION_VERDICTS = ("CONFIRMED", "REFUTED", "PARTIAL", "OUT_OF_SCOPE", "INCONCLUSIVE")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
PRIORITY_RANK = {"Must Fix": 0, "Should Fix": 1, "Nice to Have": 2, "參考用": 3}
STATUSES = ("FIXED", "STILL_OPEN", "STALE")
VERSION_STATES = ("current", "drifted", "unavailable")
VERSION_ENTRY = re.compile(r"(\S+)=head:([0-9a-f]{40}|none)\|base:([0-9a-f]{40}|none)\|state:(current|drifted|unavailable)")
SAFE_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MATERIALS_DIRNAME = "materials"
RANGE_MODE = "merged-range"
RANGE_SCOPE_RULE = "landed-files-in-range-v1"
FULL_SHA = re.compile(r"[0-9a-f]{40}")
ATTRIBUTION_TITLE = "歸因三欄"
ATTRIBUTION_HEADERS = ("finding_uid", "target_identity", "目前問題位置", "相關程式來源", "缺陷引入歸因")
MISSING_REASON = "缺失型 finding：不指派引入者，附近程式作者不是責任人"


def load_mutation_core():
  spec = importlib.util.spec_from_file_location("bitbucket_pr_workflow_core", MUTATION_CORE)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def _local_make_finding_uid(file_path, anchor, root_cause):
  normalized_cause = re.sub(r'\s+', ' ', str(root_cause)).strip()
  payload = '\0'.join((str(file_path), str(anchor), normalized_cause))
  return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]


def resolve_make_finding_uid():
  if MUTATION_CORE.exists():
    return load_mutation_core().make_finding_uid
  return _local_make_finding_uid


MAKE_FINDING_UID = resolve_make_finding_uid()


def normalize_root_cause(value):
  return re.sub(r"\s+", " ", str(value or "")).strip()


def normalized_choice(allowed, *values):
  for value in values:
    normalized = str(value or "").strip().upper()
    if normalized in allowed:
      return normalized
  return ""


def first_text(*values):
  for value in values:
    text = str(value or "").strip()
    if text:
      return text
  return ""


def verification_fields(finding):
  return {
    "verification_verdict": normalized_choice(
      VERIFICATION_VERDICTS,
      finding.get("verification_verdict"),
      finding.get("cc_verdict"),
      finding.get("codex_verdict"),
    ),
    "verification_evidence": first_text(
      finding.get("verification_evidence"),
      finding.get("cc_evidence"),
      finding.get("codex_evidence"),
    ),
    "original_severity": normalized_choice(
      SEVERITIES,
      finding.get("original_severity"),
      finding.get("severity"),
    ),
    "corrected_severity": normalized_choice(SEVERITIES, finding.get("corrected_severity")),
    "severity_reason": first_text(finding.get("severity_reason")),
  }


def single_pr_finding_uid(file_path, anchor, root_cause):
  return MAKE_FINDING_UID(str(file_path), str(anchor), str(root_cause))


def finding_uid(file_path, anchor, root_cause, target_identity=None):
  if not target_identity:
    return single_pr_finding_uid(file_path, anchor, root_cause)
  payload = "\0".join((
    str(target_identity), str(file_path), str(anchor), normalize_root_cause(root_cause),
  ))
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def location_key(location):
  return (
    str(location.get("target_identity") or ""),
    str(location.get("file") or ""),
    location.get("line"),
  )


def normalize_location(finding):
  return {
    "target_identity": finding["target_identity"],
    "file": finding["file"],
    "line": finding.get("line"),
    "anchor": str(finding.get("anchor") or ""),
    "source": str(finding.get("source") or ""),
    "finding_uid": finding_uid(
      finding["file"], finding.get("anchor") or "", finding["root_cause"], finding["target_identity"],
    ),
  }


def group_disposition(sources, strict_liability):
  if strict_liability:
    return "stand"
  has_cc = any(source in CC_SOURCES for source in sources)
  has_non_cc = any(source in NON_CC_SOURCES for source in sources)
  if has_cc and has_non_cc:
    return "baseline_check"
  return "independent_recheck"


def group_id_for(root_cause, locations, chain_id=None, anchor=""):
  keys = sorted("\0".join(str(part) for part in location_key(location)) for location in locations)
  discriminator = f"chain:{chain_id}" if chain_id else f"solo:{anchor}"
  payload = "\0".join((normalize_root_cause(root_cause), discriminator, *keys))
  return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def normalize_targets(targets):
  result = []
  seen = set()
  for target in targets or []:
    identity = str(target.get("target_identity") or "")
    if not identity or identity in seen:
      continue
    seen.add(identity)
    state = str(target.get("version_state") or "current")
    if state not in VERSION_STATES:
      state = "unavailable"
    result.append({
      "target_identity": identity,
      "head": target.get("head"),
      "base": target.get("base"),
      "version_state": state,
    })
  return sorted(result, key=lambda target: target["target_identity"])


def version_entry(target):
  key = target.get("case_token") or target["target_identity"]
  head = target["head"] if re.fullmatch(r"[0-9a-f]{40}", str(target["head"] or "")) else "none"
  base = target["base"] if re.fullmatch(r"[0-9a-f]{40}", str(target["base"] or "")) else "none"
  return f"{key}=head:{head}|base:{base}|state:{target['version_state']}"


def route_findings(findings, declared_targets, attribute=None):
  declared = set(declared_targets)
  admitted = []
  refused = []
  for finding in findings or []:
    source = str(finding.get("source") or "")
    if source == C4_SOURCE and not finding.get("reducer_validated"):
      refused.append({"reason_code": "C4_NOT_VALIDATED", "target_identity": finding.get("target_identity"),
                      "file": finding.get("file")})
      continue
    if not finding.get("target_identity") or not finding.get("file") or not finding.get("root_cause"):
      refused.append({"reason_code": "FINDING_INCOMPLETE", "target_identity": finding.get("target_identity"),
                      "file": finding.get("file")})
      continue
    if str(finding["target_identity"]) not in declared:
      refused.append({"reason_code": "UNDECLARED_TARGET", "target_identity": finding["target_identity"],
                      "file": finding.get("file")})
      continue
    admitted.append(finding)

  buckets = {}
  order = []
  for finding in admitted:
    chain_id = str(finding.get("failure_chain_id") or "").strip()
    if chain_id:
      key = ("chain", chain_id, normalize_root_cause(finding["root_cause"]))
    else:
      key = ("solo", str(finding["target_identity"]), str(finding["file"]),
             str(finding.get("anchor") or ""), normalize_root_cause(finding["root_cause"]))
    bucket = buckets.get(key)
    if bucket is None:
      bucket = {
        "anchor": str(finding.get("anchor") or "") if not chain_id else "",
        "root_cause": key[-1], "chain_id": chain_id or None, "locations": [], "sources": [],
        "perspectives": [], "strict_liability": False,
      }
      buckets[key] = bucket
      order.append(key)
    bucket["strict_liability"] = bucket["strict_liability"] or bool(finding.get("strict_liability"))
    bucket["sources"].append(str(finding.get("source") or ""))
    suggestion = str(finding.get("suggestion") or "") if str(finding.get("suggestion") or "") in PRIORITY_RANK else "參考用"
    action = str(finding.get("action") or "") if str(finding.get("action") or "") in ACTIONS else "ask-user"
    location = normalize_location(finding)
    existing = next((item for item in bucket["locations"] if location_key(item) == location_key(location)), None)
    if existing is None:
      if attribute:
        location["attribution"] = attribute(finding)
      bucket["locations"].append(location)
      existing = location
    # 同 repo 可有多個位置，UID 在這裡綁定；產表時用 target_identity 反查會讓後一個位置蓋掉前一個
    bucket["perspectives"].append({
      "source": str(finding.get("source") or ""),
      "target_identity": str(finding["target_identity"]),
      "finding_uid": existing["finding_uid"],
      "suggestion": suggestion,
      "action": action,
      "action_reason": str(finding.get("action_reason") or "需人工判斷"),
      "title": str(finding.get("title") or normalize_root_cause(finding["root_cause"])),
      "comment": str(finding.get("comment") or normalize_root_cause(finding["root_cause"])),
      **verification_fields(finding),
    })

  groups = []
  for key in order:
    bucket = buckets[key]
    locations = sorted(bucket["locations"], key=location_key)
    sources = sorted({source for source in bucket["sources"] if source})
    perspectives = bucket["perspectives"]
    top = min(
      perspectives,
      key=lambda item: (PRIORITY_RANK.get(item["suggestion"], 3), item["source"]),
    )
    groups.append({
      "group_id": group_id_for(
        bucket["root_cause"], locations, bucket["chain_id"], bucket["anchor"],
      ),
      "root_cause": bucket["root_cause"],
      "anchor": bucket["anchor"],
      "title": top["title"],
      "sources": sources,
      "routed_to": group_disposition(sources, bucket["strict_liability"]),
      "suggestion": min((item["suggestion"] for item in perspectives),
                        key=lambda value: PRIORITY_RANK.get(value, 3)),
      "action": top["action"],
      "action_reason": top["action_reason"],
      "comment": top["comment"],
      "perspectives": perspectives,
      "chain_id": bucket["chain_id"],
      "locations": locations,
    })
  groups.sort(key=lambda group: (PRIORITY_RANK[group["suggestion"]], group["group_id"]))
  return {"groups": groups, "refused": refused}


def prior_rows_are_loadable(prior):
  for row in prior.get("findings") or []:
    if str(row.get("action") or "") not in ACTIONABLE_ACTIONS:
      continue
    if not row.get("finding_uid") or not row.get("file") or not row.get("root_cause"):
      return False
    if not re.fullmatch(r"[0-9a-f]{20}", str(row["finding_uid"])):
      return False
  return True


def reconcile_prior(prior, targets, fresh_findings, recheck_responses, current_set_identity):
  prior = prior or {}
  rows = [row for row in prior.get("findings") or []
          if str(row.get("action") or "") in ACTIONABLE_ACTIONS]
  if not rows:
    return {"continuity": "n-a", "scope": None, "reason": None,
            "rows": [], "tally": {status: 0 for status in STATUSES},
            "prior_inputs": [], "expanded_targets": []}
  if not prior_rows_are_loadable(prior):
    return {"continuity": "skipped", "scope": None, "reason": "prior audit rows lack stable uid / action / problem / file",
            "rows": [], "tally": {status: 0 for status in STATUSES},
            "prior_inputs": [], "expanded_targets": []}

  prior_set = prior.get("set_identity")
  scope = "legacy" if not prior_set else ("set" if prior_set == current_set_identity else "stale-set")
  current = {target["target_identity"] for target in targets}
  fresh = {
    finding_uid(finding.get("file"), finding.get("anchor") or "", finding.get("root_cause") or "",
                finding.get("target_identity"))
    for finding in fresh_findings or []
  }

  disposition = []
  for row in rows:
    target_identity = str(row.get("target_identity") or "")
    legacy_uid = str(row["finding_uid"])
    group_uid = None
    if target_identity in current:
      group_uid = finding_uid(row.get("file"), row.get("anchor") or "", row.get("root_cause") or "",
                              target_identity)
    display_uid = group_uid or legacy_uid
    response = (recheck_responses or {}).get(display_uid)
    if response is None and group_uid is not None:
      response = (recheck_responses or {}).get(legacy_uid)
    verdict = str(response.get("status") or "") if isinstance(response, dict) else ""
    evidence = str(response.get("evidence") or "") if isinstance(response, dict) else ""
    if scope == "stale-set":
      status, evidence = "STALE", "set identity changed; prior finding not carried forward"
    elif group_uid is None:
      status, evidence = "STALE", "target of prior finding absent this round (missing target / material)"
    elif verdict in STATUSES:
      status = verdict
    else:
      status, evidence = "STALE", "no independent recheck evidence"
    if status == "FIXED" and not evidence:
      status, evidence = "STALE", "recheck claimed fixed without current evidence"
    disposition.append({
      "finding_uid": display_uid,
      "legacy_uid": legacy_uid,
      "target_identity": target_identity,
      "problem": normalize_root_cause(row.get("root_cause")),
      "status": status,
      "evidence": evidence,
      "rediscovered": bool(group_uid and group_uid in fresh),
    })

  tally = {status: sum(row["status"] == status for row in disposition) for status in STATUSES}
  return {"continuity": "checked", "scope": scope, "reason": None,
          "rows": disposition, "tally": tally,
          "prior_inputs": [], "expanded_targets": []}


def canonical_set_identity(targets):
  joined = "\n".join(sorted(target["target_identity"] for target in targets))
  return f"sha256:{hashlib.sha256(joined.encode('utf-8')).hexdigest()}"


def stable_id(set_identity):
  return hashlib.sha256(str(set_identity).encode("utf-8")).hexdigest()[:12]


def is_range_payload(payload):
  entries = list(payload.get("targets") or []) + list(payload.get("no_net_diff") or [])
  return bool(payload.get("no_net_diff")) or any(entry.get("kind") == "range" for entry in entries)


def range_case_token(identity, prs):
  return "{}+prs:{}+scope:{}".format(identity, ",".join(str(pr) for pr in prs), RANGE_SCOPE_RULE)


def normalize_range_target(entry, net_diff):
  identity = str(entry.get("target_identity") or "")
  start = entry.get("start") or {}
  end = entry.get("end") or {}
  prs = sorted({int(pr["pr"]) for pr in entry.get("related_prs") or [] if pr.get("pr") is not None})
  if not identity or not prs:
    raise ValueError("range target requires target identity and source PRs")
  if not FULL_SHA.fullmatch(str(start.get("sha") or "")) or not FULL_SHA.fullmatch(str(end.get("sha") or "")):
    raise ValueError("range target requires full R/T SHAs")
  state = str(entry.get("version_state") or "current")
  entry_files = sorted(entry.get("entry_files") or [], key=lambda item: str(item.get("path") or ""))
  return {
    "target_identity": identity,
    "case_token": range_case_token(identity, prs),
    "head": end["sha"],
    "base": start["sha"],
    "version_state": state if state in VERSION_STATES else "unavailable",
    "target_branch": str(entry.get("target_branch") or ""),
    "start": {"sha": start["sha"], "source": str(start.get("source") or ""),
              "detail": str(start.get("detail") or "")},
    "end": {"sha": end["sha"], "ref": str(end.get("ref") or "")},
    "source_prs": prs,
    "net_diff": net_diff,
    "entry_file_count": len(entry_files),
  }


def normalize_range_targets(payload):
  entries = [(entry, True) for entry in payload.get("targets") or []]
  entries += [(entry, False) for entry in payload.get("no_net_diff") or []]
  if any(net_diff and entry.get("kind") != "range" for entry, net_diff in entries):
    raise ValueError("range report cannot mix PR targets")
  result = {}
  for entry, net_diff in entries:
    target = normalize_range_target(entry, net_diff)
    result.setdefault(target["target_identity"], target)
  return sorted(result.values(), key=lambda target: target["target_identity"])


def range_attribution(finding, target):
  missing = bool(finding.get("missing"))
  current = {"file": str(finding["file"]), "line": finding.get("line"), "commit": target["head"]}
  evidence = finding.get("r_evidence")
  if isinstance(evidence, dict) and evidence.get("file"):
    current["r_evidence"] = {"file": str(evidence["file"]), "line": evidence.get("line"),
                             "commit": target["base"]}
  sources = []
  for entry in finding.get("code_source") or []:
    prs = []
    for pr in entry.get("prs") or []:
      item = {"pr": pr.get("pr")}
      if pr.get("author"):
        item["author"] = str(pr["author"])
      if pr.get("base_ref"):
        item["target_branch_match"] = str(pr["base_ref"]) == target["target_branch"]
      prs.append(item)
    sources.append({"commit": str(entry.get("commit") or ""), "prs": prs})
  claim = finding.get("introduction") if isinstance(finding.get("introduction"), dict) else {}
  confirmed = (not missing and str(claim.get("status") or "") == "confirmed"
               and FULL_SHA.fullmatch(str(claim.get("commit") or "")) and claim.get("pr") is not None)
  if confirmed:
    introduction = {"status": "confirmed", "commit": claim["commit"], "pr": claim["pr"],
                    "evidence": str(claim.get("evidence") or "")}
    if claim.get("author"):
      introduction["author"] = str(claim["author"])
  else:
    reason = MISSING_REASON if missing else first_text(claim.get("reason"), "未提供可核對的引入 commit 與 PR")
    introduction = {"status": "unconfirmed", "reason": reason}
  return {"missing": missing, "current_location": current, "code_source": sources,
          "introduction": introduction}


def build_range_set(payload):
  targets = normalize_range_targets(payload)
  if not targets:
    raise ValueError("range report requires at least one range target")
  joined = "\n".join(sorted(target["case_token"] for target in targets))
  set_identity = f"sha256:{hashlib.sha256(joined.encode('utf-8')).hexdigest()}"
  by_identity = {target["target_identity"]: target for target in targets}
  routed = route_findings(
    payload.get("findings") or [], list(by_identity),
    lambda finding: range_attribution(finding, by_identity[str(finding["target_identity"])]),
  )
  return finish_set(payload, set_identity, targets, routed, {
    "mode": RANGE_MODE,
    "scope_rule": RANGE_SCOPE_RULE,
    "report_stem": f"set-{set_identity[7:19]}-review",
  })


def finish_set(payload, set_identity, targets, routed, extra=None):
  history = reconcile_prior(
    payload.get("prior_report"), targets, payload.get("findings") or [],
    payload.get("recheck_responses") or {}, set_identity,
  )
  incomplete = sorted(target["target_identity"] for target in targets
                      if target["version_state"] == "unavailable")
  return {
    "set_identity": set_identity,
    "stable_id": set_identity[7:19],
    **(extra or {}),
    "targets": targets,
    "groups": routed["groups"],
    "refused": routed["refused"],
    "history": history,
    "completeness": "INCOMPLETE" if incomplete else "COMPLETE",
    "incomplete_targets": incomplete,
    "grants": {"modify_code": False, "comment_on_prs": False, "multi_target_fanout": False},
  }


def build_set(payload):
  if is_range_payload(payload):
    return build_range_set(payload)
  set_identity = str(payload.get("set_identity") or "")
  if not SET_IDENTITY_PATTERN.fullmatch(set_identity):
    raise ValueError("set identity must be sha256:<64-hex>")
  targets = normalize_targets(payload.get("targets") or [])
  if not targets:
    raise ValueError("group report requires at least one bound target")
  derived = canonical_set_identity(targets)
  if set_identity != derived:
    raise ValueError("set identity does not match canonical target identities")
  routed = route_findings(payload.get("findings") or [], [target["target_identity"] for target in targets])
  return finish_set(payload, set_identity, targets, routed)


def cell(value):
  return str(value if value is not None else "").replace("|", "\\|")


def continuity_header(history):
  if history["continuity"] == "n-a":
    return "**Prior review continuity**: N-A (no prior audit)"
  if history["continuity"] == "skipped":
    return f"**Prior review continuity**: SKIPPED ({history['reason']})"
  tally = history["tally"]
  return (f"**Prior review continuity**: CHECKED (fixed {tally['FIXED']} / "
          f"still-open {tally['STILL_OPEN']} / stale {tally['STALE']})")


def continuity_section(history):
  if history["continuity"] == "n-a":
    return "N-A — no prior audit"
  if history["continuity"] == "skipped":
    return f"SKIPPED — {history['reason']}"
  if sum(history["tally"].values()) == 0:
    return "CHECKED — 0 actionable findings"
  lines = ["| 前輪 finding_uid | 問題 | 狀態 | 本輪證據 |", "|---|---|---|---|"]
  for row in sorted(history["rows"], key=lambda item: (item["status"], item["finding_uid"])):
    lines.append("| {} | {} | {} | {} |".format(
      cell(row["finding_uid"]), cell(row["problem"]), cell(row["status"]), cell(row["evidence"]),
    ))
  return "\n".join(lines)


def line_value(location):
  line = location.get("line")
  if isinstance(line, int) and not isinstance(line, bool) and line >= 1:
    return str(line)
  return LINE_SENTINEL


def range_header(targets):
  return [
    "**Range R/T**: " + "; ".join(
      f"{target['target_identity']}=R:{target['base']}|T:{target['head']}|T-ref:{target['end']['ref']}"
      for target in targets),
    "**Range R source**: " + "; ".join(
      f"{target['target_identity']}={target['start']['source']}（{target['start']['detail']}）"
      for target in targets),
    f"**Range scope**: rule={RANGE_SCOPE_RULE}; " + "; ".join(
      "{}=prs:{}|entry-files:{}|net-diff:{}".format(
        target["target_identity"], ",".join(f"#{pr}" for pr in target["source_prs"]),
        target["entry_file_count"], "yes" if target["net_diff"] else "no")
      for target in targets),
  ]


def location_text(file_path, line):
  return f"{file_path}:{line_value({'line': line})}"


def attribution_cells(attribution):
  current = attribution["current_location"]
  place = location_text(current["file"], current["line"])
  evidence = current.get("r_evidence")
  if evidence:
    place = (f"{place}（T 受影響位置）；R 舊證據 "
             f"{location_text(evidence['file'], evidence['line'])} @ {evidence['commit']}")
  sources = []
  for entry in attribution["code_source"]:
    prs = []
    for pr in entry["prs"]:
      text = f"#{pr['pr']}" + (f" @{pr['author']}" if pr.get("author") else "")
      if pr.get("target_branch_match") is False:
        text += "（目的分支不符）"
      prs.append(text)
    sources.append(f"{entry['commit'][:12]} → " + ", ".join(prs) if prs else entry["commit"][:12])
  source_text = "; ".join(sources) or "未提供"
  if attribution["missing"] and sources:
    source_text = f"附近程式，僅供定位：{source_text}"
  introduction = attribution["introduction"]
  if introduction["status"] == "confirmed":
    intro_text = f"已確認：{introduction['commit'][:12]} #{introduction['pr']}"
    if introduction.get("evidence"):
      intro_text += f"（{introduction['evidence']}）"
  else:
    intro_text = f"未確認：{introduction['reason']}"
  return place, source_text, intro_text


def attribution_section(groups):
  lines = [f"## {ATTRIBUTION_TITLE}", "",
           "| " + " | ".join(ATTRIBUTION_HEADERS) + " |",
           "|" + "---|" * len(ATTRIBUTION_HEADERS)]
  for group in groups:
    for location in group["locations"]:
      lines.append("| {} | {} | {} | {} | {} |".format(
        cell(location["finding_uid"]), cell(location["target_identity"]),
        *(cell(value) for value in attribution_cells(location["attribution"])),
      ))
  return lines


def render_draft(payload):
  data = build_set(payload)
  ranged = data.get("mode") == RANGE_MODE
  lines = [
    f"# Review set {data['stable_id']} Code Review 比較報告",
    "",
    SCHEMA_LINE,
    *([f"**Review mode**: {RANGE_MODE}"] if ranged else []),
    f"**Review set identity**: {data['set_identity']}",
    "**Review set targets**: " + " · ".join(
      target.get("case_token") or target["target_identity"] for target in data["targets"]),
    "**Target versions**: " + "; ".join(version_entry(target) for target in data["targets"]),
    *(range_header(data["targets"]) if ranged else []),
    continuity_header(data["history"]),
  ]
  for extra in payload.get("state_lines") or []:
    lines.append(str(extra))

  lines.extend(["", f"## {LOCATIONS_TITLE}", "",
                "| " + " | ".join(LOCATION_HEADERS) + " |",
                "|" + "---|" * len(LOCATION_HEADERS)])
  if not any(group["locations"] for group in data["groups"]):
    lines.append(ZERO_FINDING_MARKER)
  for group in data["groups"]:
    for location in group["locations"]:
      lines.append("| {} | {} | {} | {} | {} | {} |".format(
        cell(group["group_id"]), cell(location["finding_uid"]), cell(location["target_identity"]),
        cell(location["file"]), cell(line_value(location)), cell(location["source"]),
      ))

  lines.extend(["", f"## {PRIOR_REVIEW_TITLE}", "", continuity_section(data["history"])])

  lines.extend(["", "## 來源與分歧", "",
                "| finding_uid | target_identity | source | 驗證裁決 | 驗證證據 | 原始 severity | 校正 severity | severity 理由 | 最終建議 | Action | Action 理由 | 修法 |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|"])
  for group in data["groups"]:
    for perspective in group["perspectives"]:
      lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | `{}` | {} | {} |".format(
        cell(perspective["finding_uid"]), cell(perspective["target_identity"]),
        cell(perspective["source"]), cell(perspective["verification_verdict"]),
        cell(perspective["verification_evidence"]), cell(perspective["original_severity"]),
        cell(perspective["corrected_severity"]), cell(perspective["severity_reason"]),
        cell(perspective["suggestion"]), perspective["action"],
        cell(perspective["action_reason"]), cell(perspective["comment"]),
      ))

  if ranged:
    lines.extend(["", *attribution_section(data["groups"])])

  lines.extend(["", "## 發現總覽", "",
                "| # | 問題 | 最終建議 | Action | Action 理由 |", "|---|---|---|---|---|"])
  for index, group in enumerate(data["groups"], start=1):
    lines.append("| F-{:02d} | {} | {} | `{}` | {} |".format(
      index, cell(group["root_cause"]), cell(group["suggestion"]), group["action"],
      cell(group["action_reason"]),
    ))
  lines.append("")
  lines.append(SUMMARY_NOTICE)
  lines.append("")
  for index, group in enumerate(data["groups"], start=1):
    lines.append("F-{:02d} finding_uid: {} action={}{}".format(
      index, group["group_id"], group["action"],
      " inline=none" if group["action"] == "no-op" else "",
    ))

  lines.extend(["", f"### {INLINE_TITLE}", ""])
  for index, group in enumerate(data["groups"], start=1):
    if group["action"] == "no-op":
      continue
    primary = group["locations"][0]
    lines.extend([
      f"#### #{index} {group['title']}",
      f"**File**: {primary['file']}",
      f"**Line**: {line_value(primary)}",
      "",
      "**Comment**:",
      "```",
      str(group["comment"]),
      "```",
      "",
    ])
  return "\n".join(lines).rstrip() + "\n"


def cleanup(payload):
  state_root = payload.get("state_root")
  run_id = str(payload.get("run_id") or "")
  keep = sorted({str(value) for value in payload.get("keep") or []})
  if not state_root or not SAFE_SLUG.match(run_id) or ".." in run_id:
    return {"removed": [], "kept": keep, "reason_codes": ["CLEANUP_NOT_FOUND"]}
  resolved_state_root = Path(str(state_root)).expanduser().resolve(strict=False)
  materials_root = resolved_state_root / MATERIALS_DIRNAME
  lexical_base = materials_root / run_id
  if lexical_base.is_symlink():
    return {"removed": [], "kept": keep, "reason_codes": ["CLEANUP_ROOT_OUT_OF_SCOPE"]}
  try:
    materials_base = lexical_base.resolve(strict=False)
  except (OSError, RuntimeError):
    return {"removed": [], "kept": keep, "reason_codes": ["CLEANUP_ROOT_OUT_OF_SCOPE"]}
  if materials_base.parent != materials_root:
    return {"removed": [], "kept": keep, "reason_codes": ["CLEANUP_ROOT_OUT_OF_SCOPE"]}
  recorded = payload.get("run_root")
  if recorded:
    try:
      run_root = Path(str(recorded)).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
      return {"removed": [], "kept": keep, "reason_codes": ["CLEANUP_ROOT_OUT_OF_SCOPE"]}
    if run_root != materials_base:
      return {"removed": [], "kept": keep, "reason_codes": ["CLEANUP_ROOT_OUT_OF_SCOPE"]}
  if not materials_base.is_dir():
    return {"removed": [], "kept": keep, "reason_codes": ["CLEANUP_NOT_FOUND"]}
  removed = []
  for entry in sorted(materials_base.rglob("*"), reverse=True):
    if not entry.is_file() or entry.is_symlink() or entry.name in keep:
      continue
    removed.append(str(entry))
    entry.unlink()
  for entry in sorted(materials_base.rglob("*"), reverse=True):
    if entry.is_dir() and not entry.is_symlink() and not any(entry.iterdir()):
      entry.rmdir()
  if any(materials_base.iterdir()):
    return {"removed": removed, "kept": keep, "reason_codes": ["MATERIALS_PARTIALLY_RETAINED"]}
  materials_base.rmdir()
  return {"removed": removed, "kept": keep, "reason_codes": []}


def main(argv=None):
  parser = argparse.ArgumentParser()
  parser.add_argument("mode", choices=("reconcile", "render", "cleanup"))
  args = parser.parse_args(argv)
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError, UnicodeDecodeError):
    json.dump({"status": "ERROR", "reason_codes": ["INVALID_INPUT_JSON"]}, sys.stdout)
    sys.stdout.write("\n")
    return 1
  try:
    if args.mode == "render":
      sys.stdout.write(render_draft(payload))
      return 0
    if args.mode == "reconcile":
      result = build_set(payload)
    else:
      result = cleanup(payload)
  except ValueError as error:
    json.dump({"status": "ERROR", "reason_codes": [str(error)]}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 1
  result["status"] = "OK"
  json.dump(result, sys.stdout, ensure_ascii=False)
  sys.stdout.write("\n")
  return 0


if __name__ == "__main__":
  sys.exit(main())
