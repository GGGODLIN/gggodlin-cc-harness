#!/usr/bin/env bash
# cc-tool-updates-daily.sh — local-analysis shell channel
# 枚舉 6 manager（含 mcp-npx：~/.claude.json 裡 npx 釘版的 MCP server，2026-08-25 加）+ 三名單分類 + 比對 upstream → 預設 markdown report（無更新+無新發現 → __SILENT__）。
# --json：結構化輸出給測試。graceful：任何查詢失敗進 errors、不中斷、exit 0。
# 名單同目錄：cc-tool-manifest.json（白）/ cc-tool-ignore.txt（黑）。
# 重要性判斷（該升/可緩）交給 workflow digest LLM 階段，本 script 只附 release notes 摘要當素材。
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CCTOOL_DIR="$DIR"
case " $* " in
  *" --json "*) : ;;
  *)
    SI="$HOME/code/social-info"
    DATE="${LOCAL_ANALYSIS_DATE:-$(date +%F)}"
    export CCTOOL_OUT="${CCTOOL_OUT:-$SI/reports/local-analysis/$DATE-tool-updates.md}"
    mkdir -p "$(dirname "$CCTOOL_OUT")" 2>/dev/null || true
  ;;
esac
python3 - "$@" <<'PY'
import sys, os, json, re, shutil, subprocess, urllib.request, base64

DIR = os.environ["CCTOOL_DIR"]
JSON_OUT = "--json" in sys.argv[1:]
MANIFEST = os.environ.get("CCTOOL_MANIFEST") or os.path.join(DIR, "cc-tool-manifest.json")
IGNORE = os.environ.get("CCTOOL_IGNORE") or os.path.join(DIR, "cc-tool-ignore.txt")
UPGRADE_NOTES = os.environ.get("CCTOOL_UPGRADE_NOTES") or os.path.expanduser("~/.claude/references/tool-upgrade-notes.json")

def run(args, timeout=20):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None

def run_raw(args, timeout=20):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return None

def load_manifest():
    try:
        return json.load(open(MANIFEST))
    except Exception:
        return []

def load_ignore():
    try:
        return set(l.strip() for l in open(IGNORE) if l.strip() and not l.startswith("#"))
    except Exception:
        return set()

def load_upgrade_notes():
    try:
        value = json.load(open(UPGRADE_NOTES))
        return value.get("tools", {}) if value.get("schema_version") == 1 else {}
    except Exception:
        return {}

def norm(v):
    return re.sub(r'^v', '', (v or "").strip())

def pep503_norm(n):
    return re.sub(r'[-_.]+', '-', n or "").lower()

# ---- installed 偵測 ----
def cargo_git_installed():
    out = {}
    try:
        d = json.load(open(os.path.expanduser("~/.cargo/.crates2.json")))
    except Exception:
        return out
    for k, v in d.get("installs", {}).items():
        m = re.match(r'(\S+)\s+(\S+)\s+\(git\+(\S+?)(?:\?(tag|branch|rev)=([^#]+))?#([0-9a-f]+)\)', k)
        if not m:
            continue
        pkg, _ver, url, _rt, ref, commit = m.groups()
        repo = re.sub(r'https?://github.com/|\.git$', '', url)
        for b in (v.get("bins") or [pkg]):
            out[b] = {"repo": repo, "tag": ref, "commit": commit}
    return out

def mcp_npx_installed():
    paths = os.environ.get("CCTOOL_CLAUDE_JSON")
    paths = paths.split(os.pathsep) if paths is not None else [
        os.path.expanduser("~/.claude.json")]
    out = {}
    for path in paths:
        try:
            servers = json.load(open(path)).get("mcpServers", {})
        except Exception:
            continue
        for name, cfg in servers.items():
            if not isinstance(cfg, dict) or cfg.get("command") not in ("npx", "bunx"):
                continue
            for arg in cfg.get("args") or []:
                m = re.match(r'^(-y|--yes)$', str(arg))
                if m:
                    continue
                m = re.match(r'^((?:@[^/@]+/)?[^@\s]+)(?:@([^\s]+))?$', str(arg))
                if m and not str(arg).startswith("-"):
                    out.setdefault(name, []).append({"package": m.group(1), "pin": m.group(2), "config": path})
                    break
    return out

