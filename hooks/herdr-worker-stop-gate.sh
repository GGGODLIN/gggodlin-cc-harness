#!/usr/bin/env bash
# 本檔在契約測試底下：python3 ~/.claude/hooks/herdr-worker-stop-gate.test.py
#
# Threat model（防漂移／提示型偏安全 Stop gate）：
# - 對誰有效：防誠實但健忘的 Herdr 主控（main session，具備 HC_TERMINAL_ID）在名下仍有未關閉的子席或子 worker 時直接結束回合睡著：
#   * 舊路子 worker（無 seat_dispatch=v2 label）：(a) 工作中卻無活著的 agent-watch.sh，或 (b) 已停下且無 agent-watch.sh，或已退回空 shell。
#   * 新路單席（帶 label seat_dispatch=v2）：未關席、未向真人提問，且處於工作中卻無可歸屬之單席 `hc wait <addr|name>`，或已停下／退回空 shell 尚未收件關閉。
# - 明文不保證（Non-promises）：
#   1. 不防主動規避：agent 若提前強制關閉 worker、偽造同名背景程序、或在句尾硬塞問號皆可繞過。
#   2. 字串比對型提問豁免不承諾完整語意理解，只認常見「待拍板／允許這次派工／第 N/M 題」區塊與句尾問號（?／？）；
#      可能放行句尾帶修辭問句的回覆，也會攔到未包進程式碼區塊（```）或引言（>）的討論文字（替代路徑：若真要向真人提問請明確在結尾放問號或 `### 待拍板`；若不需提問請對新路席掛單席 `hc wait <addr> --timeout 300 --json`、收件或 `hc kill`/`hc rm` 收掉，舊路 worker 補掛 `agent-watch.sh`）。
#   3. 絕不自動啟動 Herdr server（遵守 terminal-backend-routing.md）：`hc server status` 非 running、`hc ls` 失敗或輸出無法解析時一律靜默放行（exit 0），避免後端停機鎖死對話。
#   4. 僅涵蓋新版 Herdr Core（`HC_TERMINAL_ID` 具備明確 `parent` 歸屬欄位）；不含舊版無 `parent` 欄位的 `HERDR_PANE_ID`，也不管 CC 原生 Agent／Workflow 背景任務。
#   5. 新路背景等待歸屬只認單席 `hc wait <addr|name>`（不認 `--children any/all`），且必須從 `ps eww` 同時讀到相符的 `HC_TERMINAL_ID` 與 `CLAUDE_CODE_SESSION_ID`；任一欄位讀不到即 fail-closed 不放行，環境變數只在記憶體抽取此兩鍵、絕不印出或寫 log。
#
# Surface 四分表：
# - Locked: ~/.claude/hooks/herdr-worker-stop-gate.sh、~/.claude/hooks/herdr-worker-stop-gate.test.py
# - Editable: Herdr 子 worker 狀態（補掛 agent-watch.sh、讀取轉達、hc kill/rm 關閉）、loopguard 狀態檔
# - Append-only: ~/.claude/logs/herdr-worker-stop-gate.jsonl（超過 512KB 停寫）
# - Human-controlled: ~/.claude/settings.json hooks 註冊、停用開關 ~/.claude/hooks/state/herdr-worker-stop-gate.disabled
#
# Locked 自身三路徑：
# - bootstrap: 先建立本檔與測試檔跑通四件組＋病態目標測試，再寫入 ~/.claude/settings.json Stop 段
# - update: 本 gate 只掛 Stop 且僅檢查 HC_TERMINAL_ID 名下子 worker，不攔 Edit/Write/Bash 修改自身、helper 或測試檔
# - recovery: 建立 ~/.claude/hooks/state/herdr-worker-stop-gate.disabled（或設環境變數 HERDR_WORKER_STOP_GATE_DISABLED=1），stderr 留稽核訊息並立即放行
#
# 繞行場景表：
# 1. 查 watcher 時自命中 shell 字串 → 以 ps argv 結構比對 agent-watch.sh 位置參數（backend=herdr-core、parent=HC_TERMINAL_ID、worker pane/name），排除自身 PID
# 2. 只掛 worker A 的 watcher 卻漏掛 worker B → 逐一對每個子 worker 的 address/name 獨立核對專屬 watcher
# 3. 子 worker 撞確認框或崩潰退回 zsh/bash → 對 turn>0 的 shell 子終端機判 exited_to_shell 攔截
# 4. 同 workspace 的非 agent 背景服務（如 npm dev server，turn=0 且無 agent status） → 排除不攔，防誤殺
#
# Stop loop guard：
# - 指紋綁定排序後的 [(worker_address, issue_kind)] 狀態清單（不含時間戳、PID 或行號）；same>3 或 total>6 自動放行並記 ESCAPED，刻意降為提示型偏安全防死鎖；狀態清空時自動移除計數檔。

