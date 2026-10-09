#!/usr/bin/env python3
"""skill-changes-daily — 每日對改版過的 skill 跑 SkillEvaluator T1/T2 與 skill-up 回歸，產出帶建議檔位的報告。

Threat model：提示型 channel，不阻擋任何 session。只認 git 看得到的 SKILL.md 與 commands/*.md 改動
（已 commit 或 working tree 未 commit）；worktree 內尚未 merge 回 main 的改動要等 merge 後才會出現。
runner 或 provider 掛掉時把該 skill 標成「無法驗證」進中檔，不靜默吞掉。
取代 2026-09-21 拆除的 SkillEvaluator Stop gate、PostToolUse obligation 與 skill-eval 收據 gate。

用法：LOCAL_ANALYSIS_DATE=YYYY-MM-DD python3 skill-changes-daily.py --out <report.md>
state：~/.claude/logs/skill-changes/state.json（last_head、last_run_epoch、uncommitted_stamps）
"""
import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import plugin_hook_drift

HOME = Path.home()
CONFIG = HOME / ".claude"
SKILLS = CONFIG / "skills"
COMMANDS = CONFIG / "commands"
COMMAND_EVALS = CONFIG / "evals"
RUNNER = CONFIG / "scripts" / "skillevaluator-trial.py"
STATE_DIR = Path(os.environ.get("SKILL_CHANGES_STATE_DIR", str(CONFIG / "logs" / "skill-changes")))
STATE = STATE_DIR / "state.json"
APPROVED_HOOKS = CONFIG / "logs" / "plugin-hook-drift" / "approved.json"
ARTIFACT_ROOT = Path(os.environ.get("SKILL_CHANGES_ARTIFACT_ROOT", str(CONFIG / "logs" / "skillevaluator" / "artifacts" / "skill-changes")))
EVAL_RUNS = Path(os.environ.get("SKILL_EVAL_RUNS_DIR", str(HOME / "Desktop/projects/.claude/trials/skill-up-cli/eval-runs")))
SKILL_UP = Path(os.environ.get("SKILL_UP_BIN", str(HOME / ".local/bin/skill-up")))
SILENT = "__SILENT__"


def git(*args):
  return subprocess.run(["git", "-C", str(CONFIG), *args], capture_output=True, text=True, check=False)


def load_state():
  try:
    data = json.loads(STATE.read_text())
    return data if isinstance(data, dict) else {}
  except (OSError, ValueError):
    return {}


def save_state(data):
  STATE_DIR.mkdir(parents=True, exist_ok=True)
  tmp = STATE.with_suffix(".tmp")
  tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
  os.replace(tmp, STATE)


def stamp_of(path):
  try:
    info = path.stat()
  except OSError:
    return None
  return [info.st_mtime_ns, info.st_size]


# claude.ai 同步輪會把 vendor skill 舊版搬進 skills/.trash/（untracked）、新版放 gitignored 的 skills/synced/；
# 兩者都不是自撰 skill，評進去只會每輪同步重報一次白燒的評估（2026-10-09 四個對象全是這類）。
VENDOR_MANAGED_PREFIXES = ("skills/.trash/", "skills/synced/")


def changed_paths(last_head, fallback_since, seen_uncommitted):
  if last_head and git("cat-file", "-e", f"{last_head}^{{commit}}").returncode == 0:
    committed = git("log", "--name-only", "--format=", f"{last_head}..HEAD", "--", "skills/*/SKILL.md", "commands/*.md")
  else:
    committed = git("log", "--name-only", "--format=", f"--since={fallback_since}", "--", "skills/*/SKILL.md", "commands/*.md")
  dirty = git("status", "--porcelain", "--", "skills/*/SKILL.md", "commands/*.md")
  paths = {}
  for line in committed.stdout.splitlines():
    line = line.strip()
    if line and not line.startswith(VENDOR_MANAGED_PREFIXES):
      paths[line] = "committed"
  current_uncommitted = {}
  for line in dirty.stdout.splitlines():
    rel = line[3:].strip()
    if not rel or rel.startswith(VENDOR_MANAGED_PREFIXES):
      continue
    stamp = stamp_of(CONFIG / rel)
    current_uncommitted[rel] = stamp
    if stamp is not None and seen_uncommitted.get(rel) == stamp:
      continue
    paths[rel] = "uncommitted"
  return paths, current_uncommitted