def brew_installed():
    # 一個 formula 留多個 keg 時 `brew list --versions` 會在同一行列出全部，
    # 而且順序無保證（實測 `sqlite 3.53.0 3.51.3 3.53.2`）。原本取 p[-1] 等於
    # 隨機挑一個 keg，通常是舊的 → 已升級的工具每天被回報「有新版」。
    # 2026-07-30 實測誤報：ast-grep（0.45.0 0.44.1）、beads（1.1.2 1.1.0）兩個
    # 白名單工具連日假陽性。改成按版本取最大。
    out = {}
    s = run(["brew", "list", "--versions", "--formula"])
    if s:
        for line in s.splitlines():
            p = line.split()
            if len(p) >= 2:
                out[p[0]] = max(p[1:], key=_vkey)
    return out

def brew_leaves():
    s = run(["brew", "leaves"])
    return [l.strip() for l in s.splitlines() if l.strip()] if s else []

def _vkey(v):
    base, _, revision = norm(v).partition("_")
    values = [int(x) if x.isdigit() else 0 for x in re.split(r'[.\-+]', base)[:4]]
    parts = tuple((values + [0] * 4)[:4])
    return parts + (int(revision) if revision.isdigit() else 0,)

def npm_global_roots():
    override = os.environ.get("CCTOOL_NPM_ROOTS")
    if override is not None:
        return [r for r in override.split(os.pathsep) if os.path.isdir(r)]
    import glob
    roots = ["/opt/homebrew/lib/node_modules", "/usr/local/lib/node_modules"]
    nvm = glob.glob(os.path.expanduser("~/.nvm/versions/node/v*"))
    if nvm:
        newest = max(nvm, key=lambda p: _vkey(os.path.basename(p)))
        roots.append(os.path.join(newest, "lib/node_modules"))
    return [r for r in roots if os.path.isdir(r)]

def npm_g_installed():
    found = {}
    def read_pkg(package_dir, root):
        try:
            package = json.load(open(os.path.join(package_dir, "package.json")))
            name = package.get("name")
            version = package.get("version")
            if not name or not version:
                return
            raw_bins = package.get("bin")
            if isinstance(raw_bins, str):
                bins = {name.rsplit("/", 1)[-1]: raw_bins}
            elif isinstance(raw_bins, dict):
                bins = {key: value for key, value in raw_bins.items() if isinstance(key, str) and isinstance(value, str)}
            else:
                bins = {}
            found.setdefault(name, []).append({
                "version": version,
                "root": root,
                "package_dir": package_dir,
                "bins": bins,
            })
        except Exception:
            pass
    for root in npm_global_roots():
        for entry in os.listdir(root):
            path = os.path.join(root, entry)
            if not os.path.isdir(path):
                continue
            if entry.startswith("@"):
                for sub in os.listdir(path):
                    read_pkg(os.path.join(path, sub), root)
            else:
                read_pkg(path, root)
    out = {}
    for name, installs in found.items():
        active_candidates = []
        seen_candidates = set()
        for install in installs:
            package_root = os.path.realpath(install["package_dir"]) + os.sep
            for bin_name, target in install["bins"].items():
                executable = shutil.which(bin_name)
                if not executable:
                    continue
                executable_real = os.path.realpath(executable)
                target_real = os.path.realpath(os.path.join(install["package_dir"], target))
                if executable_real == target_real or executable_real.startswith(package_root):
                    key = (install["root"], install["package_dir"])
                    if key not in seen_candidates:
                        active_candidates.append(install)
                        seen_candidates.add(key)
                    break
        active = active_candidates[0] if len(active_candidates) == 1 else None
        active_error = None
        if len(active_candidates) > 1:
            choices = ", ".join(f"{item['version']} @ {item['root']}" for item in active_candidates)
            active_error = f"ambiguous active installs: {choices}"
        others = sorted(
            ({"version": install["version"], "root": install["root"]} for install in installs if install is not active),
            key=lambda item: (_vkey(item["version"]), item["root"]),
            reverse=True,
        )
        out[name] = {
            "active": {"version": active["version"], "root": active["root"]} if active else None,
            "others": others,
            "error": active_error,
        }
    return out