set -u

HOME_DIR="${HOME:-}"
STATE_DIR="${HERDR_STOP_GATE_STATE_DIR:-${HOME_DIR:+$HOME_DIR/.claude/hooks/state}}"
DISABLED="${HERDR_STOP_GATE_DISABLED_SENTINEL:-${STATE_DIR:+$STATE_DIR/herdr-worker-stop-gate.disabled}}"

if [ "${HERDR_WORKER_STOP_GATE_DISABLED:-0}" = "1" ] || { [ -n "$DISABLED" ] && { [ -e "$DISABLED" ] || [ -L "$DISABLED" ]; }; }; then
  printf '[herdr-worker-stop-gate] disabled (%s); allowing Stop.\n' "$DISABLED" >&2
  exit 0
fi

# 非 Herdr Core 終端機零成本早退（不啟動 python3 / jq）
[ -n "${HC_TERMINAL_ID:-}" ] || exit 0

HC_BIN="${HC_BIN:-hc}"
command -v "$HC_BIN" >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

LOG_PATH="${HERDR_STOP_GATE_AUDIT_LOG:-${HOME_DIR:+$HOME_DIR/.claude/logs/herdr-worker-stop-gate.jsonl}}"
LOOPGUARD_DIR="${HERDR_STOP_GATE_LOOPGUARD_DIR:-${STATE_DIR:+$STATE_DIR/herdr-worker-stop-loopguard}}"
SAME_LIMIT="${HERDR_STOP_GATE_LOOPGUARD_SAME:-3}"
TOTAL_LIMIT="${HERDR_STOP_GATE_LOOPGUARD_TOTAL:-6}"

exec 3<&0
python3 -I - "$HC_TERMINAL_ID" "$HC_BIN" "$LOG_PATH" "$LOOPGUARD_DIR" "$SAME_LIMIT" "$TOTAL_LIMIT" <<'PY'
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time

hc_parent, hc_bin, log_path_s, loopguard_dir_s, same_limit_s, total_limit_s = sys.argv[1:7]
LOG_LIMIT = 512 * 1024

FENCED_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
PASTED_RE = re.compile(r"<pasted_content\b[^>]*>.*?</pasted_content>", re.DOTALL)
BLOCKQUOTE_LINE_RE = re.compile(r"(?m)^\s*>.*$")
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
CONTROL_BIDI_RE = re.compile(r"[\x00-\x1f\x7f‎‏‪-‮⁦-⁩]")

PENDING_QUESTION_RE = re.compile(
  r"(?m)"
  r"(?:^#{1,4}\s*第\s*\d+\s*/\s*\d+\s*題[^\n]*)"
  r"|(?:^(?:#{1,4}\s*|\*\*)待(?:你)?(?:拍板|補確認)[^\n]*)"
  r"|(?:允許這次派工)"
  r"|(?:(?:你想選|請選擇)\s*[*`「『\"']?[A-Za-z1-9][*`」』\"']?\s*(?:（[^）\n]*）)?\s*(?:還是|或)\s*[*`「『\"']?[A-Za-z1-9])"
  r"|(?:請[^\n]{0,50}(?:按同意|完成[^\n]{0,15}授權)[^\n]{0,30}(?:後|再)[^\n]{0,20}(?:回我|跟我說|回覆))"
)
TRAILING_Q_RE = re.compile(r"[?？][\"'」』）)*_\s]*$")

AGENT_APPS = {"claude-code", "claude", "codex", "pi"}
SHELL_APPS = {"zsh", "bash", "sh", "fish", "-zsh", "-bash", "-sh", "-fish"}
WORKING_STATES = {"working", "starting", "running"}
STOPPED_WATCHABLE = {"idle", "done"}
STOPPED_ATTENTION = {"blocked", "error"}


