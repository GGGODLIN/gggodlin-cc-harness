#!/usr/bin/env python3
"""skill-trigger-health channel 核心掃描器（純機械、零 LLM；判讀歸 main session）。

三段輸出：
  1. ⚠️ 警報：分類為 auto-only 的 skill 在 30 天窗內出現手動 slash（任何一次即報）
  2. 統計儀表：每 skill 的 auto invoke（distinct tool_use id）/ manual slash（distinct msg uuid）
  3. 死庫存候選：安裝 > min-age 天且 90 天窗內零 invoke（每輪限量列出、其餘計數）

分類 registry：reports/local-analysis/.skill-trigger-registry.json
  {name: {"mode": "auto-only|manual-by-design|dual", "decided": bool}}
  decided=true 為使用者拍板、腳本永不覆寫；decided=false 每輪按 frontmatter 重新自動猜。

範圍宣告（no silent caps）：只掃自有 ~/.claude/skills + ~/.claude/commands；
plugin 前綴（含冒號）的 Skill invoke 不對映；死庫存軸是 90 天窗、非真 lifetime。
死庫存軸排除 settings.json skillOverrides 設 name-only 的 skill（2026-08-04 拍板）：
name-only 只注入名字一行（~5 tok）、無 description 誤觸發面、由 router/手動叫用，
零 invoke 是設計預期而非死庫存訊號；排除數在報告標題註記、不靜默。
registry mode 為 hook-driven 的同樣排除（2026-09-22 拍板）：這類 command 由 hook 注入 workflow
指令觸發、不經 Skill tool（例 daily-topic），計數器結構上看不到；使用者原則是
「零成本／看不到的 skill 不進死庫存警報」。
計數紀律：auto 按 distinct tool_use id、manual 按 distinct message uuid 去重
（resume/fork 會複製訊息，原始命中數灌水 3-13 倍，前案見 memory adhd extract 洞察 2）。
"""
import argparse
import json
import glob
import os
import re
import subprocess
import time

CMD_RE = re.compile(r"<command-name>/([A-Za-z0-9_-]+)</command-name>")
DUAL_RE = re.compile(r"invokable (manually|via)|手動|slash command|also invokable", re.IGNORECASE)


def read_frontmatter(path):
  desc, disable = "", False
  try:
    with open(path, errors="replace") as fh:
      lines = fh.read().split("\n")
  except OSError:
    return desc, disable
  if not lines or lines[0].strip() != "---":
    return desc, disable
  for line in lines[1:60]:
    if line.strip() == "---":
      break
    if line.startswith("description:"):
      desc = line[len("description:"):].strip()
    if line.startswith("disable-model-invocation:") and "true" in line:
      disable = True
  return desc, disable


def build_inventory(skills_dir, commands_dir):
  inv = {}
  for skill_md in sorted(glob.glob(os.path.join(skills_dir, "*", "SKILL.md"))):
    name = os.path.basename(os.path.dirname(skill_md))
    desc, disable = read_frontmatter(skill_md)
    if disable:
      guess = "manual-by-design"
    elif DUAL_RE.search(desc) or f"/{name}" in desc:
      guess = "dual"
    else:
      guess = "auto-only"
    inv[name] = {"source": "skill", "guess": guess, "path": skill_md, "disable": disable}
  for cmd_md in sorted(glob.glob(os.path.join(commands_dir, "*.md"))):
    name = os.path.basename(cmd_md)[:-3]
    _, cmd_disable = read_frontmatter(cmd_md)
    if name in inv:
      inv[name]["source"] = "skill+command"
      inv[name]["guess"] = "dual"
      inv[name]["disable"] = inv[name].get("disable", False) or cmd_disable
    else:
      inv[name] = {"source": "command", "guess": "manual-by-design", "path": cmd_md, "disable": cmd_disable}
  return inv