def uv_installed():
    import glob
    out = {}
    tools_root = os.path.expanduser("~/.local/share/uv/tools")
    if os.path.isdir(tools_root):
        for tool_name in os.listdir(tools_root):
            tool_dir = os.path.join(tools_root, tool_name)
            if not os.path.isdir(tool_dir):
                continue
            target = pep503_norm(tool_name)
            for meta in glob.glob(os.path.join(tool_dir, "lib/python*/site-packages/*.dist-info/METADATA")):
                try:
                    name = ver = None
                    with open(meta) as f:
                        for line in f:
                            if line.startswith("Name: "):
                                name = line[6:].strip()
                            elif line.startswith("Version: "):
                                ver = line[9:].strip()
                            if name and ver:
                                break
                    if name and ver and pep503_norm(name) == target:
                        out[tool_name] = ver
                        break
                except Exception:
                    pass
    s = run(["uv", "tool", "list"])
    if s:
        for line in s.splitlines():
            m = re.match(r'(\S+)\s+v?([\d.]+)', line)
            if m and m.group(1) not in out:
                out[m.group(1)] = m.group(2)
    return out

def uv_git_commit(tool_name):
    import glob
    target = pep503_norm(tool_name)
    tool_dir = os.path.expanduser(f"~/.local/share/uv/tools/{tool_name}")
    for direct_url in glob.glob(os.path.join(tool_dir, "lib/python*/site-packages/*.dist-info/direct_url.json")):
        metadata = os.path.join(os.path.dirname(direct_url), "METADATA")
        try:
            name = None
            with open(metadata) as f:
                for line in f:
                    if line.startswith("Name: "):
                        name = line[6:].strip()
                        break
            if pep503_norm(name or "") != target:
                continue
            with open(direct_url) as f:
                return json.load(f).get("vcs_info", {}).get("commit_id")
        except Exception:
            continue
    return None

def mcp_list():
    s = run(["claude", "mcp", "list"])
    names = []
    if s:
        for line in s.splitlines():
            m = re.match(r'([A-Za-z0-9_-]+):', line.strip())
            if m:
                names.append(m.group(1))
    return names

# ---- upstream latest ----
def gh_latest(repo):
    s = run(["gh", "api", f"repos/{repo}/releases/latest", "--jq", ".tag_name"])
    if s and s.strip():
        return s.strip()
    s = run(["gh", "api", f"repos/{repo}/tags", "--jq", ".[0].name"])
    return s.strip() if s and s.strip() else None

def gh_notes(repo, tag):
    s = run(["gh", "api", f"repos/{repo}/releases/tags/{tag}", "--jq", ".body"])
    return " ".join(s.split())[:200] if s else ""

def gh_head(repo):
    s = run(["gh", "api", f"repos/{repo}/commits/HEAD", "--jq", ".sha"])
    return s.strip() if s else None

def npm_min_release_age():
    s = run(["npm", "config", "get", "min-release-age"])
    try:
        return max(int((s or "").strip()), 0)
    except ValueError:
        return 0

def npm_latest(pkg):
    s = run(["npm", "view", pkg, "version"])
    return s.strip() if s else None