def clean_label(value, fallback="worker"):
  cleaned = CONTROL_BIDI_RE.sub("", str(value or "")).strip()
  return cleaned[:64] if cleaned else fallback


def safe_session_key(session_id):
  cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(session_id or "unknown")).strip("._-")
  return cleaned[:80] if cleaned else "session"


def close_quietly(fd: int) -> None:
  if fd >= 0:
    try:
      os.close(fd)
    except OSError:
      pass


def is_safe_dir(path: Path) -> bool:
  try:
    if path.is_symlink():
      return False
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid()
  except OSError:
    return False


def is_regular_single(path: Path) -> bool:
  try:
    st = path.lstat()
    return stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid()
  except OSError:
    return False


def valid_open_stat(st, max_size=None) -> bool:
  if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid():
    return False
  return max_size is None or st.st_size <= max_size


def open_regular_read(path: Path) -> int:
  fd = -1
  try:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(str(path), flags)
    if not valid_open_stat(os.fstat(fd)):
      close_quietly(fd)
      return -1
    return fd
  except OSError:
    close_quietly(fd)
    return -1


def append_jsonl_safe(log_path: Path, row: dict) -> None:
  if not is_safe_dir(log_path.parent):
    return
  if (log_path.exists() or log_path.is_symlink()) and not is_regular_single(log_path):
    return
  fd = -1
  try:
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(str(log_path), flags, 0o600)
    if not valid_open_stat(os.fstat(fd), LOG_LIMIT):
      return
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
      fd = -1
      fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
      fh.flush()
  except OSError:
    pass
  finally:
    close_quietly(fd)


def append_audit(event: str, session_id: str, issues: list, same: int = 0, total: int = 0) -> None:
  row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "event": event,
    "parent": hc_parent,
    "session_id": session_id,
    "issues": issues,
    "same": same,
    "total": total,
  }
  append_jsonl_safe(Path(log_path_s), row)


def asking_human(text: str) -> bool:
  if not isinstance(text, str) or not text.strip():
    return False
  stripped = BLOCKQUOTE_LINE_RE.sub("", FENCED_CODE_RE.sub("", PASTED_RE.sub("", text)))
  prose = INLINE_CODE_RE.sub(lambda m: "" if len(m.group(0)) >= 6 else m.group(0), stripped)
  if PENDING_QUESTION_RE.search(prose):
    return True
  non_empty = [ln.strip() for ln in prose.splitlines() if ln.strip()]
  return bool(non_empty and TRAILING_Q_RE.search(non_empty[-1]))


def unlink_regular(path: Path) -> None:
  try:
    if not path.is_symlink() and is_regular_single(path):
      path.unlink()
  except OSError:
    pass


def clear_loopguard(session_id: str) -> None:
  lg_dir = Path(loopguard_dir_s)
  if not lg_dir.is_symlink() and lg_dir.is_dir():
    unlink_regular(lg_dir / f"{safe_session_key(session_id)}.json")


def parse_caps() -> tuple[int, int]:
  try:
    s_cap, t_cap = int(same_limit_s), int(total_limit_s)
    return (s_cap, t_cap) if s_cap > 0 and t_cap > 0 else (3, 6)
  except ValueError:
    return 3, 6


def read_guard_dict(path: Path) -> dict:
  rfd = open_regular_read(path)
  if rfd < 0:
    return {}
  try:
    with os.fdopen(rfd, "r", encoding="utf-8") as fh:
      rfd = -1
      loaded = json.load(fh)
      return loaded if isinstance(loaded, dict) else {}
  except (OSError, ValueError, TypeError):
    return {}
  finally:
    close_quietly(rfd)


def write_guard_atomic(lg_dir: Path, dest: Path, data: dict) -> bool:
  wfd, tmp_path = -1, ""
  try:
    wfd, tmp_path = tempfile.mkstemp(prefix=".herdr-stop-lg.", dir=str(lg_dir))
    os.fchmod(wfd, 0o600)
    with os.fdopen(wfd, "w", encoding="utf-8") as fh:
      wfd = -1
      json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
      fh.flush()
      os.fsync(fh.fileno())
    os.replace(tmp_path, str(dest))
    tmp_path = ""
    return True
  except OSError:
    return False
  finally:
    close_quietly(wfd)
    if tmp_path:
      try:
        os.unlink(tmp_path)
      except OSError:
        pass


