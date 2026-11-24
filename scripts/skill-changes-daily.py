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
import math
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


class GitError(RuntimeError):
  pass


def git_ok(*args):
  # log／status 失敗時 stdout 是空的，跟「沒有改版」長得一樣；不擋下就會把書籤推過沒看過的 commit
  proc = git(*args)
  if proc.returncode != 0:
    raise GitError(f"git {args[0]} exit {proc.returncode}：{(proc.stderr or '').strip()[-200:]}")
  return proc


def atomic_write_text(path, content):
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = None
  try:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
      temporary = Path(handle.name)
      handle.write(content)
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, path)
  finally:
    if temporary is not None and temporary.exists():
      temporary.unlink()


def load_state_checked():
  if not STATE.exists() and not STATE.is_symlink():
    return {}, None
  try:
    data = json.loads(STATE.read_text(encoding="utf-8"))
  except (OSError, ValueError) as error:
    return {}, f"state.json 無法讀取或 JSON 損毀（已退回 24 小時視窗）：{error}"
  if not isinstance(data, dict):
    return {}, f"state.json 頂層非物件（{type(data).__name__}，已退回 24 小時視窗）"
  warnings = []
  sanitized = {}
  if "last_head" in data:
    if data["last_head"] is None or isinstance(data["last_head"], str):
      sanitized["last_head"] = data["last_head"]
    else:
      warnings.append("last_head 型別異常")
  if "last_run_epoch" in data:
    epoch = data["last_run_epoch"]
    if isinstance(epoch, (int, float)) and not isinstance(epoch, bool) and math.isfinite(epoch):
      sanitized["last_run_epoch"] = float(epoch)
    else:
      warnings.append("last_run_epoch 非有限數值")
  if "uncommitted_stamps" in data:
    if isinstance(data["uncommitted_stamps"], dict):
      sanitized["uncommitted_stamps"] = data["uncommitted_stamps"]
    else:
      warnings.append("uncommitted_stamps 非物件")
  warning = f"state.json 欄位異常（{'、'.join(warnings)}，已安全退回預設值）" if warnings else None
  return sanitized, warning


def load_state():
  return load_state_checked()[0]