def npm_installable(pkg, min_age_days, run_date):
    newest = npm_latest(pkg)
    if not newest or min_age_days <= 0:
        return newest, None
    s = run(["npm", "view", pkg, "time", "--json"])
    try:
        times = json.loads(s or "")
    except ValueError:
        return newest, None
    import datetime as _dt
    # npm 的 min-release-age 以發布時間戳算足 N×24 小時、不是日期差；只比日期會在解禁日當天早幾小時
    # 把版本列成可裝，實裝就 ETARGET（2026-10-02 backpass 0.1.28／acpx 0.19.3）。當日真跑用現在時刻，
    # 指定過去日期（測試、補跑）用該日 00:00 UTC 維持可重現。
    now = _dt.datetime.now(_dt.timezone.utc)
    run_at = now if run_date == _dt.date.today().isoformat() else _dt.datetime.fromisoformat(run_date).replace(tzinfo=_dt.timezone.utc)
    cutoff = run_at - _dt.timedelta(days=min_age_days)
    def published(v):
        return _dt.datetime.fromisoformat(times[v].replace("Z", "+00:00"))
    stable = [v for v in times if v not in ("created", "modified") and "-" not in v]
    aged = [v for v in stable if published(v) <= cutoff]
    installable = max(aged, key=_vkey) if aged else None
    if installable is None or _vkey(newest) <= _vkey(installable):
        return installable, None
    pending = {"version": newest, "published": times[newest][:10], "unlock_date": (published(newest) + _dt.timedelta(days=min_age_days)).date().isoformat()}
    return installable, pending

def pypi_latest(pkg):
    try:
        with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=15) as r:
            return json.load(r)["info"]["version"]
    except Exception:
        return None

def brew_latest(formula):
    s = run(["brew", "info", "--json=v2", formula])
    if not s:
        return None
    try:
        info = (json.loads(s).get("formulae") or [{}])[0]
        stable = info.get("versions", {}).get("stable")
        revision = info.get("revision") or 0
        return f"{stable}_{revision}" if stable and revision else stable
    except Exception:
        return None

PIN_VERSION = "2.1.246"
PIN_REPO = "anthropics/claude-code"
PIN_ISSUES = ["90299", "90537"]

def pin_check():
    if os.environ.get("CCTOOL_PIN_CHECK") == "0":
        return None
    states = []
    for num in PIN_ISSUES:
        s = run(["gh", "api", f"repos/{PIN_REPO}/issues/{num}", "--jq", ".state"])
        if s and s.strip() in ("open", "closed"):
            states.append((num, s.strip()))
        else:
            return {"error": f"cannot read issue #{num} state"}
    releases = run(["gh", "api", f"repos/{PIN_REPO}/releases?per_page=100", "--jq", ".[].tag_name"])
    if releases is None:
        return {"error": "cannot list candidate releases"}
    candidates = [t for t in releases.split() if _vkey(norm(t)) > _vkey(PIN_VERSION)]
    try:
        s = run(["gh", "api", f"repos/{PIN_REPO}/contents/CHANGELOG.md", "--jq", ".content"])
        changelog = base64.b64decode(s).decode("utf-8", "replace") if s else None
    except Exception:
        changelog = None
    if not changelog:
        return {"error": "cannot read CHANGELOG.md"}
    candidate_versions = {norm(t) for t in candidates}
    newer_sections = []
    for section in re.split(r'(?:^|\n)## ', changelog)[1:]:
        lines = section.splitlines()
        if lines and lines[0].strip() in candidate_versions:
            newer_sections.append(section)
    closed = [num for num, st in states if st == "closed"]
    matched = []
    for section in newer_sections:
        if "sticky prompt" in section.lower():
            matched.append("sticky prompt")
        matched += ["#" + num for num in PIN_ISSUES if f"#{num}" in section]
    if not closed and not matched:
        return None
    return {"closed": closed, "matched": matched, "candidates": candidates}

manifest = load_manifest()
ignore = load_ignore()
upgrade_notes = load_upgrade_notes()
cargo, brew, npm, uv, mcpnpx = cargo_git_installed(), brew_installed(), npm_g_installed(), uv_installed(), mcp_npx_installed()
updates, errors, held, release_pending = [], [], [], []
RUN_DATE = os.environ.get("LOCAL_ANALYSIS_DATE") or __import__("datetime").date.today().isoformat()
NPM_MIN_RELEASE_AGE = npm_min_release_age()