def loop_guard(session_id: str, state_fingerprint: list) -> tuple[str, int, int]:
  same_cap, total_cap = parse_caps()
  lg_dir = Path(loopguard_dir_s)
  if not is_safe_dir(lg_dir):
    return "allow", 0, 0
  p = lg_dir / f"{safe_session_key(session_id)}.json"
  if (p.exists() or p.is_symlink()) and not is_regular_single(p):
    return "allow", 0, 0
  fp_key = json.dumps(state_fingerprint, ensure_ascii=False, separators=(",", ":"))
  prev = read_guard_dict(p)
  def _safe_count(val) -> int:
    if isinstance(val, bool):
      return 0
    try:
      return max(0, int(val))
    except (ValueError, TypeError):
      return 0
  same = _safe_count(prev.get("same", 0)) + 1 if prev.get("state") == fp_key else 1
  total = _safe_count(prev.get("total", 0)) + 1
  if same > same_cap or total > total_cap:
    unlink_regular(p)
    return "release", same, total
  ok = write_guard_atomic(lg_dir, p, {"state": fp_key, "same": same, "total": total})
  return ("block" if ok else "allow"), same, total


def load_ps_text() -> str:
  ps_override = os.environ.get("HERDR_STOP_GATE_PS_FILE")
  if ps_override:
    try:
      return Path(ps_override).read_text(encoding="utf-8", errors="replace")
    except OSError:
      return ""
  try:
    proc = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, timeout=2)
    return proc.stdout if proc.returncode == 0 else ""
  except (OSError, subprocess.SubprocessError):
    return ""


def split_cmd_tokens(cmd: str) -> list[str]:
  try:
    return shlex.split(cmd)
  except ValueError:
    return cmd.split()


def find_watch_script_tail(tokens: list[str]) -> list[str]:
  for i, tok in enumerate(tokens):
    if tok == "agent-watch.sh" or tok.endswith("/agent-watch.sh"):
      return tokens[i + 1:]
  return []


def parse_watcher_line(line: str, excluded_pids: set[int]) -> dict | None:
  if "agent-watch.sh" not in line:
    return None
  parts = line.strip().split(None, 1)
  if len(parts) < 2 or not parts[0].isdigit() or int(parts[0]) in excluded_pids:
    return None
  rest = find_watch_script_tail(split_cmd_tokens(parts[1]))
  if len(rest) < 4:
    return None
  return {
    "backend": rest[0],
    "worker_name": rest[1],
    "parent_id": rest[2],
    "worker_pane": rest[7] if len(rest) >= 8 else "",
  }


def read_watchers() -> list[dict]:
  excluded = {os.getpid(), os.getppid()}
  parsed = [parse_watcher_line(ln, excluded) for ln in load_ps_text().splitlines()]
  return [w for w in parsed if w is not None]


def has_watcher(watchers: list[dict], addr: str, raw_name: str) -> bool:
  for w in watchers:
    if w["backend"] != "herdr-core" or w["parent_id"] != hc_parent:
      continue
    target_match = (w["worker_pane"] == addr) if w["worker_pane"] else (w["worker_name"] in (addr, raw_name))
    if target_match:
      return True
  return False


def run_hc_json(args: list[str], timeout_sec: int) -> dict | None:
  try:
    proc = subprocess.run([hc_bin, *args], capture_output=True, text=True, timeout=timeout_sec)
    if proc.returncode != 0:
      return None
    data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return data if isinstance(data, dict) else None
  except (OSError, subprocess.SubprocessError, ValueError):
    return None


def server_is_running(st_json: dict | None) -> bool:
  if st_json is None or st_json.get("running") is False:
    return False
  return st_json.get("state") not in {"stopped", "down", "offline"}


def is_own_live_child(t) -> bool:
  return isinstance(t, dict) and t.get("parent") == hc_parent and t.get("state") == "live"


def fetch_live_children() -> list[dict] | None:
  if not server_is_running(run_hc_json(["server", "status", "--json"], 2)):
    return None
  ls_json = run_hc_json(["ls", "--json"], 3)
  terminals = ls_json.get("terminals") if ls_json else None
  if not isinstance(terminals, list):
    return None
  return [t for t in terminals if is_own_live_child(t)]