def save_state(data):
  atomic_write_text(STATE, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


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
  seen_uncommitted = seen_uncommitted if isinstance(seen_uncommitted, dict) else {}
  if isinstance(last_head, str) and last_head and git("cat-file", "-e", f"{last_head}^{{commit}}").returncode == 0:
    committed = git_ok("-c", "core.quotePath=false", "log", "--name-only", "--format=", f"{last_head}..HEAD", "--", "skills/*/SKILL.md", "commands/*.md")
  else:
    committed = git_ok("-c", "core.quotePath=false", "log", "--name-only", "--format=", f"--since={fallback_since}", "--", "skills/*/SKILL.md", "commands/*.md")
  dirty = git_ok("-c", "core.quotePath=false", "status", "--porcelain", "-z", "--", "skills/*/SKILL.md", "commands/*.md")
  paths = {}
  for line in committed.stdout.splitlines():
    line = line.strip()
    if line and not line.startswith(VENDOR_MANAGED_PREFIXES):
      paths[line] = "committed"
  current_uncommitted = {}
  tokens = dirty.stdout.split("\0")
  idx = 0
  while idx < len(tokens):
    entry = tokens[idx]
    idx += 1
    if len(entry) < 4:
      continue
    xy = entry[:2]
    rel = entry[3:]
    if xy[0] in ("R", "C") or xy[1] in ("R", "C"):
      idx += 1
    if not rel or rel.startswith(VENDOR_MANAGED_PREFIXES):
      continue
    stamp = stamp_of(CONFIG / rel)
    if stamp is None:
      continue
    current_uncommitted[rel] = stamp
    if seen_uncommitted.get(rel) == stamp:
      continue
    paths[rel] = "uncommitted"
  return paths, current_uncommitted


def to_targets(paths):
  targets = {}
  for rel, origin in sorted(paths.items()):
    p = CONFIG / rel
    if not p.is_file():
      continue
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
  if not isinstance(packet, dict):
    return {}, f"runner 回傳非物件 JSON（{type(packet).__name__}，exit {proc.returncode}）"
  raw_entries = None
  for key in ("skills", "results", "entries"):
    if key in packet and packet[key] is not None:
      raw_entries = packet[key]
      break
  if raw_entries is not None and not isinstance(raw_entries, list):
    return {}, f"runner 輸出清單欄位非陣列（{type(raw_entries).__name__}）"
  per = {}
  malformed_error = None
  for item in raw_entries or []:
    if not isinstance(item, dict) or not isinstance(item.get("skill_name"), str) or not item["skill_name"]:
      malformed_error = "runner 輸出含非預期結構項目"
      continue
    raw_t1 = item.get("tier1")
    raw_t2 = item.get("tier2_intra")
    t1 = raw_t1 if isinstance(raw_t1, dict) else ({"status": "error", "reason": "tier1 格式異常"} if raw_t1 is not None else {})
    t2 = raw_t2 if isinstance(raw_t2, dict) else ({"status": "error", "reason": "tier2 格式異常"} if raw_t2 is not None else {})
    per[item["skill_name"]] = {
      "tier1": t1,
      "tier2": t2,
      "artifact_root": packet.get("artifact_root"),
    }
  reason = packet.get("reason")
  preflight_obj = packet.get("tier2_preflight")
  preflight = preflight_obj.get("status") if isinstance(preflight_obj, dict) else None
  if preflight == "infrastructure_failure":
    return per, f"Tier 2 preflight {preflight}：{reason}"
  if preflight_obj is not None and not isinstance(preflight_obj, dict):
    malformed_error = malformed_error or "tier2_preflight 格式異常"
  return per, malformed_error


# 暫停自動背景重跑名單：避免長耗時評測套件在背景自動排程中連續觸發逾時；
# 改完 runner 環境隔離並驗證穩定後再移出此名單。
SKILL_UP_PAUSED_SKILLS = frozenset({"research-before-answer"})


def launch_skill_up(targets, date):
  launched = []
  errors = []
  if not SKILL_UP.is_file():
    return launched, "skill-up binary 不存在"
  try:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
  except OSError as error:
    return launched, f"建立 state 目錄失敗：{error}"
  for t in targets:
    if t["name"] in SKILL_UP_PAUSED_SKILLS:
      continue
    eval_yaml = t["eval_dir"] / "evals" / "eval.yaml"
    if not eval_yaml.is_file():
      continue
    log = STATE_DIR / f"skill-up-{t['name']}-{date}.log"
    # 每個 target 各自一個 output root：同日的 target 平行跑、iteration 都從 1 起算，
    # 共用一個 root 時後寫的會蓋掉先寫的 result.json，collector 只看得到最後一份。
    try:
      with open(log, "ab") as handle:
        subprocess.Popen(
          [str(SKILL_UP), "run", "evals/eval.yaml", "--output-dir", str(EVAL_RUNS / t["name"])],
          cwd=str(t["eval_dir"]), stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
        )
    except OSError as error:
      errors.append(f"{t['name']}：{error}")
      continue
    launched.append(t["name"])
  return launched, ("；".join(errors) if errors else None)


def _corrupt_skill_up_entry(result, reason, skill=None):
  fallback = skill if isinstance(skill, str) and skill else result.parent.parent.name
  return {
    "skill": fallback,
    "iteration": result.parent.name,
    "passed": 0,
    "failed": 0,
    "errored": 1,
    "path": str(result),
    "corrupt_reason": reason,
  }


def collect_skill_up_results(since_epoch):
  results = []
  if not EVAL_RUNS.is_dir():
    return results
  for result in EVAL_RUNS.rglob("result.json"):
    try:
      mtime = result.stat().st_mtime
    except OSError as error:
      results.append(_corrupt_skill_up_entry(result, f"無法讀取檔案狀態：{error}"))
      continue
    if mtime <= since_epoch:
      continue
    try:
      raw_text = result.read_bytes().decode("utf-8")
      data = json.loads(raw_text)
    except UnicodeDecodeError as error:
      results.append(_corrupt_skill_up_entry(result, f"UTF-8 解碼失敗：{error}"))
      continue
    except (OSError, ValueError) as error:
      results.append(_corrupt_skill_up_entry(result, f"讀取或 JSON 解析失敗：{error}"))
      continue
    if not isinstance(data, dict):
      results.append(_corrupt_skill_up_entry(result, f"頂層非物件（{type(data).__name__}）"))
      continue
    raw_skill = data.get("skill_name")
    if raw_skill is not None and raw_skill != "" and not isinstance(raw_skill, str):
      results.append(_corrupt_skill_up_entry(result, f"skill_name 型別異常（{type(raw_skill).__name__}）"))
      continue
    skill_name = raw_skill if isinstance(raw_skill, str) and raw_skill else result.parent.parent.name
    if "case_results" not in data or not isinstance(data["case_results"], list):
      results.append(_corrupt_skill_up_entry(result, "缺少或無效的 case_results 欄位", skill=skill_name))
      continue
    cases = data["case_results"]
    if any(not isinstance(c, dict) or not isinstance(c.get("status"), str) or not c["status"].strip() for c in cases):
      results.append(_corrupt_skill_up_entry(result, "case_results 含非物件或缺少有效 status", skill=skill_name))
      continue
    statuses = [c["status"].strip().upper() for c in cases]
    results.append({
      "skill": skill_name,
      "iteration": result.parent.name,
      "passed": sum(1 for s in statuses if s == "PASS"),
      "failed": sum(1 for s in statuses if s not in ("PASS", "ERROR")),
      "errored": sum(1 for s in statuses if s == "ERROR"),
      "path": str(result),
    })
  return sorted(results, key=lambda r: (r["skill"], r["iteration"], r["path"]))


def skill_up_result_tier(result):
  # FAIL 是 skill 沒過；ERROR 是 harness，不能升成高，但也不能當全過掉進低。
  if result["failed"]:
    return "高"
  if result.get("errored"):
    return "中"
  return "低"


def skill_up_detail(result):
  # iteration 目錄名在不同 output root 會重覆；不帶 result.json 路徑，同名 run 在報告裡分不開。
  if result.get("corrupt_reason"):
    return f"收據異常（{result['corrupt_reason']}） {result['path']}"
  detail = f"{result['passed']} PASS／{result['failed']} FAIL／{result.get('errored', 0)} ERROR"
  if result.get("errored") and not result["failed"]:
    detail += "（harness 錯誤、非 skill 失敗）"
  return f"{detail} {result['path']}"


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
  rank = {"低": 0, "中": 1, "高": 2}
  for r in skill_up:
    result_tier = skill_up_result_tier(r)
    if rank[result_tier] > rank[tier]:
      tier = result_tier
    reasons.append(f"skill-up {r['iteration']}：{skill_up_detail(r)}")
  if not reasons:
    reasons.append("Tier 1／Tier 2 通過" if target["kind"] == "skill" else "無 SkillEvaluator 面；只排 skill-up")
  return tier, reasons


def render(date, targets, evaluations, runner_error, launched, launch_error, skill_up_results, state, plugin_events, state_warning=None):
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
    elif name in SKILL_UP_PAUSED_SKILLS:
      lines.append("- skill-up 自動背景回歸已暫停（待修復晨間環境模型繼承 900s 逾時後恢復）")
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
        tier = skill_up_result_tier(r)
        tiers[tier].append(f"{name} skill-up")
        lines.append(f"- {name} {r['iteration']}：{skill_up_detail(r)} → 建議檔位：{tier}")
    lines.append("")
  lines.append("## 本輪限制")
  if state_warning:
    lines.append(f"- ⚠️ {state_warning}")
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
  state, state_warning = load_state_checked()
  now = time.time()
  fallback_since = (dt.datetime.now() - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
  try:
    head = git_ok("rev-parse", "HEAD").stdout.strip()
    paths, current_uncommitted = changed_paths(state.get("last_head"), fallback_since, state.get("uncommitted_stamps") or {})
  except GitError as error:
    atomic_write_text(out, f"# skill-changes {args.date}\n\n⚠️ 讀不到 ~/.claude 的 git 紀錄，本輪沒有檢查改版、書籤未前進：{error}\n")
    return 1
  targets = to_targets(paths)
  since_epoch = state.get("last_run_epoch")
  if not isinstance(since_epoch, (int, float)) or isinstance(since_epoch, bool) or not math.isfinite(since_epoch):
    since_epoch = now - 86400
  skill_up_results = collect_skill_up_results(float(since_epoch))
  plugin_events = plugin_hook_drift.scan(CONFIG, APPROVED_HOOKS)
  if not targets and not skill_up_results and not plugin_events and not state_warning:
    atomic_write_text(out, SILENT + "\n")
    save_state({"last_head": head, "last_run_epoch": now, "uncommitted_stamps": current_uncommitted})
    return 0
  skill_targets = [t for t in targets.values() if t["kind"] == "skill"]
  evaluations, runner_error = run_evaluator(skill_targets, args.date)
  launched, launch_error = ([], None) if args.no_skill_up else launch_skill_up(list(targets.values()), args.date)
  report = render(args.date, targets, evaluations, runner_error, launched, launch_error, skill_up_results, state, plugin_events, state_warning=state_warning)
  atomic_write_text(out, report)
  save_state({"last_head": head, "last_run_epoch": now, "uncommitted_stamps": current_uncommitted})
  return 0


if __name__ == "__main__":
  sys.exit(main())