def load_registry(path, inventory):
  registry = {}
  if os.path.exists(path):
    try:
      registry = json.load(open(path))
    except (OSError, json.JSONDecodeError):
      registry = {}
  new_names = {name for name in inventory if name not in registry}
  for name, meta in inventory.items():
    entry = registry.get(name)
    if entry and entry.get("decided"):
      continue
    preserved = {k: v for k, v in (entry or {}).items() if k not in ("mode", "decided")}
    registry[name] = {**preserved, "mode": meta["guess"], "decided": False}
  return registry, new_names


def save_registry(path, registry):
  tmp = path + ".tmp"
  json.dump(dict(sorted(registry.items())), open(tmp, "w"), ensure_ascii=False, indent=1)
  os.replace(tmp, path)


def parse_ts(rec, fallback):
  ts = rec.get("timestamp")
  if isinstance(ts, str):
    try:
      import datetime
      return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
      pass
  return fallback


def parse_iso_date(val):
  if not isinstance(val, str) or not val.strip():
    return 0.0
  try:
    import datetime
    dt = datetime.datetime.fromisoformat(val.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()
  except ValueError:
    return 0.0


def scan(projects_dir, names, alert_days, dead_days, now):
  alert_cut = now - alert_days * 86400
  dead_cut = now - dead_days * 86400
  auto_ids, manual_uuids = {}, {}
  files = 0
  for path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl")):
    if "-private-var-folders-" in os.path.basename(os.path.dirname(path)):
      continue
    try:
      mtime = os.path.getmtime(path)
    except OSError:
      continue
    if mtime < dead_cut:
      continue
    files += 1
    try:
      fh = open(path, errors="replace")
    except OSError:
      continue
    with fh:
      for line in fh:
        has_cmd = "<command-name>/" in line
        has_skill = '"Skill"' in line and '"skill"' in line
        has_wf = '"Workflow"' in line and '"tool_use"' in line
        if not (has_cmd or has_skill or has_wf):
          continue
        try:
          rec = json.loads(line)
        except json.JSONDecodeError:
          continue
        msg = rec.get("message") or {}
        ts = parse_ts(rec, mtime)
        role = msg.get("role")
        content = msg.get("content")
        if (has_skill or has_wf) and role == "assistant" and isinstance(content, list):
          for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
              continue
            bname = block.get("name")
            inp = block.get("input") or {}
            if bname == "Skill":
              skill = inp.get("skill", "")
              if skill in names:
                auto_ids.setdefault(skill, {})[block.get("id") or f"{path}:{ts}"] = ts
            elif bname == "Workflow":
              wf = inp.get("name") or ""
              if not wf and inp.get("scriptPath"):
                wf = os.path.splitext(os.path.basename(str(inp.get("scriptPath"))))[0]
              if wf in names:
                auto_ids.setdefault(wf, {})[block.get("id") or f"{path}:{ts}"] = ts
        if has_cmd and role == "user":
          blob = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
          for hit in CMD_RE.findall(blob):
            if hit in names:
              manual_uuids.setdefault(hit, {})[rec.get("uuid") or f"{path}:{hash(line)}"] = ts
  def bucket(store):
    out = {}
    for name, events in store.items():
      out[name] = {
        "recent": sum(1 for t in events.values() if t >= alert_cut),
        "window": len(events),
        "last_ts": max(events.values()) if events else 0.0,
      }
    return out
  return bucket(auto_ids), bucket(manual_uuids), files


def install_date(git_dir, rel_path):
  if not git_dir:
    return None
  try:
    out = subprocess.run(
      ["git", "-C", git_dir, "log", "--diff-filter=A", "--format=%at", "-1", "--", rel_path],
      capture_output=True, text=True, timeout=15,
    )
    val = out.stdout.strip()
    return int(val) if val else None
  except (OSError, subprocess.SubprocessError, ValueError):
    return None


def norm_repo_path(val):
  if not isinstance(val, str) or not val.strip():
    return ""
  return os.path.realpath(os.path.expanduser(val.strip()))


def read_matching_ledger(cand_path, real_repo):
  try:
    with open(cand_path) as f:
      data = json.load(f)
    if isinstance(data, dict) and norm_repo_path(data.get("repo_path")) == real_repo:
      return data
  except (OSError, json.JSONDecodeError):
    pass
  return None


def load_deep_check_ledger(state_dir, repo_dir):
  real_repo = norm_repo_path(repo_dir)
  if not state_dir or not os.path.isdir(state_dir) or not real_repo:
    return None
  base = os.path.basename(real_repo)
  parent = os.path.basename(os.path.dirname(real_repo))
  candidates = [
    os.path.join(state_dir, f"{base}.json"),
    os.path.join(state_dir, f"{parent}-{base}.json"),
    *sorted(glob.glob(os.path.join(state_dir, "*.json"))),
  ]
  for cand in candidates:
    if os.path.exists(cand):
      matched = read_matching_ledger(cand, real_repo)
      if matched is not None:
        return matched
  return None


def git_rev_list_count(repo_dir, *rev_args):
  try:
    r = subprocess.run(
      ["git", "-C", repo_dir, "rev-list", "--count", *rev_args],
      capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0 and r.stdout.strip().isdigit():
      return int(r.stdout.strip())
  except (OSError, subprocess.SubprocessError):
    pass
  return None


def count_uninspected_commits(real_repo, ledger, since_30d):
  head_sha = str(ledger.get("head_sha") or "").strip()
  if head_sha:
    cnt = git_rev_list_count(real_repo, f"{head_sha}..HEAD")
    if cnt is not None:
      return cnt
  since = str(ledger.get("checked_at") or since_30d).strip()
  return git_rev_list_count(real_repo, f"--since={since}", "HEAD") or 0


def iter_candidate_repos(repo_roots):
  seen_repos = set()
  for root in repo_roots:
    root = os.path.expanduser(root.strip())
    if not root or not os.path.isdir(root):
      continue
    for entry in sorted(os.listdir(root)):
      repo_dir = os.path.join(root, entry)
      if not os.path.isdir(repo_dir) or not os.path.exists(os.path.join(repo_dir, ".git")):
        continue
      real_repo = norm_repo_path(repo_dir)
      if real_repo and real_repo not in seen_repos:
        seen_repos.add(real_repo)
        yield entry, real_repo


def evaluate_repo_candidate(entry, real_repo, state_dir, now, remind_days, since_30d, min_commits):
  ledger = load_deep_check_ledger(state_dir, real_repo)
  if ledger:
    last_activity = max(parse_iso_date(ledger.get("checked_at")), parse_iso_date(ledger.get("skipped_at")))
    if last_activity > 0 and (now - last_activity) < remind_days * 86400:
      return None
    count = count_uninspected_commits(real_repo, ledger, since_30d)
    return (count, f"{entry}（+{count} commits）") if count >= min_commits else None
  count = git_rev_list_count(real_repo, f"--since={since_30d}", "HEAD") or 0
  return (count, f"{entry}（+{count} commits，首次健檢）") if count >= min_commits else None


def nominate_deep_check_repos(state_dir, repo_roots, now, remind_days, min_commits=20):
  import datetime
  since_30d = datetime.datetime.fromtimestamp(now - 30 * 86400, datetime.timezone.utc).strftime("%Y-%m-%d")
  candidates = [
    cand for entry, real_repo in iter_candidate_repos(repo_roots)
    if (cand := evaluate_repo_candidate(entry, real_repo, state_dir, now, remind_days, since_30d, min_commits))
  ]
  candidates.sort(key=lambda x: (-x[0], x[1]))
  return [label for _, label in candidates[:2]]


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--date", required=True)
  ap.add_argument("--out", required=True)
  ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
  ap.add_argument("--skills-dir", default=os.path.expanduser("~/.claude/skills"))
  ap.add_argument("--commands-dir", default=os.path.expanduser("~/.claude/commands"))
  ap.add_argument("--registry", default="~/code/social-info/reports/local-analysis/.skill-trigger-registry.json")
  ap.add_argument("--claude-git-dir", default=os.path.expanduser("~/.claude"))
  ap.add_argument("--deep-check-state-dir", default=os.path.expanduser("~/.claude/skills/deep-check/state"))
  ap.add_argument("--repo-roots", default=f"{os.path.expanduser('~/Desktop/work/acme')},{os.path.expanduser('~/Desktop/projects')}")
  ap.add_argument("--alert-window-days", type=int, default=30)
  ap.add_argument("--dead-window-days", type=int, default=90)
  ap.add_argument("--dead-min-age-days", type=int, default=90)
  ap.add_argument("--dead-cap", type=int, default=3)
  args = ap.parse_args()

  now = time.time()
  inventory = build_inventory(args.skills_dir, args.commands_dir)
  registry, new_names = load_registry(args.registry, inventory)
  save_registry(args.registry, registry)
  auto, manual, files = scan(
    args.projects_dir, set(inventory), args.alert_window_days, args.dead_window_days, now
  )

  name_only = set()
  for sp in (os.path.expanduser("~/.claude/settings.json"), os.path.expanduser("~/.claude-team/settings.json")):
    try:
      with open(sp) as fh:
        ov = json.load(fh).get("skillOverrides", {})
      name_only.update(k for k, v in ov.items() if v == "name-only")
    except (OSError, json.JSONDecodeError):
      continue

  alerts, rows, dead, reminders, undecided, new_undecided = [], [], [], [], [], []
  dead_name_only_excluded = 0
  dead_hook_driven_excluded = 0
  dead_disabled_excluded = 0
  dead_remind_excluded = 0
  repo_roots = [r for r in args.repo_roots.split(",") if r.strip()]
  for name, meta in sorted(inventory.items()):
    reg_entry = registry.get(name, {})
    mode = reg_entry.get("mode", meta["guess"])
    decided = reg_entry.get("decided", False)
    remind_days = reg_entry.get("remind_after_days")
    has_remind = isinstance(remind_days, int) and not isinstance(remind_days, bool) and remind_days > 0
    a = auto.get(name, {"recent": 0, "window": 0, "last_ts": 0.0})
    m = manual.get(name, {"recent": 0, "window": 0, "last_ts": 0.0})
    rel = os.path.relpath(meta["path"], args.claude_git_dir) if args.claude_git_dir else meta["path"]
    inst = install_date(args.claude_git_dir, rel)
    if has_remind:
      last_invoked = max(a.get("last_ts", 0.0), m.get("last_ts", 0.0))
      last_skipped = parse_iso_date(reg_entry.get("last_skipped_at"))
      ref_ts = max(last_invoked, last_skipped, float(inst or 0.0))
      if ref_ts == 0.0 or (now - ref_ts) >= remind_days * 86400:
        days_ago = int((now - ref_ts) / 86400) if ref_ts > 0 else remind_days
        hint = str(reg_entry.get("remind_hint") or "").strip()
        hint_part = f"｜{hint}" if hint else ""
        if name == "deep-check":
          top_repos = nominate_deep_check_repos(args.deep_check_state_dir, repo_roots, now, remind_days)
          if top_repos:
            reminders.append(f"- `{name}`（距上次 {days_ago} 天{hint_part}）→ 推薦目標：{'、'.join(top_repos)}")
        else:
          reminders.append(f"- `{name}`（距上次 {days_ago} 天{hint_part}）")
    if not decided:
      undecided.append(f"{name}（自動猜 {mode}、source {meta['source']}）")
      if name in new_names:
        new_undecided.append(f"{name}（自動猜 {mode}、source {meta['source']}）")
    if mode == "auto-only" and m["recent"] > 0:
      alerts.append(
        f"- ⚠️ `{name}`（auto-only）{args.alert_window_days} 天內被手動 slash **{m['recent']} 次**（同窗 auto {a['recent']} 次）——該自動觸發卻要人手打"
      )
    if a["recent"] or m["recent"]:
      rows.append(f"| `{name}` | {mode}{'' if decided else ' (未拍板)'} | {a['recent']} | {m['recent']} | {a['window'] + m['window']} |")
    if a["window"] + m["window"] == 0:
      if has_remind:
        dead_remind_excluded += 1
        continue
      if name in name_only:
        dead_name_only_excluded += 1
        continue
      if mode == "hook-driven":
        dead_hook_driven_excluded += 1
        continue
      if meta.get("disable"):
        dead_disabled_excluded += 1
        continue
      if inst and (now - inst) >= args.dead_min_age_days * 86400:
        dead.append((inst, name, mode))
  dead.sort()

  lines = [
    f"# Skill trigger health — {args.date}",
    "",
    f"範圍：自有 skills（{sum(1 for v in inventory.values() if 'skill' in v['source'])}）+ commands（{sum(1 for v in inventory.values() if v['source'] == 'command')}）；plugin 前綴 invoke 不對映；掃 {files} 個 jsonl（mtime {args.dead_window_days} 天內）；死庫存軸 = {args.dead_window_days} 天窗非真 lifetime。",
    "",
    "## 警報（auto-only 被手動 slash）",
    "",
  ]
  lines += alerts if alerts else ["無。"]
  lines += ["", f"## 🔔 久未執行提醒（{len(reminders)}）", ""]
  lines += reminders if reminders else ["無。"]
  lines += ["", f"## 統計儀表（{args.alert_window_days} 天窗、僅列有活動者，共 {len(rows)}/{len(inventory)}）", "", "| skill | mode | auto | manual | 90d 合計 |", "|---|---|---|---|---|"]
  lines += rows if rows else []
  lines += ["", f"## 死庫存候選（安裝 ≥ {args.dead_min_age_days} 天且 {args.dead_window_days} 天零 invoke；本輪列 {min(len(dead), args.dead_cap)}/{len(dead)}；另排除 name-only {dead_name_only_excluded} 個——router 選單成員、零 invoke 屬設計預期；排除 hook-driven {dead_hook_driven_excluded} 個——由 hook 注入觸發、不經 Skill tool，計數器看不到；排除 disable-model-invocation {dead_disabled_excluded} 個——零常駐 token 成本；排除 remind_after_days {dead_remind_excluded} 個——低頻週期提醒工具）", ""]
  for inst, name, mode in dead[: args.dead_cap]:
    age = int((now - inst) / 86400)
    lines.append(f"- `{name}`（{mode}、安裝 {age} 天、{args.dead_window_days} 天零 invoke）→ 留/殺候選")
  if len(dead) > args.dead_cap:
    lines.append(f"- ……另 {len(dead) - args.dead_cap} 個候選排隊（下輪輪替）")
  if not dead:
    lines.append("無。")
  lines += ["", f"## 待拍板分類（registry decided=false 共 {len(undecided)}；漸進制——只在警報／死庫存／skill 結案時逐項拍，不做全量批次，2026-08-07 拍板）", ""]
  if new_undecided:
    lines.append(f"本輪新增 {len(new_undecided)} 項：")
    lines += [f"- {u}" for u in new_undecided]
    lines.append("")
    lines.append(f"拍板方式：改 {args.registry} 對應 entry 的 mode 並設 decided=true（main session 代改、使用者只拍板）。")
  else:
    lines.append("本輪無新增；既有未拍板項留在 registry、遇事件才逐項拍。")

  tmp = args.out + ".tmp"
  with open(tmp, "w") as fh:
    fh.write("\n".join(lines) + "\n")
  os.replace(tmp, args.out)
  print(f"skill-trigger-health: alerts={len(alerts)} active={len(rows)} dead={len(dead)} undecided={len(undecided)}")


if __name__ == "__main__":
  main()