def extract_status_state(raw_st) -> str:
  if isinstance(raw_st, dict):
    raw_st = raw_st.get("state")
  return raw_st.strip() if isinstance(raw_st, str) else ""


def extract_turn_int(raw_turn) -> int:
  return raw_turn if isinstance(raw_turn, int) and not isinstance(raw_turn, bool) else 0


def classify_agent_state(safe_addr: str, safe_name: str, st: str, watched: bool) -> tuple[list[str], str] | None:
  if st in WORKING_STATES and not watched:
    return [safe_addr, "working_unwatched"], f"{safe_addr}（{safe_name}：status={clean_label(st, 'working')} 但無活著的 agent-watch.sh，做完將無人喚醒 main）"
  if st in STOPPED_ATTENTION:
    lbl = clean_label(st, "attention")
    return [safe_addr, f"stopped:{lbl}"], f"{safe_addr}（{safe_name}：status={lbl}，請讀取處理或 hc kill/rm 關閉）"
  if st in STOPPED_WATCHABLE and not watched:
    lbl = clean_label(st, "stopped")
    return [safe_addr, f"stopped:{lbl}"], f"{safe_addr}（{safe_name}：status={lbl} 且未掛 watcher，請讀取交付／重掛 agent-watch.sh 等背景任務／或 hc kill 關閉）"
  return None


def load_ps_eww_map(pids: list[int]) -> dict[int, str]:
  eww_override = os.environ.get("HERDR_STOP_GATE_PS_EWW_FILE")
  if eww_override:
    try:
      text = Path(eww_override).read_text(encoding="utf-8", errors="replace")
    except OSError:
      return {}
  else:
    if not pids:
      return {}
    try:
      pid_arg = ",".join(str(p) for p in sorted(set(pids)))
      proc = subprocess.run(["ps", "eww", "-o", "pid=,command=", "-p", pid_arg], capture_output=True, text=True, timeout=2)
      text = proc.stdout if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
      return {}
  out: dict[int, str] = {}
  for line in text.splitlines():
    parts = line.strip().split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
      out[int(parts[0])] = parts[1]
  return out


def parse_hc_wait_target(tokens: list[str], *, stop_at_env: bool = False) -> str | None:
  if len(tokens) < 3:
    return None
  exe = tokens[0]
  if not (exe == "hc" or exe.endswith("/hc")) or tokens[1] != "wait":
    return None
  rest = tokens[2:]
  positional: list[str] = []
  i = 0
  while i < len(rest):
    tok = rest[i]
    if stop_at_env and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
      break
    if tok == "--children" or tok.startswith("--children="):
      return None
    if tok in ("--timeout", "--output"):
      i += 2
      continue
    if tok.startswith(("--timeout=", "--output=")) or tok in ("--json", "-h", "--help"):
      i += 1
      continue
    if tok.startswith("-"):
      i += 1
      continue
    positional.append(tok)
    i += 1
  return positional[0] if len(positional) == 1 else None


def read_attributable_hc_waits(session_id: str) -> set[str]:
  excluded = {os.getpid(), os.getppid()}
  candidates: list[tuple[int, str]] = []
  for line in load_ps_text().splitlines():
    if "wait" not in line or "hc" not in line:
      continue
    parts = line.strip().split(None, 1)
    if len(parts) < 2 or not parts[0].isdigit():
      continue
    pid = int(parts[0])
    if pid in excluded:
      continue
    target = parse_hc_wait_target(split_cmd_tokens(parts[1]))
    if target:
      candidates.append((pid, target))
  if not candidates:
    return set()
  eww_map = load_ps_eww_map([pid for pid, _ in candidates])
  attributed: set[str] = set()
  for pid, target in candidates:
    eww_line = eww_map.get(pid, "")
    if not eww_line:
      continue
    # 在同一份 ps eww 快照重核 argv[0]=hc、wait 與目標一致，避免 PID 重用或混入命令引數字串。
    eww_tokens = split_cmd_tokens(eww_line)
    if parse_hc_wait_target(eww_tokens, stop_at_env=True) != target:
      continue
    env_idx = next((idx for idx, tok in enumerate(eww_tokens) if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok)), len(eww_tokens))
    env_tail = " ".join(eww_tokens[env_idx:])
    m_tid = re.search(r"(?:^|\s)HC_TERMINAL_ID=([^\s]+)", env_tail)
    m_sid = re.search(r"(?:^|\s)CLAUDE_CODE_SESSION_ID=([^\s]+)", env_tail)
    if m_tid and m_sid and m_tid.group(1) == hc_parent and m_sid.group(1) == session_id:
      attributed.add(target)
  return attributed