def to_targets(paths):
  targets = {}
  for rel, origin in sorted(paths.items()):
    p = CONFIG / rel
    if rel.startswith("skills/") and rel.endswith("/SKILL.md"):
      skill_dir = p.parent
      if not skill_dir.is_dir():
        continue
      targets[skill_dir.name] = {"name": skill_dir.name, "kind": "skill", "dir": skill_dir, "eval_dir": skill_dir, "origin": origin}
    elif rel.startswith("commands/") and rel.endswith(".md"):
      name = p.stem
      eval_dir = COMMAND_EVALS / name
      if (eval_dir / "evals" / "eval.yaml").is_file():
        targets[name] = {"name": name, "kind": "command", "dir": p, "eval_dir": eval_dir, "origin": origin}
  return targets


def run_evaluator(skill_targets, date):
  if not skill_targets:
    return {}, None
  with tempfile.TemporaryDirectory(prefix="skill-changes-") as tmp:
    coll = Path(tmp) / "collection"
    coll.mkdir()
    for t in skill_targets:
      os.symlink(t["dir"], coll / t["name"])
    summary = Path(tmp) / "summary.md"
    env = dict(os.environ)
    env["SKILLEVALUATOR_TRIAL_ARTIFACT_ROOT"] = str(ARTIFACT_ROOT)
    env.setdefault("SKILLEVALUATOR_EMBEDDING_PREFLIGHT_TIMEOUT_SECONDS", "90")
    proc = subprocess.run(
      [sys.executable, str(RUNNER), "weekly", "--collection", str(coll), "--date", date, "--summary", str(summary), "--workers", "2"],
      capture_output=True, text=True, env=env, check=False,
    )
  try:
    packet = json.loads(proc.stdout.strip().splitlines()[-1])
  except (ValueError, IndexError):
    return {}, f"runner exit {proc.returncode}：{(proc.stderr or proc.stdout).strip()[-300:]}"
  per = {}
  for item in packet.get("skills") or packet.get("results") or packet.get("entries") or []:
    per[item.get("skill_name")] = {
      "tier1": item.get("tier1") or {},
      "tier2": item.get("tier2_intra") or {},
      "artifact_root": packet.get("artifact_root"),
    }
  reason = packet.get("reason")
  preflight = (packet.get("tier2_preflight") or {}).get("status")
  return per, (f"Tier 2 preflight {preflight}：{reason}" if preflight == "infrastructure_failure" else None)


def skill_up_env():
  env = dict(os.environ)
  shim = str(HOME / ".local/share/better-rm/bin")
  env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p and p != shim)
  return env


def launch_skill_up(targets, date):
  launched = []
  if not SKILL_UP.is_file():
    return launched, "skill-up binary 不存在"
  STATE_DIR.mkdir(parents=True, exist_ok=True)
  for t in targets:
    eval_yaml = t["eval_dir"] / "evals" / "eval.yaml"
    if not eval_yaml.is_file():
      continue
    log = STATE_DIR / f"skill-up-{t['name']}-{date}.log"
    # 每個 target 各自一個 output root：同日的 target 平行跑、iteration 都從 1 起算，
    # 共用一個 root 時後寫的會蓋掉先寫的 result.json，collector 只看得到最後一份。
    with open(log, "ab") as handle:
      subprocess.Popen(
        [str(SKILL_UP), "run", "evals/eval.yaml", "--output-dir", str(EVAL_RUNS / t["name"])],
        cwd=str(t["eval_dir"]), stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
        env=skill_up_env(),
      )
    launched.append(t["name"])
  return launched, None


