import json
import os
from pathlib import Path
import tempfile


def locations(config):
  settings = json.loads((config / "settings.json").read_text())
  installed = json.loads((config / "plugins/installed_plugins.json").read_text())
  enabled = settings.get("enabledPlugins")
  plugins = installed.get("plugins")
  if not isinstance(enabled, dict) or not isinstance(plugins, dict):
    raise ValueError("installed plugin inventory has an unknown format")
  found = {}
  errors = []
  for name, active in sorted(enabled.items()):
    if active is not True:
      continue
    records = plugins.get(name)
    if not isinstance(records, list) or not records:
      errors.append({"plugin": name, "status": "遺失", "category": "安裝記錄"})
      continue
    paths = {record.get("installPath") for record in records if isinstance(record, dict)}
    if len(paths) != 1 or not all(isinstance(path, str) and Path(path).is_absolute() for path in paths):
      errors.append({"plugin": name, "status": "無法檢查", "category": "安裝位置"})
      continue
    found[name] = Path(next(iter(paths)))
  return found, errors


def snapshot(plugin):
  try:
    root = plugin.resolve(strict=True)
    manifest_path = plugin / "hooks/hooks.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
      return None, "no-hooks"
    manifest = manifest_path.resolve(strict=True)
    if not manifest.is_relative_to(root) or not manifest.is_file():
      raise ValueError("hook manifest is outside its installation root")
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict):
      raise ValueError("hook manifest has an unknown format")
    commands = data.get("hooks")
    modules = data.get("modules")
    if commands is None and modules is None:
      raise ValueError("hook manifest has an unknown format")
    if commands is not None and (not isinstance(commands, dict) or not all(isinstance(items, list) for items in commands.values())):
      raise ValueError("command hooks have an unknown format")
    if modules is not None and (not isinstance(modules, list) or not all(isinstance(item, str) for item in modules)):
      raise ValueError("function hooks have an unknown format")
    # 只記 mtime＋size、不存原文：同 mtime 同大小的原地改寫看不到，這是刻意接受的限度。
    module_stats = {}
    for relative in modules or []:
      try:
        path = (manifest.parent / relative).resolve(strict=True)
      except FileNotFoundError:
        return None, "無法檢查"
      if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("module is outside its installation root or not a file")
      stat = path.stat()
      module_stats[relative] = [stat.st_mtime_ns, stat.st_size]
    return {"manifest": data, "modules": module_stats}, None
  except FileNotFoundError:
    return None, "遺失"
  except (OSError, ValueError, RuntimeError, TypeError):
    return None, "無法檢查"


def read_state(path):
  if not path.exists():
    return {}
  data = json.loads(path.read_text())
  if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("plugins"), dict):
    raise ValueError("plugin hook state has an unknown format")
  plugins = data["plugins"]
  if not all(isinstance(value, dict) for value in plugins.values()):
    raise ValueError("plugin hook state has an invalid entry")
  return plugins


def inspected_path(approved_path):
  return approved_path.with_name("inspected.json")


def write_state(path, plugins):
  path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
  temporary = None
  try:
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
      temporary = Path(handle.name)
      os.chmod(temporary, 0o600)
      json.dump({"version": 1, "plugins": plugins}, handle, sort_keys=True, indent=2)
      handle.write("\n")
    os.replace(temporary, path)
  finally:
    if temporary is not None and temporary.exists():
      temporary.unlink()


def scan(config, approved_path):
  try:
    installed, errors = locations(config)
    approved = read_state(approved_path)
  except (OSError, ValueError, TypeError):
    return [{"plugin": "plugin inventory", "status": "無法檢查", "category": "清單或批准基準"}]
  events = list(errors)
  for name, root in sorted(installed.items()):
    current, error = snapshot(root)
    if error == "no-hooks" and name not in approved:
      continue
    if error:
      events.append({"plugin": name, "status": "遺失" if error == "no-hooks" else error, "category": "hook 內容"})
      continue
    old = approved.get(name)
    if old is None:
      events.append({"plugin": name, "status": "未審", "category": "新增"})
      continue
    content = old.get("content")
    if content == current:
      continue
    if not isinstance(content, dict):
      events.append({"plugin": name, "status": "未審", "category": "舊格式批准需重新批准"})
      continue
    categories = []
    if content.get("manifest") != current["manifest"]:
      categories.append("manifest")
    if content.get("modules") != current["modules"]:
      categories.append("module")
    events.append({"plugin": name, "status": "未審", "category": "、".join(categories)})
  return events


def current_content(config, name):
  installed, errors = locations(config)
  if name not in installed:
    raise ValueError(f"plugin is not an enabled installation: {name}; {errors}")
  current, error = snapshot(installed[name])
  if error:
    raise ValueError(f"plugin hook cannot be inspected: {error}")
  return current


def inspect(config, approved_path, name):
  current = current_content(config, name)
  inspected = read_state(inspected_path(approved_path))
  inspected[name] = {"content": current}
  write_state(inspected_path(approved_path), inspected)
  return {"plugin": name, **current, "approved": read_state(approved_path).get(name, {}).get("content") == current}


def approve(config, approved_path, name):
  current = current_content(config, name)
  inspected = read_state(inspected_path(approved_path))
  if name not in inspected:
    raise ValueError("no inspection on record; inspect the plugin before approving")
  if inspected[name].get("content") != current:
    raise ValueError("hook content changed since inspection; approval refused")
  approved = read_state(approved_path)
  approved[name] = {"content": current}
  write_state(approved_path, approved)
  del inspected[name]
  write_state(inspected_path(approved_path), inspected)
  return {"plugin": name, "approved": True}