def fetch_v2_seat_addrs(children: list[dict]) -> set[str]:
  v2: set[str] = set()
  for t in children:
    lbls = t.get("labels")
    raw_addr = t.get("address")
    addr = raw_addr.strip() if isinstance(raw_addr, str) else ""
    if addr and isinstance(lbls, dict) and lbls.get("seat_dispatch") == "v2":
      v2.add(addr)
  ls_v2 = run_hc_json(["ls", "--label", "seat_dispatch=v2", "--json"], 2)
  terminals = ls_v2.get("terminals") if isinstance(ls_v2, dict) else None
  if isinstance(terminals, list):
    for t in terminals:
      if is_own_live_child(t):
        raw_addr = t.get("address")
        addr = raw_addr.strip() if isinstance(raw_addr, str) else ""
        if addr:
          v2.add(addr)
  return v2


def classify_v2_child(t: dict, waited_targets: set[str]) -> tuple[list[str], str] | None:
  raw_addr = t.get("address")
  addr_raw = raw_addr.strip() if isinstance(raw_addr, str) else ""
  if not addr_raw:
    return None
  raw_name = t.get("name")
  name_raw = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else addr_raw
  agent = str(t.get("agent") or "").strip()
  turn = extract_turn_int(t.get("turn"))
  st = extract_status_state(t.get("status"))
  safe_addr = clean_label(addr_raw, "t?")
  safe_name = clean_label(name_raw, safe_addr)
  if (agent in SHELL_APPS) and (turn > 0):
    return [safe_addr, "v2_exited_to_shell"], f"{safe_addr}（{safe_name}：已退回 {clean_label(agent, 'shell')}，turn={turn}，請讀畫面後 hc kill/rm 關閉）"
  waited = (addr_raw in waited_targets) or (name_raw in waited_targets)
  if st in WORKING_STATES or st == "":
    if waited:
      return None
    kind = "v2_working_unwaited" if st in WORKING_STATES else "v2_unreported_unwaited"
    lbl = clean_label(st, "unreported") if st else "unreported"
    return [safe_addr, kind], f"{safe_addr}（{safe_name}：status={lbl} 但無屬於本 session 的單席 hc wait）"
  if st in STOPPED_ATTENTION:
    lbl = clean_label(st, "attention")
    return [safe_addr, f"v2_stopped:{lbl}"], f"{safe_addr}（{safe_name}：status={lbl}，請用 hc read 檢查並處理或 hc kill/rm 關閉）"
  if st in STOPPED_WATCHABLE:
    lbl = clean_label(st, "stopped")
    return [safe_addr, f"v2_stopped:{lbl}"], f"{safe_addr}（{safe_name}：status={lbl}，請用 worker-turns.py --turn 收件、續問或 hc kill/rm 關閉）"
  return None


def classify_child(t: dict, watchers: list[dict]) -> tuple[list[str], str] | None:
  addr_raw = str(t.get("address") or "").strip()
  if not addr_raw:
    return None
  name_raw = str(t.get("name") or addr_raw).strip()
  agent = str(t.get("agent") or "").strip()
  turn = extract_turn_int(t.get("turn"))
  st = extract_status_state(t.get("status"))
  safe_addr = clean_label(addr_raw, "t?")
  safe_name = clean_label(name_raw, safe_addr)
  if (agent in SHELL_APPS) and (turn > 0):
    return [safe_addr, "exited_to_shell"], f"{safe_addr}（{safe_name}：已退回 {clean_label(agent, 'shell')}，turn={turn}，請讀畫面確認後 hc kill/rm 關閉或重啟）"
  if (agent not in AGENT_APPS) and (st not in (WORKING_STATES | STOPPED_WATCHABLE | STOPPED_ATTENTION)):
    return None
  return classify_agent_state(safe_addr, safe_name, st, has_watcher(watchers, addr_raw, name_raw))