def collect_skill_up_results(since_epoch):
  results = []
  if not EVAL_RUNS.is_dir():
    return results
  for result in EVAL_RUNS.rglob("result.json"):
    try:
      if result.stat().st_mtime <= since_epoch:
        continue
      data = json.loads(result.read_text())
    except (OSError, ValueError):
      continue
    cases = data.get("case_results") or []
    statuses = [str(c.get("status", "")).upper() for c in cases]
    results.append({
      "skill": data.get("skill_name") or result.parent.parent.name,
      "iteration": result.parent.name,
      "passed": sum(1 for s in statuses if s == "PASS"),
      "failed": sum(1 for s in statuses if s not in ("PASS", "ERROR")),
      "errored": sum(1 for s in statuses if s == "ERROR"),
      "path": str(result),
    })
  return sorted(results, key=lambda r: (r["skill"], r["iteration"]))


def tier_for(target, evaluation, skill_up, runner_error):
  reasons = []
  tier = "低"
  if target["kind"] == "skill":
    if evaluation is None:
      tier = "中"
      reasons.append(f"無法驗證：{runner_error or 'runner 未回傳此 skill'}")
    else:
      t1, t2 = evaluation["tier1"], evaluation["tier2"]
      if t1.get("status") == "failed":
        tier = "高"
        reasons.append(f"Tier 1 failed（{t1.get('finding_count', 0)} finding）")
      elif t1.get("status") not in ("passed",):
        tier = "中"
        reasons.append(f"Tier 1 {t1.get('status')}：{t1.get('reason')}")
      if t2.get("status") == "findings":
        tier = "高" if tier == "高" else "中"
        reasons.append(f"Tier 2 finding（{t2.get('finding_count', 0)}）")
      elif t2.get("status") not in ("passed", None):
        tier = "高" if tier == "高" else "中"
        reasons.append(f"Tier 2 {t2.get('status')}：{t2.get('reason')}")
  for r in skill_up:
    if r["failed"]:
      tier = "高"
      reasons.append(f"skill-up {r['iteration']}：{r['passed']} PASS／{r['failed']} FAIL")
    elif r.get("errored"):
      tier = "高" if tier == "高" else "中"
      reasons.append(f"skill-up {r['iteration']}：{r['passed']} PASS／{r['errored']} ERROR（harness 錯誤、非 skill 失敗）")
    else:
      reasons.append(f"skill-up {r['iteration']}：{r['passed']} PASS")
  if not reasons:
    reasons.append("Tier 1／Tier 2 通過" if target["kind"] == "skill" else "無 SkillEvaluator 面；只排 skill-up")
  return tier, reasons


