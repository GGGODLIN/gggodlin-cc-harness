#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


DAILY = Path(__file__).with_name("skill-changes-daily.py")
PLUGIN = "demo@fixture"

# 假的 skill-up：不跑真 eval，只照 --output-dir 與 cwd 造出 iteration-1/result.json。
# 先寫 marker 再等 peer marker，確保兩個 target 真的同時在跑，RED 看到的「只剩一份」不是「第二個沒跑」。
FAKE_SKILL_UP = '''#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path


def main():
  args = sys.argv[1:]
  output_dir = Path(args[args.index("--output-dir") + 1])
  name = Path.cwd().name
  markers = Path(os.environ["FAKE_SKILL_UP_MARKERS"])
  markers.mkdir(parents=True, exist_ok=True)
  (markers / (name + ".json")).write_text(json.dumps({"name": name, "output_dir": str(output_dir)}))
  deadline = time.monotonic() + 5
  while time.monotonic() < deadline and len(list(markers.glob("*.json"))) < int(os.environ["FAKE_SKILL_UP_PEERS"]):
    time.sleep(0.05)
  iteration = output_dir / "iteration-1"
  iteration.mkdir(parents=True, exist_ok=True)
  tmp = iteration / ("." + name + ".tmp")
  tmp.write_text(json.dumps({"skill_name": name, "case_results": [{"name": name + "-case", "status": "PASS"}]}))
  os.replace(tmp, iteration / "result.json")
  return 0


if __name__ == "__main__":
  sys.exit(main())
'''