def add_update(name, mgr, cur, latest, src, notes="", **details):
    if latest and norm(latest) != norm(cur):
        update = {"name": name, "manager": mgr, "current": cur, "latest": latest, "source": src, "notes": notes}
        registered = upgrade_notes.get(name)
        if isinstance(registered, dict) and registered.get("report_note"):
            update["upgrade_note"] = registered["report_note"]
        update.update(details)
        hold_until = registered.get("hold_until") if isinstance(registered, dict) else None
        if hold_until and RUN_DATE <= str(hold_until):
            update["hold_until"] = str(hold_until)
            update["hold_reason"] = registered.get("hold_reason", "")
            held.append(update)
            return
        updates.append(update)

for e in manifest:
    name, mgr, src = e.get("name"), e.get("manager"), e.get("source")
    try:
        if mgr == "cargo-git":
            info = cargo.get(name)
            if not info:
                errors.append({"name": name, "reason": "not in .crates2.json"}); continue
            cur = info["tag"] or info["commit"][:8]
            latest = gh_latest(info["repo"])
            add_update(name, mgr, cur, latest, src or info["repo"], gh_notes(info["repo"], latest) if latest else "")
        elif mgr == "github-release":
            v = run([name, "--version"]) or ""
            mm = re.search(r'(\d+\.\d+\.\d+)', v)
            if not mm:
                errors.append({"name": name, "reason": "cannot detect installed version"}); continue
            latest = gh_latest(src)
            add_update(name, mgr, mm.group(1), latest, src, gh_notes(src, latest) if latest else "")
        elif mgr == "brew":
            cur = brew.get(src or name)
            if not cur:
                errors.append({"name": name, "reason": "not brew-installed"}); continue
            add_update(name, mgr, cur, brew_latest(src or name), src or name)
        elif mgr == "npm-g":
            info = npm.get(src or name)
            if not info:
                errors.append({"name": name, "reason": "not npm-g-installed"}); continue
            if info.get("error"):
                errors.append({"name": name, "reason": info["error"]}); continue
            active = info.get("active")
            if not active:
                installed = ", ".join(f"{item['version']} @ {item['root']}" for item in info.get("others", []))
                errors.append({"name": name, "reason": f"installed but no executable on PATH: {installed}"}); continue
            installable, pending = npm_installable(src or name, NPM_MIN_RELEASE_AGE, RUN_DATE)
            if pending:
                release_pending.append({"name": name, "manager": mgr, "current": active["version"], "installable": installable, **pending, "min_release_age": NPM_MIN_RELEASE_AGE})
            if installable and _vkey(installable) <= _vkey(active["version"]):
                installable = None
            add_update(
                name,
                mgr,
                active["version"],
                installable,
                src or name,
                active_install=active["root"],
                other_installs=info.get("others", []),
            )
        elif mgr == "uv-tool":
            cur = uv.get(src or name)
            if not cur:
                errors.append({"name": name, "reason": "not uv-installed"}); continue
            add_update(name, mgr, cur, pypi_latest(src or name), src or name)
        elif mgr == "uv-git":
            if not uv.get(name):
                errors.append({"name": name, "reason": "not uv-installed"}); continue
            current_commit = uv_git_commit(name)
            latest_commit = gh_head(src)
            if not current_commit:
                errors.append({"name": name, "reason": "installed uv tool has no VCS commit"}); continue
            if not latest_commit:
                errors.append({"name": name, "reason": "cannot resolve upstream HEAD"}); continue
            add_update(name, mgr, current_commit[:8], latest_commit[:8], src)
        elif mgr == "mcp-npx":
            entries = mcpnpx.get(name)
            if not entries:
                errors.append({"name": name, "reason": "not an npx mcpServer in ~/.claude.json"}); continue
            pkg = src or entries[0]["package"]
            pins = sorted({e["pin"] or "latest" for e in entries})
            if pins != ["latest"] and "latest" in pins:
                errors.append({"name": name, "reason": f"config mismatch: pins {pins} across " + ", ".join(e["config"] for e in entries)}); continue
            if pins == ["latest"]:
                errors.append({"name": name, "reason": f"unpinned (@latest) — npx re-resolves on every session start; pin {pkg}@<version> to track"}); continue
            if len(pins) > 1:
                errors.append({"name": name, "reason": f"config mismatch: pins {pins} across " + ", ".join(e["config"] for e in entries)}); continue
            add_update(name, mgr, pins[0], npm_latest(pkg), pkg, configs=[e["config"] for e in entries])
        else:
            errors.append({"name": name, "reason": f"unknown manager {mgr}"})
    except Exception as ex:
        errors.append({"name": name, "reason": str(ex)[:80]})