def read_stop_payload() -> dict | None:
  try:
    with os.fdopen(3, "r", encoding="utf-8", errors="replace") as payload_fh:
      raw = payload_fh.read()
    payload = json.loads(raw) if raw.strip() else {}
  except (OSError, ValueError):
    return None
  if not isinstance(payload, dict) or payload.get("hook_event_name") != "Stop" or payload.get("agent_id"):
    return None
  return payload if str(payload.get("session_id") or "") else None


def emit_decision(session_id: str, pairs: list[tuple[list[str], str]]) -> None:
  pairs.sort(key=lambda x: x[0])
  issues = [p[0] for p in pairs]
  details = [p[1] for p in pairs]
  verdict, same, total = loop_guard(session_id, issues)
  if verdict in ("release", "allow"):
    if verdict == "release":
      append_audit("ESCAPED", session_id, issues, same=same, total=total)
    return
  append_audit("BLOCKED", session_id, issues, same=same, total=total)
  has_v2 = any(iss[1].startswith("v2_") for iss in issues)
  has_old = any(not iss[1].startswith("v2_") for iss in issues)
  if has_v2 and not has_old:
    guidance = (
      "[herdr-worker-stop-gate] 本場 main 名下仍有未處理的新路 Herdr 子席，直接停下會漏收或漏關。"
      "請先完成對應處置再結束回合：(1) 仍在跑的子席掛單席背景等待 `hc wait <addr> --timeout 300 --json`；"
      "(2) 已停下的子席用 `worker-turns.py --turn` 收件、續問或用 `hc kill <addr>` 與 `hc rm <addr>` 關閉；"
      "(3) 若本輪是要向真人提問，請在回覆結尾明確寫出問題（`？` 或 `### 待拍板`）。"
    )
  elif has_old and not has_v2:
    guidance = (
      "[herdr-worker-stop-gate] 本場 main 名下仍有未收尾或漏掛哨兵的 Herdr 子 worker，直接停下會讓整個 team 無聲乾等。"
      "請先完成對應處置再結束回合：(1) 仍在跑的 worker 補掛 `nohup bash ~/.claude/skills/agent-dispatch/scripts/agent-watch.sh herdr-core ...`；"
      "(2) 已停下的 worker 先讀螢幕／JSONL 處理、續派或用 `hc kill <addr>` 關閉；"
      "(3) 若本輪其實是要停下來等真人回答問題，請在回覆結尾明確寫出問題（`？` 或 `### 待拍板`）。"
    )
  else:
    guidance = (
      "[herdr-worker-stop-gate] 本場 main 名下仍有未處理的 Herdr 子席／子 worker。"
      "請先完成對應處置：(1) 新路子席掛單席 `hc wait <addr> --timeout 300 --json`、收件或 `hc kill`/`hc rm` 關閉；"
      "(2) 舊路 worker 補掛 `agent-watch.sh`、讀取或關閉；"
      "(3) 若要等真人回答問題，請在回覆結尾明確寫出問題（`？` 或 `### 待拍板`）。"
    )
  reason = f"{guidance} 命中清單：{'；'.join(details)} [loop guard: same={same} total={total}]"
  print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def main() -> None:
  payload = read_stop_payload()
  if payload is None:
    return
  session_id = str(payload["session_id"])
  children = fetch_live_children()
  if children is None:
    return
  if not children:
    clear_loopguard(session_id)
    return
  if asking_human(payload.get("last_assistant_message", "")):
    clear_loopguard(session_id)
    append_audit("ALLOW_QUESTION", session_id, [])
    return
  v2_addrs = fetch_v2_seat_addrs(children)
  watchers = read_watchers() if any(str(t.get("address") or "").strip() not in v2_addrs for t in children) else []
  waited_targets = read_attributable_hc_waits(session_id) if v2_addrs else set()
  pairs = []
  for t in children:
    addr = str(t.get("address") or "").strip()
    item = classify_v2_child(t, waited_targets) if addr in v2_addrs else classify_child(t, watchers)
    if item is not None:
      pairs.append(item)
  if not pairs:
    clear_loopguard(session_id)
    return
  emit_decision(session_id, pairs)


if __name__ == "__main__":
  main()
PY
exit 0