def load_daily(env):
  """以指定環境變數載入模組：EVAL_RUNS／SKILL_UP／STATE_DIR 都是 import 時從環境讀的常數。"""
  saved = dict(os.environ)
  os.environ.update(env)
  try:
    spec = importlib.util.spec_from_file_location("skill_changes_daily_under_test", DAILY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
  finally:
    os.environ.clear()
    os.environ.update(saved)


class PluginHookDriftTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.home = Path(self.temp.name)
    self.config = self.home / ".claude"
    self.plugin = self.config / "plugins/cache/fixture/demo/1.0.0"
    self.hooks = self.plugin / "hooks"
    self.hooks.mkdir(parents=True)
    self.registry = self.config / "plugins/installed_plugins.json"
    self.registry.write_text(json.dumps({"version": 2, "plugins": {PLUGIN: [{"installPath": str(self.plugin), "scope": "user", "version": "1.0.0"}]}}))
    (self.config / "settings.json").write_text(json.dumps({"enabledPlugins": {PLUGIN: True}}))
    self.report = self.home / "report.md"
    self.approved = self.config / "logs/plugin-hook-drift/approved.json"
    self.marker = self.home / "hook-ran"
    self.env = {**os.environ, "HOME": str(self.home), "SKILL_CHANGES_STATE_DIR": str(self.home / "daily-state")}
    # 正式環境的 ~/.claude 一定是 git repo；fixture 不是 repo 時每次 git 都失敗，會跟「讀 git 失敗要報錯」的行為打架
    subprocess.run(["git", "init", "-q", str(self.config)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(self.config), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-q", "--allow-empty", "-m", "init"], check=True, capture_output=True)
    self.command_manifest("first")

  def command_manifest(self, value):
    command = f"python3 -c 'from pathlib import Path; Path({str(self.marker)!r}).write_text({value!r})'"
    self.manifest({"hooks": {"SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": 5}]}]}})

  def function_manifest(self, content="export const name = 'first'\n"):
    (self.hooks / "register.ts").write_text(content)
    self.manifest({"description": "fixture", "modules": ["./register.ts"]})

  def manifest(self, data):
    (self.hooks / "hooks.json").write_text(json.dumps(data))

  def run_cli(self, *args):
    return subprocess.run([sys.executable, str(DAILY), *args], env=self.env, capture_output=True, text=True, timeout=10)

  def daily(self):
    result = self.run_cli("--out", str(self.report), "--no-skill-up")
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertTrue(self.report.is_file())
    return self.report.read_text()

  def inspect(self):
    result = self.run_cli("--inspect-plugin", PLUGIN)
    self.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout)

  def approve(self):
    self.inspect()
    result = self.run_cli("--approve-plugin", PLUGIN)
    self.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout)

  def commit_command(self, text):
    commands = self.config / "commands"
    commands.mkdir(exist_ok=True)
    target = commands / "check.md"
    target.write_text("first\n")
    eval_dir = self.config / "evals/check/evals"
    eval_dir.mkdir(parents=True)
    (eval_dir / "eval.yaml").write_text("tests: []\n")
    subprocess.run(["git", "init", "-q", str(self.config)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(self.config), "add", "commands/check.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(self.config), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "baseline"], check=True, capture_output=True)
    target.write_text(text)
    return target

  def test_unreadable_git_is_reported_and_keeps_the_bookmark(self):
    # git 失敗時 stdout 是空的，以前會被當成「沒有改版」並把書籤推過沒看過的 commit（2026-10-10 稽核找到）
    self.daily()
    state_path = self.home / "daily-state/state.json"
    before = json.loads(state_path.read_text())
    (self.config / ".git/HEAD").write_text("garbage\n")
    result = self.run_cli("--out", str(self.report), "--no-skill-up")
    self.assertEqual(result.returncode, 1, result.stderr)
    self.assertIn("讀不到", self.report.read_text())
    self.assertEqual(json.loads(state_path.read_text()), before)

  def test_unapproved_change_reports_until_explicit_approval(self):
    first = self.daily()
    self.assertIn("未審", first)
    self.assertIn(PLUGIN, first)
    self.assertIn("未審", self.daily())
    self.assertFalse(self.approved.exists())
    refused = self.run_cli("--approve-plugin", PLUGIN)
    self.assertNotEqual(refused.returncode, 0)
    self.assertFalse(self.approved.exists())
    inspected = self.inspect()
    self.assertEqual(inspected["plugin"], PLUGIN)
    self.assertEqual(set(inspected), {"plugin", "manifest", "modules", "approved"})
    self.approve()
    approved_bytes = self.approved.read_bytes()
    self.assertEqual(self.daily(), "__SILENT__\n")
    self.assertEqual(self.approved.read_bytes(), approved_bytes)
    self.assertFalse(self.marker.exists())
    entry = json.loads(self.approved.read_text())["plugins"][PLUGIN]
    self.assertEqual(set(entry), {"content"})
    self.assertEqual(set(entry["content"]), {"manifest", "modules"})

  def test_approval_is_refused_when_content_changed_after_inspection(self):
    self.inspect()
    self.command_manifest("changed-after-inspection")
    refused = self.run_cli("--approve-plugin", PLUGIN)
    self.assertNotEqual(refused.returncode, 0)
    self.assertIn("changed since inspection", refused.stderr)
    self.assertFalse(self.approved.exists())

  def test_legacy_digest_only_approval_needs_reapproval_without_crashing(self):
    self.approved.parent.mkdir(parents=True)
    self.approved.write_text(json.dumps({"version": 1, "plugins": {PLUGIN: {"digest": "a" * 64, "manifest": "b" * 64, "modules": {}}}}))
    report = self.daily()
    self.assertIn("未審", report)
    self.assertIn(PLUGIN, report)
    self.approve()
    self.assertEqual(self.daily(), "__SILENT__\n")
    self.assertEqual(set(json.loads(self.approved.read_text())["plugins"][PLUGIN]), {"content"})

  def test_unchanged_uncommitted_file_is_reported_once_and_edits_report_again(self):
    self.approve()
    target = self.commit_command("second\n")
    self.assertIn("## check（command", self.daily())
    self.assertEqual(self.daily(), "__SILENT__\n")
    state = json.loads((self.home / "daily-state/state.json").read_text())
    self.assertEqual(set(state), {"last_head", "last_run_epoch", "uncommitted_stamps"})
    target.write_text("third, longer\n")
    self.assertIn("## check（command", self.daily())

  def test_vendor_managed_skill_dirs_are_not_targets(self):
    self.approve()
    self.commit_command("first\n")
    self.assertIn("## check（command", self.daily())
    for rel in ("skills/.trash/1791477004334-52236-IOheCg/computer-use/SKILL.md", "skills/synced/org_user/chrome-browser/SKILL.md"):
      target = self.config / rel
      target.parent.mkdir(parents=True)
      target.write_text("---\nname: vendor\ndescription: synced copy\n---\n")
    self.assertEqual(self.daily(), "__SILENT__\n")
    state = json.loads((self.home / "daily-state/state.json").read_text())
    self.assertEqual(state["uncommitted_stamps"], {})

  def test_manifest_and_module_changes_report_without_executing_hooks(self):
    self.approve()
    self.command_manifest("second")
    self.assertIn("manifest", self.daily())
    self.assertFalse(self.marker.exists())
    self.function_manifest()
    self.approve()
    module = self.hooks / "register.ts"
    stat = module.stat()
    self.assertEqual(json.loads(self.approved.read_text())["plugins"][PLUGIN]["content"]["modules"], {"./register.ts": [stat.st_mtime_ns, stat.st_size]})
    module.write_text("export const name = 'second'\n")
    report = self.daily()
    self.assertIn("module", report)
    self.assertIn(PLUGIN, report)
    self.assertFalse(self.marker.exists())

  def test_missing_unreadable_and_escaped_hooks_keep_approval(self):
    self.approve()
    approved_bytes = self.approved.read_bytes()
    (self.hooks / "hooks.json").unlink()
    self.assertIn("遺失", self.daily())
    (self.hooks / "hooks.json").mkdir()
    self.assertIn("無法檢查", self.daily())
    (self.hooks / "hooks.json").rmdir()
    outside = self.home / "outside.fifo"
    os.mkfifo(outside)
    (self.hooks / "register.ts").symlink_to(outside)
    self.manifest({"modules": ["./register.ts"]})
    self.assertIn("無法檢查", self.daily())
    self.assertEqual(self.approved.read_bytes(), approved_bytes)

  def test_hook_only_changes_do_not_hide_existing_command_reports(self):
    self.commit_command("second\n")
    self.approve()
    self.command_manifest("second")
    report = self.daily()
    self.assertIn("## check（command", report)
    self.assertIn(PLUGIN, report)
    self.assertNotIn("__SILENT__\n", report)
    self.assertFalse(self.marker.exists())

  def add_project_installation(self, with_hooks=False):
    project = self.config / "plugins/cache/fixture/demo/0.9.0"
    project.mkdir(parents=True)
    if with_hooks:
      (project / "hooks").mkdir()
      (project / "hooks/hooks.json").write_text(json.dumps({"hooks": {}}))
    data = json.loads(self.registry.read_text())
    data["plugins"][PLUGIN].append({"installPath": str(project), "scope": "project", "projectPath": str(self.home)})
    self.registry.write_text(json.dumps(data))
    return project

  def test_multiple_installations_without_hooks_are_silent(self):
    (self.hooks / "hooks.json").unlink()
    self.add_project_installation()
    self.assertEqual(self.daily(), "__SILENT__\n")
    self.assertFalse(self.approved.exists())

  def test_multiple_installations_inspect_approve_and_detect_each_change(self):
    project = self.add_project_installation(with_hooks=True)
    self.assertIn("未審", self.daily())
    inspected = self.inspect()
    self.assertEqual(set(inspected["installations"]), {str(self.plugin), str(project)})
    (project / "hooks/hooks.json").write_text(json.dumps({"hooks": {}}))
    self.assertNotEqual(self.run_cli("--approve-plugin", PLUGIN).returncode, 0)
    self.assertFalse(self.approved.exists())
    self.approve()
    before = self.approved.read_bytes()
    self.assertEqual(self.daily(), "__SILENT__\n")
    self.command_manifest("changed-user-installation")
    self.assertIn("未審", self.daily())
    self.assertEqual(self.approved.read_bytes(), before)
    self.approve()
    (project / "hooks/hooks.json").unlink()
    self.assertIn("未審", self.daily())
    project.joinpath("hooks").rmdir()
    project.rmdir()
    self.assertIn("遺失", self.daily())
    self.assertFalse(self.marker.exists())

  def test_multiple_installations_keep_malformed_location_visible(self):
    self.add_project_installation()
    data = json.loads(self.registry.read_text())
    data["plugins"][PLUGIN][1]["installPath"] = "relative/path"
    self.registry.write_text(json.dumps(data))
    self.assertIn("無法檢查", self.daily())
    self.assertFalse(self.approved.exists())

  def test_missing_referenced_module_without_approval_is_not_silent(self):
    self.manifest({"modules": ["./missing.ts"]})
    self.assertIn("無法檢查", self.daily())
    self.assertFalse(self.approved.exists())

  def test_disabled_plugin_does_not_create_a_new_approval(self):
    (self.config / "settings.json").write_text(json.dumps({"enabledPlugins": {PLUGIN: False}}))
    self.assertEqual(self.daily(), "__SILENT__\n")
    self.assertFalse(self.approved.exists())


class PopenCapture:
  """只覆寫 Popen 的 subprocess 代理。

  module 內的 subprocess 全域被換成它，測試才拿得到真的 Popen handle 去 wait；
  直接改 subprocess.Popen 會連測試自己的 subprocess 一起換掉，capturing wrapper 就遞迴了。
  """

  def __init__(self, original):
    self.original = original
    self.processes = []

  def Popen(self, *args, **kwargs):
    process = self.original.Popen(*args, **kwargs)
    self.processes.append(process)
    return process

  def __getattr__(self, name):
    return getattr(self.original, name)


class SkillUpOutputIsolationTest(unittest.TestCase):
  """同日多個 target 平行跑 skill-up 時，每個 target 要有自己的 output root，receipt 不互相覆蓋。"""

  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.home = Path(self.temp.name)
    self.runs = self.home / "eval-runs"
    self.markers = self.home / "markers"
    self.skill_up = self.home / "fake-skill-up"
    self.skill_up.write_text(FAKE_SKILL_UP)
    self.skill_up.chmod(0o755)
    # 背景 Popen 繼承的是行程環境，marker 變數要留到 launch 之後才看得到
    settings = {
      "SKILL_EVAL_RUNS_DIR": str(self.runs),
      "SKILL_UP_BIN": str(self.skill_up),
      "SKILL_CHANGES_STATE_DIR": str(self.home / "state"),
      "FAKE_SKILL_UP_MARKERS": str(self.markers),
      "FAKE_SKILL_UP_PEERS": "2",
    }
    saved = {key: os.environ.get(key) for key in settings}
    os.environ.update(settings)
    self.addCleanup(self.restore_env, saved)
    self.module = load_daily(settings)
    self.popen = PopenCapture(subprocess)
    self.module.subprocess = self.popen
    self.addCleanup(self.reap_processes)

  def restore_env(self, saved):
    for key, value in saved.items():
      if value is None:
        os.environ.pop(key, None)
      else:
        os.environ[key] = value

  def reap_processes(self):
    """測試中途失敗也要收乾淨：留著沒 wait 的子行程，unittest 收尾時會噴 ResourceWarning。"""
    for process in self.popen.processes:
      if process.poll() is None:
        process.terminate()
      try:
        process.wait(timeout=10)
      except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)

  def target(self, name):
    eval_dir = self.home / name
    (eval_dir / "evals").mkdir(parents=True)
    (eval_dir / "evals" / "eval.yaml").write_text("version: 1\n")
    return {"name": name, "kind": "skill", "dir": eval_dir, "eval_dir": eval_dir, "origin": "committed"}

  def await_results(self, expected, timeout=10.0):
    """有界等待背景 Popen 落地；逾時就 FAIL，不用固定 sleep 掩蓋競態。"""
    deadline = time.monotonic() + timeout
    found = []
    while time.monotonic() < deadline:
      found = sorted(self.runs.rglob("result.json"))
      if len(found) >= expected:
        return found
      time.sleep(0.05)
    self.fail(f"等 {timeout}s 只看到 {len(found)}/{expected} 份 result.json：{[str(p) for p in found]}")

  def assert_clean_exit(self, timeout=10.0):
    """result.json 是 fake runner 的最後一步，落地後才等 exit 並要求 0：先寫檔再崩的 runner 不算通過。"""
    self.assertTrue(self.popen.processes, "launch_skill_up 沒有留下任何 Popen handle")
    deadline = time.monotonic() + timeout
    for process in self.popen.processes:
      try:
        code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
      except subprocess.TimeoutExpired:
        self.fail(f"skill-up 子行程 pid {process.pid} 等 {timeout}s 還沒結束")
      self.assertEqual(code, 0, f"skill-up 子行程 pid {process.pid} exit {code}")

  def test_parallel_targets_keep_one_result_each_under_their_own_root(self):
    launched, error = self.module.launch_skill_up([self.target("alpha"), self.target("beta")], "2026-09-23")
    self.assertIsNone(error)
    self.assertEqual(launched, ["alpha", "beta"])
    found = self.await_results(2)
    self.assert_clean_exit()
    # marker 證明兩個 target 真的平行跑過；否則「只剩一份」會跟「第二個根本沒啟動」分不開
    self.assertEqual(sorted(p.stem for p in self.markers.glob("*.json")), ["alpha", "beta"])
    self.assertEqual([p.parent.parent.name for p in found], ["alpha", "beta"])
    self.assertEqual({p.parent.name for p in found}, {"iteration-1"})

  def test_collector_reads_per_target_and_legacy_root_level_results(self):
    legacy = self.runs / "iteration-104"
    legacy.mkdir(parents=True)
    (legacy / "result.json").write_text(json.dumps({"skill_name": "legacy-skill", "case_results": [{"status": "PASS"}]}))
    launched, error = self.module.launch_skill_up([self.target("alpha"), self.target("beta")], "2026-09-23")
    self.assertIsNone(error)
    self.assertEqual(launched, ["alpha", "beta"])
    self.await_results(3)
    self.assert_clean_exit()
    results = self.module.collect_skill_up_results(0)
    self.assertEqual({r["skill"] for r in results}, {"legacy-skill", "alpha", "beta"})
    self.assertEqual({r["skill"]: r["path"] for r in results}["alpha"], str(self.runs / "alpha" / "iteration-1" / "result.json"))


class SkillUpStatusRenderTest(unittest.TestCase):
  """skill-up 列要同時看得到 PASS／FAIL／ERROR 與 result.json 路徑；檔位才不會把 harness ERROR 當低。"""

  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.module = load_daily({"SKILL_EVAL_RUNS_DIR": str(Path(self.temp.name) / "unused-runs")})

  def target(self, name):
    return {name: {"name": name, "kind": "command", "dir": Path("."), "eval_dir": Path("."), "origin": "committed"}}

  def render(self, targets, results):
    return self.module.render("2026-10-12", targets, {}, None, [], None, results, {}, [])

  def line_with(self, report, needle):
    found = [line for line in report.splitlines() if needle in line]
    self.assertEqual(len(found), 1, report)
    return found[0]

  def test_both_routes_keep_path_status_and_tier(self):
    left = "/runs/left/iteration-1/result.json"
    right = "/runs/right/iteration-1/result.json"
    errored = "/runs/err-only/iteration-9/result.json"
    clean = "/runs/clean/iteration-2/result.json"
    results = [
      {"skill": "dup", "iteration": "iteration-1", "passed": 2, "failed": 1, "errored": 1, "path": left},
      {"skill": "dup", "iteration": "iteration-1", "passed": 3, "failed": 0, "errored": 0, "path": right},
      {"skill": "err-only", "iteration": "iteration-9", "passed": 0, "failed": 0, "errored": 2, "path": errored},
      {"skill": "clean", "iteration": "iteration-2", "passed": 4, "failed": 0, "errored": 0, "path": clean},
    ]
    via_target = self.render(self.target("dup"), results)
    fail_line = self.line_with(via_target, left)
    self.assertIn("2 PASS／1 FAIL／1 ERROR", fail_line)
    self.assertIn(right, via_target)
    self.assertIn("3 PASS／0 FAIL／0 ERROR", self.line_with(via_target, right))
    self.assertIn("## dup（command，committed）\n- 建議檔位：高", via_target)
    self.assertIn("建議檔位：中", self.line_with(via_target, errored))
    self.assertIn("0 PASS／0 FAIL／2 ERROR", self.line_with(via_target, errored))
    self.assertIn("建議檔位：低", self.line_with(via_target, clean))
    self.assertIn("建議檔位彙總：高 1／中 1／低 1", via_target)
    via_fallback = self.render({**self.target("err-only"), **self.target("clean")}, results)
    self.assertIn("## err-only（command，committed）\n- 建議檔位：中", via_fallback)
    self.assertIn(errored, self.line_with(via_fallback, "0 PASS／0 FAIL／2 ERROR"))
    self.assertIn("## clean（command，committed）\n- 建議檔位：低", via_fallback)
    self.assertIn("建議檔位：高", self.line_with(via_fallback, left))
    self.assertIn("建議檔位：低", self.line_with(via_fallback, right))
    self.assertNotIn("建議檔位：低", self.line_with(via_fallback, errored))

  def test_result_json_keeps_distinct_runs_and_errors(self):
    # 形狀與 2026-10-12 三份 result.json 的計數相同：兩條 iteration-1、一條 FAIL+ERROR。
    rels = [
      "run-a/iteration-1/result.json",
      "run-b/iteration-1/result.json",
      "run-c/iteration-8/result.json",
    ]
    counts = [(10, 6, 0), (8, 8, 0), (8, 5, 3)]
    runs = Path(self.temp.name) / "eval-runs"
    for rel, (passed, failed, errored) in zip(rels, counts):
      dest = runs / rel
      dest.parent.mkdir(parents=True, exist_ok=True)
      cases = [{"status": "PASS"}] * passed + [{"status": "FAIL"}] * failed + [{"status": "ERROR"}] * errored
      dest.write_text(json.dumps({"skill_name": "research-before-answer", "case_results": cases}))
    self.module.EVAL_RUNS = runs
    results = self.module.collect_skill_up_results(0)
    self.assertEqual(len(results), 3)
    self.assertTrue(all(r["skill"] == "research-before-answer" for r in results))
    by_suffix = {next(rel for rel in rels if rel in r["path"]): r for r in results}
    self.assertEqual((by_suffix[rels[0]]["passed"], by_suffix[rels[0]]["failed"], by_suffix[rels[0]]["errored"]), (10, 6, 0))
    self.assertEqual((by_suffix[rels[1]]["passed"], by_suffix[rels[1]]["failed"], by_suffix[rels[1]]["errored"]), (8, 8, 0))
    self.assertEqual((by_suffix[rels[2]]["passed"], by_suffix[rels[2]]["failed"], by_suffix[rels[2]]["errored"]), (8, 5, 3))
    fallback = self.render({}, results)
    target = self.render(self.target("research-before-answer"), results)
    for report in (fallback, target):
      self.assertIn("10 PASS／6 FAIL／0 ERROR", self.line_with(report, by_suffix[rels[0]]["path"]))
      self.assertIn("8 PASS／8 FAIL／0 ERROR", self.line_with(report, by_suffix[rels[1]]["path"]))
      self.assertIn("8 PASS／5 FAIL／3 ERROR", self.line_with(report, by_suffix[rels[2]]["path"]))
      self.assertNotEqual(self.line_with(report, rels[0]), self.line_with(report, rels[1]))
    self.assertIn("上一輪啟動的 skill-up 回歸結果", fallback)
    self.assertNotIn("上一輪啟動的 skill-up 回歸結果", target)
    self.assertIn("## research-before-answer（command，committed）\n- 建議檔位：高", target)
    self.assertIn("skill-up 自動背景回歸已暫停", target)

  def test_paused_skill_is_not_launched_by_launch_skill_up(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      module = load_daily({
        "SKILL_EVAL_RUNS_DIR": str(root / "eval-runs"),
        "SKILL_UP_BIN": str(root / "fake-skill-up"),
        "SKILL_CHANGES_STATE_DIR": str(root / "state"),
      })
      fake = root / "fake-skill-up"
      fake.write_text("#!/bin/sh\nexit 0\n")
      fake.chmod(0o755)
      rba_dir = root / "research-before-answer"
      (rba_dir / "evals").mkdir(parents=True)
      (rba_dir / "evals" / "eval.yaml").write_text("version: 1\n")
      launched, err = module.launch_skill_up(
        [{"name": "research-before-answer", "kind": "skill", "dir": rba_dir, "eval_dir": rba_dir, "origin": "committed"}],
        "2026-11-19",
      )
      self.assertEqual(launched, [])
      self.assertIsNone(err)


class ChaosAndResilienceTest(unittest.TestCase):
  """混沌測試：壞收據隔離、損毀 state、異常 runner JSON、不可執行 skill-up、git rename/non-ASCII/刪除。"""

  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.home = Path(self.temp.name)
    self.config = self.home / ".claude"
    (self.config / "plugins").mkdir(parents=True)
    (self.config / "settings.json").write_text(json.dumps({"enabledPlugins": {}}))
    (self.config / "plugins/installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {}}))
    subprocess.run(["git", "init", "-q", str(self.config)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(self.config), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-q", "--allow-empty", "-m", "init"], check=True, capture_output=True)
    self.runs = self.home / "eval-runs"
    self.state_dir = self.home / "daily-state"
    self.report = self.home / "report.md"
    self.env = {
      **os.environ,
      "HOME": str(self.home),
      "SKILL_CHANGES_STATE_DIR": str(self.state_dir),
      "SKILL_EVAL_RUNS_DIR": str(self.runs),
    }

  def run_cli(self, *args, extra_env=None):
    env = {**self.env, **(extra_env or {})}
    return subprocess.run([sys.executable, str(DAILY), *args], env=env, capture_output=True, text=True, timeout=10)

  def test_corrupt_skill_up_receipts_are_isolated_and_reported_alongside_valid_ones(self):
    # BUG-01: non-dict JSON, non-list case_results, non-dict case, bad skill_name, truncated JSON, bad UTF-8, missing case_results
    cases = {
      "valid-skill/iteration-1/result.json": json.dumps({"skill_name": "valid-skill", "case_results": [{"status": "PASS"}]}).encode("utf-8"),
      "list-root/iteration-1/result.json": b"[]",
      "null-root/iteration-1/result.json": b"null",
      "bad-cases-type/iteration-1/result.json": json.dumps({"skill_name": "bad-cases-type", "case_results": 123}).encode("utf-8"),
      "non-dict-case/iteration-1/result.json": json.dumps({"skill_name": "non-dict-case", "case_results": [None, "PASS"]}).encode("utf-8"),
      "bad-skill-name/iteration-1/result.json": json.dumps({"skill_name": ["unhashable"], "case_results": [{"status": "PASS"}]}).encode("utf-8"),
      "truncated/iteration-1/result.json": b'{"skill_name": "truncated", "case_results": [',
      "bad-utf8/iteration-1/result.json": b"\xff\xfe\x00invalid",
      "missing-cases/iteration-1/result.json": json.dumps({"skill_name": "missing-cases"}).encode("utf-8"),
    }
    for rel, raw in cases.items():
      p = self.runs / rel
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_bytes(raw)
    proc = self.run_cli("--out", str(self.report), "--no-skill-up")
    self.assertEqual(proc.returncode, 0, proc.stderr)
    report = self.report.read_text()
    # Valid receipt is preserved as low tier
    self.assertIn("valid-skill iteration-1：1 PASS／0 FAIL／0 ERROR", report)
    # Every corrupt receipt must appear with its path and be at least medium tier (never silently dropped or low tier)
    for rel in cases:
      if rel.startswith("valid-skill"):
        continue
      full_path = str(self.runs / rel)
      matched = [line for line in report.splitlines() if full_path in line]
      self.assertEqual(len(matched), 1, f"missing attributable diagnostic for {rel}:\n{report}")
      self.assertIn("建議檔位：中", matched[0], f"corrupt receipt {rel} must not be low tier: {matched[0]}")

  def test_corrupt_state_fields_do_not_crash_and_surface_warning(self):
    # BUG-03: null/string/NaN last_run_epoch, non-dict uncommitted_stamps, corrupt state.json
    self.state_dir.mkdir(parents=True, exist_ok=True)
    # Add an uncommitted command so changed_paths actually accesses seen_uncommitted.get(...)
    cmd = self.config / "commands/demo.md"
    cmd.parent.mkdir(parents=True, exist_ok=True)
    cmd.write_text("# demo\n")
    eval_yaml = self.config / "evals/demo/evals/eval.yaml"
    eval_yaml.parent.mkdir(parents=True, exist_ok=True)
    eval_yaml.write_text("tests: []\n")

    for bad_state in (
      json.dumps({"last_run_epoch": None, "uncommitted_stamps": ["not-a-dict"]}),
      json.dumps({"last_run_epoch": "not-a-number", "uncommitted_stamps": "bad"}),
      '{"last_run_epoch": NaN, "uncommitted_stamps": {}}',
      "{truncated state",
    ):
      (self.state_dir / "state.json").write_text(bad_state)
      proc = self.run_cli("--out", str(self.report), "--no-skill-up")
      self.assertEqual(proc.returncode, 0, f"crashed on state={bad_state}: {proc.stderr}")
      text = self.report.read_text()
      self.assertIn("## 本輪限制", text, f"expected state warning in report for {bad_state}")
      self.assertIn("state.json", text, f"expected state.json diagnostic for {bad_state}")

  def test_run_evaluator_handles_non_dict_json_and_malformed_tiers(self):
    # BUG-02: runner outputting [] / null / non-dict tier1 must return structured error, not AttributeError
    fake_runner = self.home / "fake-runner.py"
    skill_dir = self.config / "skills/alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: alpha\n---\n")
    mod = load_daily({
      "HOME": str(self.home),
      "SKILL_CHANGES_STATE_DIR": str(self.state_dir),
      "SKILL_EVAL_RUNS_DIR": str(self.runs),
    })
    mod.RUNNER = fake_runner
    target = {"name": "alpha", "kind": "skill", "dir": skill_dir, "eval_dir": skill_dir, "origin": "uncommitted"}

    for payload in ("[]", "null", json.dumps({"skills": "bad"}), json.dumps({"skills": [None]})):
      fake_runner.write_text(f"import sys\nprint({payload!r})\n")
      per, err = mod.run_evaluator([target], "2026-11-23")
      self.assertIsInstance(per, dict)
      self.assertTrue(err, f"expected runner error for payload={payload}, got per={per}, err={err}")

    # Non-dict tier1/tier2_intra inside a skill entry must not crash tier_for
    fake_runner.write_text(
      "import json\n"
      "print(json.dumps({'skills': [{'skill_name': 'alpha', 'tier1': 'bad', 'tier2_intra': 42}], 'tier2_preflight': 'bad'}))\n"
    )
    per, err = mod.run_evaluator([target], "2026-11-23")
    tier, reasons = mod.tier_for(target, per.get("alpha"), [], err)
    self.assertEqual(tier, "中")
    self.assertTrue(reasons)

  def test_launch_skill_up_handles_non_executable_binary_without_crashing(self):
    # BUG-04: SKILL_UP exists (is_file=True) but lacks +x -> Popen raises PermissionError
    bad_bin = self.home / "non-exec-skill-up"
    bad_bin.write_text("#!/bin/sh\nexit 0\n")
    bad_bin.chmod(0o644)
    eval_dir = self.home / "alpha"
    (eval_dir / "evals").mkdir(parents=True)
    (eval_dir / "evals/eval.yaml").write_text("tests: []\n")
    mod = load_daily({
      "SKILL_UP_BIN": str(bad_bin),
      "SKILL_CHANGES_STATE_DIR": str(self.state_dir),
      "SKILL_EVAL_RUNS_DIR": str(self.runs),
    })
    launched, err = mod.launch_skill_up(
      [{"name": "alpha", "kind": "skill", "dir": eval_dir, "eval_dir": eval_dir, "origin": "uncommitted"}],
      "2026-11-23",
    )
    self.assertEqual(launched, [])
    self.assertIsNotNone(err)
    self.assertIn("alpha", err)

  def test_git_rename_non_ascii_and_deleted_targets_are_handled_cleanly(self):
    # BUG-05: rename, non-ASCII quoted filename, and deleted command/skill with leftover evals
    # 1) Rename staged command: commands/old.md -> commands/renamed.md
    commands = self.config / "commands"
    commands.mkdir(parents=True, exist_ok=True)
    (commands / "old.md").write_text("v1\n")
    (commands / "deleted.md").write_text("v1\n")
    for name in ("renamed", "deleted", "中文指令"):
      p = self.config / "evals" / name / "evals"
      p.mkdir(parents=True, exist_ok=True)
      (p / "eval.yaml").write_text("tests: []\n")
    subprocess.run(["git", "-C", str(self.config), "add", "commands/old.md", "commands/deleted.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(self.config), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "add cmds"], check=True, capture_output=True)
    # Seed watermark at this commit so only uncommitted rename/non-ASCII/delete are tested
    self.assertEqual(self.run_cli("--out", str(self.report), "--no-skill-up").returncode, 0)

    # Now perform: rename old.md -> renamed.md, delete deleted.md, create non-ASCII 中文指令.md
    subprocess.run(["git", "-C", str(self.config), "mv", "commands/old.md", "commands/renamed.md"], check=True, capture_output=True)
    (commands / "deleted.md").unlink()
    (commands / "中文指令.md").write_text("# zh\n")

    proc = self.run_cli("--out", str(self.report), "--no-skill-up")
    self.assertEqual(proc.returncode, 0, proc.stderr)
    report = self.report.read_text()
    self.assertIn("## renamed（command，uncommitted）", report)
    self.assertIn("## 中文指令（command，uncommitted）", report)
    self.assertNotIn("## deleted（command", report)
    self.assertNotIn("->", report)
    # Next run with no edits must be silent (deleted file must not loop forever)
    proc2 = self.run_cli("--out", str(self.report), "--no-skill-up")
    self.assertEqual(proc2.returncode, 0, proc2.stderr)
    self.assertEqual(self.report.read_text(), "__SILENT__\n")

  def test_collect_since_epoch_boundary_and_nonstandard_failure_status_and_tier_for(self):
    # Exact boundary mtime == since_epoch must be excluded; non-PASS/ERROR status (e.g. TIMEOUT) counts as failed
    mod = load_daily({
      "HOME": str(self.home),
      "SKILL_CHANGES_STATE_DIR": str(self.state_dir),
      "SKILL_EVAL_RUNS_DIR": str(self.runs),
    })
    boundary_epoch = 1700000000.0
    at_boundary = self.runs / "boundary-skill/iteration-1/result.json"
    at_boundary.parent.mkdir(parents=True, exist_ok=True)
    at_boundary.write_text(json.dumps({"skill_name": "boundary-skill", "case_results": [{"status": "PASS"}]}))
    os.utime(at_boundary, (boundary_epoch, boundary_epoch))

    newer = self.runs / "timeout-skill/iteration-1/result.json"
    newer.parent.mkdir(parents=True, exist_ok=True)
    newer.write_text(json.dumps({"skill_name": "timeout-skill", "case_results": [{"status": "TIMEOUT"}]}))
    os.utime(newer, (boundary_epoch + 10, boundary_epoch + 10))

    collected = mod.collect_skill_up_results(boundary_epoch)
    self.assertEqual([r["skill"] for r in collected], ["timeout-skill"])
    self.assertEqual(collected[0]["failed"], 1)
    self.assertEqual(collected[0]["passed"], 0)
    self.assertEqual(collected[0]["errored"], 0)

    # Verify tier_for classification for Tier 1 failure (高) and Tier 2 findings (中)
    skill_target = {"name": "s", "kind": "skill", "dir": Path("."), "eval_dir": Path("."), "origin": "committed"}
    t1_tier, _ = mod.tier_for(skill_target, {"tier1": {"status": "failed", "finding_count": 2}, "tier2": {"status": "passed"}}, [], None)
    self.assertEqual(t1_tier, "高")
    t2_tier, _ = mod.tier_for(skill_target, {"tier1": {"status": "passed"}, "tier2": {"status": "findings", "finding_count": 1}}, [], None)
    self.assertEqual(t2_tier, "中")
    clean_tier, _ = mod.tier_for(skill_target, {"tier1": {"status": "passed"}, "tier2": {"status": "passed"}}, [], None)
    self.assertEqual(clean_tier, "低")


if __name__ == "__main__":
  unittest.main()