tracked = set(e.get("name") for e in manifest)
discovered = []
pin_signal = pin_check()
if isinstance(pin_signal, dict) and "error" in pin_signal:
    errors.append({"name": "claude-code-pin", "reason": pin_signal["error"]})
elif pin_signal:
    candidates = pin_signal.get("candidates", [])
    if candidates:
        reasons = []
        if pin_signal.get("closed"):
            reasons.append("issue closed: " + ", ".join("#" + n for n in pin_signal["closed"]))
        if pin_signal.get("matched"):
            reasons.append("CHANGELOG 命中: " + ", ".join(pin_signal["matched"]))
        updates.append({
            "name": "claude-code", "manager": "claude-code-pin",
            "current": PIN_VERSION, "latest": candidates[0], "source": PIN_REPO,
            "notes": "pin 可以重新驗證（" + "；".join(reasons) + "）— 人工測試候選版本，確認 sticky prompt 恢復後再解除 pin；未驗證是否已修復",
        })
for names, mgr in [(cargo.keys(), "cargo-git"), (brew_leaves(), "brew"),
                   (npm.keys(), "npm-g"), (uv.keys(), "uv-tool"), (mcpnpx.keys(), "mcp-npx"),
                   ([n for n in mcp_list() if n not in mcpnpx], "mcp")]:
    for n in names:
        if n not in tracked and n not in ignore:
            discovered.append({"name": n, "manager": mgr})

result = {"updates": updates, "discovered": discovered, "errors": errors, "held": held, "release_pending": release_pending}

if JSON_OUT:
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)

def emit(text):
    op = os.environ.get("CCTOOL_OUT")
    if op:
        try:
            open(op, "w").write(text + "\n")
        except Exception:
            pass
    print(text)

if not updates and not discovered and not release_pending:
    emit("__SILENT__")
    sys.exit(0)

out = []
if updates:
    out.append("### 有更新")
    for u in updates:
        note = f" — release notes: {u['notes']}" if u.get("notes") else ""
        active = f"；PATH 作用中：{u['active_install']}" if u.get("active_install") else ""
        others = ""
        if u.get("other_installs"):
            values = "、".join(f"{item['version']} @ {item['root']}" for item in u["other_installs"])
            others = f"；其他安裝：{values}"
        upgrade_note = f" {u['upgrade_note']}" if u.get("upgrade_note") else ""
        out.append(f"- {u['name']} {u['current']}→{u['latest']}（{u['manager']}{active}{others}）{upgrade_note}{note}")
if release_pending:
    out.append("### ⏳ 未滿 release age（npm min-release-age 擋、現在裝不到；到期自動回到有更新）")
    for u in release_pending:
        out.append(f"- {u['name']} {u['current']}→{u['version']}（{u['manager']}；{u['published']} 發布、min-release-age={u['min_release_age']} 天、{u['unlock_date']} 解禁）")
if held:
    out.append("### 暫緩（使用者拍板 hold_until 未到，不列入有更新；到期自動回到有更新）")
    for u in held:
        reason = f"；{u['hold_reason']}" if u.get("hold_reason") else ""
        out.append(f"- {u['name']} {u['current']}→{u['latest']}（{u['manager']}）hold 至 {u['hold_until']}{reason}")
if discovered:
    out.append("### 待分類（新發現，不在白/黑名單；歸白名單追蹤 or 黑名單忽略）")
    for d in discovered:
        out.append(f"- {d['name']}（{d['manager']}）")
if errors:
    out.append("### 查詢失敗（graceful skip）")
    for e in errors:
        out.append(f"- {e['name']}: {e['reason']}")
emit("\n".join(out))
PY