def render(date, targets, evaluations, runner_error, launched, launch_error, skill_up_results, state, plugin_events):
  lines = [f"# skill-changes — {date}", "", "每日對改版過的 skill／command 跑 SkillEvaluator T1／T2 與 skill-up 回歸；plugin hook 另與使用者批准的摘要比對，只觀察更新後的內容，不阻止 hook 先執行。", "", f"- 比對基準：{state.get('last_head', '（首輪，回看 24 小時）')} → HEAD", f"- 改版對象：{len(targets)}", ""]
  by_skill = {}
  for r in skill_up_results:
    by_skill.setdefault(r["skill"], []).append(r)
  tiers = {"高": [], "中": [], "低": []}
  for name, t in sorted(targets.items()):
    tier, reasons = tier_for(t, evaluations.get(name) if t["kind"] == "skill" else {"tier1": {"status": "passed"}, "tier2": {"status": "passed"}}, by_skill.pop(name, []), runner_error)
    tiers[tier].append(name)
    lines.append(f"## {name}（{t['kind']}，{t['origin']}）")
    lines.append(f"- 建議檔位：{tier}")
    for r in reasons:
      lines.append(f"- {r}")
    if name in launched:
      lines.append("- skill-up 回歸已於本輪背景啟動，結果在下一輪報告")
    lines.append("")
  if plugin_events:
    lines.append("## Plugin hook 待查（更新後觀察，不代表事前攔截）")
    for event in plugin_events:
      tiers["中"].append(f"plugin hook {event['plugin']}")
      lines.append(f"- {json.dumps(event['plugin'], ensure_ascii=False)}：{event['status']}（{event['category']}）")
    lines.append("")
  if by_skill:
    lines.append("## 上一輪啟動的 skill-up 回歸結果")
    for name, rows in sorted(by_skill.items()):
      for r in rows:
        tier = "高" if r["failed"] else "低"
        tiers[tier].append(f"{name} skill-up")
        lines.append(f"- {name} {r['iteration']}：{r['passed']} PASS／{r['failed']} FAIL → 建議檔位：{tier}")
    lines.append("")
  lines.append("## 本輪限制")
  if runner_error:
    lines.append(f"- ⚠️ SkillEvaluator runner：{runner_error}")
  if launch_error:
    lines.append(f"- ⚠️ skill-up：{launch_error}")
  lines.append("- Tier 2 inter（跨 skill 相似度）只在 weekly 全庫掃描做，本報告不算。")
  lines.append("- 未 merge 回 main 的 worktree 改動不在比對範圍；未 commit 的改動在 mtime 與大小都沒變時只報一次。")
  lines.append("")
  lines.append(f"建議檔位彙總：高 {len(tiers['高'])}／中 {len(tiers['中'])}／低 {len(tiers['低'])}")
  return "\n".join(lines) + "\n"


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--out")
  parser.add_argument("--date", default=os.environ.get("LOCAL_ANALYSIS_DATE") or dt.date.today().isoformat())
  parser.add_argument("--no-skill-up", action="store_true")
  parser.add_argument("--inspect-plugin")
  parser.add_argument("--approve-plugin")
  args = parser.parse_args()
  if args.inspect_plugin and args.approve_plugin:
    parser.error("inspect and approve are separate operations")
  if args.inspect_plugin or args.approve_plugin:
    try:
      result = plugin_hook_drift.approve(CONFIG, APPROVED_HOOKS, args.approve_plugin) if args.approve_plugin else plugin_hook_drift.inspect(CONFIG, APPROVED_HOOKS, args.inspect_plugin)
    except (OSError, ValueError, TypeError) as error:
      parser.exit(1, f"plugin hook operation failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
  if not args.out:
    parser.error("the daily report requires --out")
  out = Path(args.out).expanduser()
  state = load_state()
  head = git("rev-parse", "HEAD").stdout.strip()
  now = time.time()
  fallback_since = (dt.datetime.now() - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
  paths, current_uncommitted = changed_paths(state.get("last_head"), fallback_since, state.get("uncommitted_stamps") or {})
  targets = to_targets(paths)
  skill_up_results = collect_skill_up_results(float(state.get("last_run_epoch", now - 86400)))
  plugin_events = plugin_hook_drift.scan(CONFIG, APPROVED_HOOKS)
  if not targets and not skill_up_results and not plugin_events:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(SILENT + "\n")
    save_state({"last_head": head, "last_run_epoch": now, "uncommitted_stamps": current_uncommitted})
    return 0
  skill_targets = [t for t in targets.values() if t["kind"] == "skill"]
  evaluations, runner_error = run_evaluator(skill_targets, args.date)
  launched, launch_error = ([], None) if args.no_skill_up else launch_skill_up(list(targets.values()), args.date)
  report = render(args.date, targets, evaluations, runner_error, launched, launch_error, skill_up_results, state, plugin_events)
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(report)
  save_state({"last_head": head, "last_run_epoch": now, "uncommitted_stamps": current_uncommitted})
  return 0


if __name__ == "__main__":
  sys.exit(main())
