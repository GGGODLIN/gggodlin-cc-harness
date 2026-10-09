#!/usr/bin/env python3
# 本檔在契約測試底下：bash ~/.claude/hooks/ticket-yagni.test.sh && python3 ~/.claude/hooks/ticket-yagni-ticket-file.test.py && python3 ~/.claude/hooks/ticket-yagni-prompt-source.test.py && python3 ~/.claude/hooks/ticket-yagni-pi.test.py
"""ticket-yagni — ticket 級 YAGNI at delivery。CC 的 register/deliver/gate，加上外部 pi 的 pi-register/pi-deliver。

  register  PostToolUse Agent：只登記已確認的實作 worker，背景 agentId→票、worktree、base sha。
            前景完成才當場審查；背景缺身分與未知狀態不冒充前景交件，記未審查。
            帶 --sync（settings 登記成同步 hook）時，前景審查結果一律用 additionalContext 交給 main——要砍的清單、
            「審過、沒有要砍的」、「未審到＋原因」三種之一，main 拿到 worker 成果的同一刻就看得到。不帶 --sync 維持舊的
            async 輸出（stderr＋exit 2 讓 asyncRewake 叫醒）。背景 worker 兩種模式都只登記，交件仍走 deliver。
  deliver   UserPromptSubmit（async + asyncRewake）：攔 worker 的 <task-notification>，查登記，跑 runner；
            verdict 有 kill／demote 或審查失敗 → exit 2 把摘要交給模型（asyncRewake 會喚醒 idle session）。
  gate      PreToolUse Edit|Write|MultiEdit：票檔 Status 改成 completed 時，沒 verdict 不給關。
  pi-register / pi-deliver
            外部 pi 的明示入口（stdin JSON 只有 session_id、cwd、job_dir）。不讀 tool_response，
            不把 pi 副作用編成 Agent 交件。registry 身分固定是 pi-+jobUUID。
            無 decision、已確認的非實作席是 no-op。對得上既有 TDD 票的實作席若 job 不完整，exit 1，
            不能當成沒登記也可以開工。同一 job 再 register 冪等。deliver 只審已登記、state 為 completed、
            數值最小那輪 settled 是 JSON true 且正文非空的首交件；verdict／error／skip 已在就不重跑。
            base 用登記時對上 HEAD 的 dispatch sha，交件不重取 HEAD。結果指標不另猜欄名：
            result.json 的 status／text_file／full_body_path／settled 必須等於最後一輪。
            OFF 仍是唯一靜默出口，不在這裡因 pi 偏好否決已在跑的 job。

Threat model（動工前寫）：
- 防漂移，不防主動規避。main 誠實但健忘：漏帶票號、忘了審、直接關票，這些攔得到。
- 票檔來源路徑**只從 worker prompt 的明示絕對路徑抓**（2026-09-11：票檔在父層治理 repo 時 fallback roots 找不到）；
  條件＝唯一、票號吻合、存在、非 symlink，任一不滿足就回到原 fallback（不猜）。路徑只是資料、不是授權——
  登記還要求實作類 agent、description 票號與 decision.tickets 吻合；reviewer 即使提到票號或票檔也不登記。
  runner 端仍用既有 --ticket-file 契約驗票號與 issues/ 層級，雙邊同一套判定。
- 字串比對型：票號**只從 description 抓**（2026-09-10 收窄：原本 prompt 也算，導致 review-implement 的 reviewer
  因 prompt 引用 `NN-xxx.md` 被誤登記成票 worker，對空 diff 報 RuntimeError；deny 訊息本來就寫「description 帶
  Ticket NN 才會自動登記」，此改動是讓實作對齊已宣告的契約）、Status 用 regex 認、交件用 <task-id> 認。
  不承諾完整語意，只認常見入口；認不出票號就不登記，而關票 gate 對「沒登記」是 deny（fail closed），不是放行。
- 前景 worker 若先 commit，PostToolUse 才取交件後 HEAD 當 base，可能把差異判空並 skip；這條舊路徑不保證有效審查，本次不新增事前 hook。
- 明文不保證：main 用 Bash 直接改票檔（只有 Edit|Write|MultiEdit 有 matcher，v1 不擋 Bash）；
  main 拿到 verdict 後有沒有真的砍（gate 只擋一次，第二次放行）；worker 自寫測試護著膨脹（由 implement SKILL 規則處理）。
- 降級明寫：runner／relay 失敗、pending 超過 TTL → gate 放行並記 audit。這是使用者拍板的 fail-open，
  把 gate 從純安全型降為「登記面安全、審查面提示」；要改回全 fail-closed 改 FAIL_OPEN_ON_ERROR。
- 空 diff 走獨立 skip 路徑（2026-09-13 首輪 review：47 次 runner 失敗有 14 次是空 diff 被當失敗，
  佔 29%，並連帶讓 gate 記成 fail-open）。語義上「沒有任何改動」是判得出來的確定狀態、不是審查失敗——
  YAGNI 審的是「改動有沒有超出票範圍」，零改動時無物可審，放行是正解而非降級。因此 skip 放行
  **不受 FAIL_OPEN_ON_ERROR 影響**：即使改回 fail-closed，空 diff 仍放行、仍記 gate-allow-empty-diff。
  明文不保證：本路徑不判斷「worker 什麼都沒做卻要關票」是否合理，那不是 YAGNI gate 的職責。
  兩檔並存時（重跑）以 error 優先，保留 fail-closed 政策下的較保守判定。
- 判官 hook 只讀 relay key 進 Authorization header，不落 log、不進 verdict。

Surface 四分表：
  Locked：本檔、runner、settings 三段（改動走 git commit；bootstrap＝第一次 settings 登記；update＝改檔跑 .test.sh；
          recovery＝touch ~/.claude/hooks/ticket-yagni.off 三支全靜默）
  Editable：票檔（main 改 Status）、worker worktree
  Append-only：logs/ticket-yagni/<session>/workers.jsonl、audit.jsonl（O_APPEND|O_NOFOLLOW，非 regular file 拒寫）
  Human-controlled：sentinel、settings 登記、FAIL_OPEN_ON_ERROR 政策

測試：bash ~/.claude/hooks/ticket-yagni.test.sh
"""
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get('TICKET_YAGNI_ROOT', '~/.claude/logs/ticket-yagni')).expanduser()
MATT_ROOT = Path(os.environ.get('MATT_TDD_ROOT', '~/.claude/logs/matt-tdd')).expanduser()
OFF = Path(os.environ.get('TICKET_YAGNI_OFF', '~/.claude/hooks/ticket-yagni.off')).expanduser()
RUNNER = os.environ.get('TICKET_YAGNI_RUNNER', str(Path(__file__).resolve().with_name('ticket-yagni-runner.py')))
PENDING_TTL = int(os.environ.get('TICKET_YAGNI_PENDING_TTL', '700'))
RUNNER_TIMEOUT = int(os.environ.get('TICKET_YAGNI_RUNNER_TIMEOUT', '620'))
FAIL_OPEN_ON_ERROR = os.environ.get('TICKET_YAGNI_FAIL_OPEN', '1') == '1'
TAG = '[ticket-yagni]'
PI_JOBS_ROOT = Path(os.environ.get('PI_SUBTASK_JOBS_ROOT', '~/.claude/logs/pi-subtask/jobs')).expanduser()
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
SHA_RE = re.compile(r'^[0-9a-f]{40}$')
PI_SESSION_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$')
PI_START_STATUS = {'ready', 'running', 'completed'}
PI_FILE_MAX = 2_000_000

TICKET_RES = [
  re.compile(r'(?:\bticket|\bissue|票)\s*#?\s*0?(\d{1,2})\b', re.I),
  re.compile(r'/issues/(\d{2})-[^/\s]*\.md'),
  re.compile(r'(?<![\w/])(\d{2})-[a-z0-9][a-z0-9-]*\.md\b'),
]
STATUS_RE = re.compile(r'\*\*Status:?\*\*:?[^\n]*?\b(complete|completed|done|implemented|shipped)\b|\*\*Status:?\*\*:?[^\n]*?(完成|已完成)', re.I)
TICKET_FILE_RE = re.compile(r'/issues/(\d{2})-[^/]*\.md$')
AGENT_ID_RE = re.compile(r'agentId:\s*([0-9A-Za-z_-]{6,})')
WORKER_AGENT_TYPES = {'routed-impl', 'routed-secure', 'codex:codex-rescue'}
TASK_ID_RE = re.compile(r'<task-id>\s*([^<\s]+)\s*</task-id>')
TASK_STATUS_RE = re.compile(r'<status>\s*(\w+)\s*</status>')


def now():
  return time.time()


def safe_append(path, line):
  # 寫不進去一律回 False、不丟例外：呼叫端有安全型閘門，例外沒人接會讓 hook 沒輸出、Claude Code 照常執行工具。
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
  except OSError:
    return False
  try:
    if not stat.S_ISREG(os.fstat(fd).st_mode):
      return False
    os.write(fd, (line.rstrip('\n') + '\n').encode())
    return True
  except OSError:
    return False
  finally:
    os.close(fd)


def audit(event, **fields):
  fields.update({'ts': now(), 'event': event})
  safe_append(ROOT / 'audit.jsonl', json.dumps(fields, ensure_ascii=False))


def read_input():
  raw = sys.stdin.read()
  return json.loads(raw) if raw.strip() else {}


def newest_decision(session):
  if not session:
    return None
  runs = sorted(MATT_ROOT.glob(f'{session}/*/decision.json'), key=lambda p: p.stat().st_mtime, reverse=True)
  if not runs:
    return None
  try:
    data = json.loads(runs[0].read_text())
  except (OSError, ValueError):
    return None
  ids = set()
  for t in data.get('tickets') or []:
    m = re.match(r'\D*0?(\d{1,2})', str(t.get('id', '')))
    if m:
      ids.add(m.group(1).zfill(2))
  return {'path': runs[0], 'run_id': data.get('run_id') or runs[0].parent.name, 'tickets': ids}


def find_ticket(text, valid):
  for pat in TICKET_RES:
    for m in pat.finditer(text or ''):
      tid = m.group(1).zfill(2)
      if tid in valid:
        return tid
  return None


def registry_path(session):
  return ROOT / session / 'workers.jsonl'


def read_registry(session):
  p = registry_path(session)
  if not p.exists() or not p.is_file() or p.is_symlink():
    return []
  out = []
  for line in p.read_text().splitlines():
    try:
      out.append(json.loads(line))
    except ValueError:
      continue
  return out


def state_dir(session, run, ticket, agent):
  return ROOT / session / f'{run}__{ticket}' / agent


def git_toplevel(path):
  try:
    r = subprocess.run(['git', '-C', path, 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=20)
  except (OSError, subprocess.TimeoutExpired):
    return None
  return r.stdout.strip() if r.returncode == 0 else None


def git_head(path):
  try:
    r = subprocess.run(['git', '-C', path, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=20)
  except (OSError, subprocess.TimeoutExpired):
    return None
  return r.stdout.strip() if r.returncode == 0 else None


def pick_worktree(prompt, cwd):
  cwd_top = git_toplevel(cwd) if cwd else None
  for cand in re.findall(r'(/[^\s\'"`<>|,;:，。、；：（）「」『』]+)', prompt or ''):
    cand = cand.rstrip('.)')
    if not os.path.isdir(cand):
      continue
    top = git_toplevel(cand)
    if top and top != cwd_top:
      return top
  return cwd_top or cwd


PROMPT_TASKS_RE = re.compile(r'(/[^\s\'"`<>|,;:，。、；：（）「」『』]*?/openspec/changes/[^/\s\'"`<>|,;:，。、；：（）「」『』]+/tasks\.md)')
UNREVIEWED_LABELS = {
  'ticket-file-unresolved': '票檔無法解析（派工 prompt 沒有這張票的絕對路徑，或路徑不存在）',
  'openspec-unsupported': 'openspec 格式尚未支援（登記的是 tasks.md，交件審查還讀不懂段落）',
  'timeout': '逾時（驗收員超過自己的時限）',
  'relay-error': 'relay 出錯',
  'unparseable-response': '判決回應無法解析',
  'runner-error': '驗收員內部錯誤',
  'hook-timeout': '逾時（runner 超過 hook 的上限被終止）',
  'runner-spawn': 'runner 無法啟動',
  'no-result': 'runner 沒有產出結果（可能崩潰）',
}
PROMPT_TICKET_FILE_RE = re.compile(r'(/[^\s\'"`<>|,;:，。、；：（）「」『』]*?/issues/(\d{2})-[^/\s\'"`<>|,;:，。、；：（）「」『』]+\.md)')


def find_ticket_file_from_prompt(prompt, ticket):
  if not prompt:
    return None
  cands = []
  for m in PROMPT_TICKET_FILE_RE.finditer(prompt):
    path = m.group(1).rstrip('.)')
    if m.group(2) != ticket:
      continue
    if not os.path.isfile(path) or os.path.islink(path):
      continue
    if path not in cands:
      cands.append(path)
  if len(cands) != 1:
    return None
  return cands[0]


def find_openspec_tasks_from_prompt(prompt, ticket):
  # 登記成 ticket_file，runner 會回「openspec 格式尚未支援」而不是「票檔無法解析」；段落存在與否由閘門 B 檢查。
  cands = []
  for m in PROMPT_TASKS_RE.finditer(prompt or ''):
    path = m.group(1)
    if os.path.isfile(path) and not os.path.islink(path) and path not in cands:
      cands.append(path)
  return cands[0] if len(cands) == 1 else None


def agent_response_state(resp):
  if isinstance(resp, dict):
    status = str(resp.get('status', '')).lower()
    if status in ('error', 'failed', 'cancelled') or resp.get('is_error') or resp.get('error'):
      return 'failed', None
    identity = resp.get('agentId') or resp.get('agent_id')
    if not isinstance(identity, str) or re.fullmatch(r'[0-9A-Za-z_-]{6,}', identity) is None:
      identity = None
    if resp.get('isAsync') is True or status in ('running', 'launched', 'async', 'async_launched'):
      return ('background', identity) if identity else ('unknown', None)
    # CC 2.1.283 的前台完成回傳同時帶 agentId（govern-implement-fix-dispatch Ticket 07 探針）；背景啟動已在上一條
    # 以 isAsync／launched 類 status 分走，所以 completed 就是前台交件，不再要求沒有 agentId。
    if status in ('completed', 'success') and resp.get('isAsync') is not True:
      return 'foreground', None
    return 'unknown', None
  if isinstance(resp, str):
    text = resp.strip()
    if text.startswith('Error:'):
      return 'failed', None
    if text.startswith('Async agent launched successfully'):
      match = AGENT_ID_RE.search(text)
      return ('background', match.group(1)) if match else ('unknown', None)
    match = AGENT_ID_RE.fullmatch(text)
    if match:
      return 'background', match.group(1)
    if text.startswith('Final result:'):
      return 'foreground', None
  return 'unknown', None


def run_review(session, run, ticket, agent, worktree, base, cwd, ticket_file=None, sync=False):
  sdir = state_dir(session, run, ticket, agent)
  sdir.mkdir(parents=True, exist_ok=True)
  pending = sdir / 'pending.json'
  pending.write_text(json.dumps({'started': now(), 'agent': agent, 'ticket': ticket, 'worktree': worktree, 'base_sha': base}))
  cmd = [sys.executable, RUNNER, '--session', session, '--run', run, '--ticket', ticket, '--agent', agent,
         '--worktree', worktree, '--base', base, '--out', str(sdir)]
  if ticket_file:
    cmd += ['--ticket-file', ticket_file]
  if cwd:
    cmd += ['--cwd', cwd]
  try:
    subprocess.run(cmd, capture_output=True, text=True, timeout=RUNNER_TIMEOUT)
  except subprocess.TimeoutExpired:
    (sdir / 'error.json').write_text(json.dumps({'error': f'runner timeout after {RUNNER_TIMEOUT}s', 'unreviewed': 'hook-timeout', 'ticket': ticket, 'agent': agent}))
  except OSError as e:
    (sdir / 'error.json').write_text(json.dumps({'error': f'runner spawn failed: {e}', 'unreviewed': 'runner-spawn', 'ticket': ticket, 'agent': agent}))
  if pending.exists():
    pending.unlink()
  if sync:
    return report_sync(sdir, ticket, worktree, base, session, run)
  return report(sdir, ticket, worktree, base, session, run)


def emit_context(text):
  print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': text}}, ensure_ascii=False))
  return 0


def flagged_lines(data, ticket, verdict):
  counts = data.get('counts', {})
  flagged = [v for v in data.get('verdicts', []) if v.get('verdict') in ('kill', 'demote')]
  lines = [f'{TAG} 票 {ticket} 的 YAGNI verdict：kill {counts.get("kill", 0)}／demote {counts.get("demote", 0)}／keep {counts.get("keep", 0)}。',
           '這是 worker 交件的 ticket 級審查，不是新的 review 迴圈；一票只審一次。處理方式：把下列清單用 SendMessage 送回同一個 worker 砍或瘦身，',
           '只跑派工前（dispatch_base_sha）已存在的測試與 acceptance 對應測試，worker 為被砍項目新寫的測試隨項目一起刪；處理完再改票 Status。']
  for v in flagged[:40]:
    lines.append(f'- {v["verdict"]} `{v.get("item")}`（{v.get("basis")}）：{v.get("reason", "")}')
  if len(flagged) > 40:
    lines.append(f'- …另 {len(flagged) - 40} 項見 verdict 檔')
  if data.get('missing_information'):
    lines.append('missing_information：' + '；'.join(str(x) for x in data['missing_information'][:5]))
  lines.append(f'verdict 檔：{verdict}')
  return flagged, lines


def unreviewed_text(ticket, code, detail, session, run, worktree, base):
  label = UNREVIEWED_LABELS.get(code, UNREVIEWED_LABELS['runner-error'])
  return (f'{TAG} 票 {ticket} 未審到：{label}（{str(detail)[:200]}）。這份交件沒有經過 YAGNI 審查；工作照常繼續，'
          f'關票時{"放行並記 audit" if FAIL_OPEN_ON_ERROR else "會被擋"}。'
          f'手動補審：python3 {RUNNER} --manual --session {session} --run {run} --ticket {ticket} --worktree {worktree} --base {base}')


def report_sync(sdir, ticket, worktree, base, session, run):
  verdict = sdir / 'verdict.json'
  error = sdir / 'error.json'
  try:
    if verdict.exists():
      data = json.loads(verdict.read_text())
      audit('review-done', session=session, ticket=ticket, run=run, counts=data.get('counts', {}), elapsed=data.get('elapsed'),
            verdict_file=str(verdict), sync=True)
      flagged, lines = flagged_lines(data, ticket, verdict)
      if flagged:
        return emit_context('\n'.join(lines))
      return emit_context(f'{TAG} 票 {ticket} 的 YAGNI 審查：審過，沒有要砍或降級的項目（keep {data.get("counts", {}).get("keep", 0)}）。verdict 檔：{verdict}')
    if (sdir / 'skip.json').exists():
      audit('review-skip-empty-diff', session=session, ticket=ticket, run=run, sync=True)
      return emit_context(f'{TAG} 票 {ticket} 的 YAGNI 審查：交件相對派工 base 沒有改動，沒有可審的項目（空 diff）。')
    code, detail = 'no-result', 'runner 沒有寫出 verdict、skip 或 error'
    if error.exists():
      rec = json.loads(error.read_text())
      code, detail = rec.get('unreviewed') or 'runner-error', rec.get('error', 'unknown')
  except (OSError, ValueError) as e:
    code, detail = 'runner-error', f'結果檔讀不出來：{type(e).__name__}: {e}'
  audit('review-error', session=session, ticket=ticket, run=run, error=str(detail)[:300], unreviewed=code, sync=True)
  return emit_context(unreviewed_text(ticket, code, detail, session, run, worktree, base))


def report(sdir, ticket, worktree, base, session, run):
  verdict = sdir / 'verdict.json'
  error = sdir / 'error.json'
  if verdict.exists():
    data = json.loads(verdict.read_text())
    audit('review-done', session=session, ticket=ticket, run=run, counts=data.get('counts', {}), elapsed=data.get('elapsed'), verdict_file=str(verdict))
    flagged, lines = flagged_lines(data, ticket, verdict)
    if not flagged:
      return 0
    print('\n'.join(lines), file=sys.stderr)
    return 2
  if (sdir / 'skip.json').exists():
    audit('review-skip-empty-diff', session=session, ticket=ticket, run=run)
    return 0
  reason = 'unknown'
  if error.exists():
    try:
      reason = json.loads(error.read_text()).get('error', 'unknown')
    except ValueError:
      reason = 'error.json unreadable'
  audit('review-error', session=session, ticket=ticket, run=run, error=reason)
  print(f'{TAG} 票 {ticket} 的 YAGNI 審查失敗（{reason[:200]}）。關票將{"放行並記 audit" if FAIL_OPEN_ON_ERROR else "被擋"}。'
        f'手動重跑：python3 {RUNNER} --manual --session {session} --run {run} --ticket {ticket} --worktree {worktree} --base {base}', file=sys.stderr)
  return 2


class PiJobError(Exception):
  pass


def _owned_dir(path, missing_code):
  try:
    st = Path(path).lstat()
  except OSError:
    raise PiJobError(missing_code)
  if stat.S_ISLNK(st.st_mode):
    raise PiJobError('symlink')
  if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
    raise PiJobError(missing_code)
  return st


def bind_pi_job(session_id, job_dir):
  # 未知路徑直接拒絕。只跟著 jobs root 以上的系統前綴（例如 /var）走，job 目錄本身不跟隨 symlink。
  if not isinstance(session_id, str) or UUID_RE.fullmatch(session_id) is None:
    raise PiJobError('bad-session')
  if not isinstance(job_dir, str) or not os.path.isabs(job_dir):
    raise PiJobError('bad-job-dir')
  if PI_JOBS_ROOT.is_symlink():
    raise PiJobError('symlink')
  _owned_dir(PI_JOBS_ROOT, 'bad-root')
  root = Path(os.path.realpath(PI_JOBS_ROOT))
  raw = Path(os.path.abspath(job_dir))
  job_uuid = raw.name
  if raw.parent.name != session_id or UUID_RE.fullmatch(job_uuid) is None:
    raise PiJobError('unbound')
  if raw.is_symlink() or raw.parent.is_symlink():
    raise PiJobError('symlink')
  expected = root / session_id / job_uuid
  _owned_dir(expected.parent, 'missing-job')
  _owned_dir(expected, 'missing-job')
  if os.path.realpath(raw) != os.path.realpath(expected):
    raise PiJobError('unbound')
  return expected, job_uuid


def _is_strict_ancestor(ancestor, child):
  try:
    return Path(child).relative_to(ancestor).parts != ()
  except ValueError:
    return False


def locate_in_job(job_dir, ref):
  if not isinstance(ref, str) or not ref.strip() or '\x00' in ref:
    raise PiJobError('bad-path')
  job_real = Path(os.path.realpath(job_dir))
  raw = os.path.abspath(ref if os.path.isabs(ref) else os.path.join(str(job_real), ref))
  cur = Path(Path(raw).anchor)
  entered = False
  for part in Path(raw).parts[1:]:
    nxt = cur / part
    if entered:
      try:
        st = nxt.lstat()
      except OSError:
        raise PiJobError('missing')
      if stat.S_ISLNK(st.st_mode):
        raise PiJobError('symlink')
      cur = nxt
      continue
    if nxt.is_symlink():
      target = Path(os.path.realpath(nxt))
      if not _is_strict_ancestor(target, job_real):
        raise PiJobError('symlink')
      cur = target
    else:
      cur = nxt
    if cur == job_real:
      entered = True
    elif str(cur).startswith(str(job_real) + os.sep):
      raise PiJobError('outside')
  if not entered or not str(cur).startswith(str(job_real) + os.sep):
    raise PiJobError('outside')
  try:
    st = cur.lstat()
  except OSError:
    raise PiJobError('missing')
  if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid():
    raise PiJobError('untrusted-file')
  return cur


def read_owned_bytes(job_dir, ref):
  path = locate_in_job(job_dir, ref)
  flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
  try:
    fd = os.open(path, flags)
  except OSError:
    raise PiJobError('open')
  try:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid() or st.st_size > PI_FILE_MAX:
      raise PiJobError('untrusted-file')
    data = os.read(fd, PI_FILE_MAX + 1)
  finally:
    os.close(fd)
  if len(data) > PI_FILE_MAX:
    raise PiJobError('too-large')
  return data


def load_json_in_job(job_dir, ref):
  try:
    data = json.loads(read_owned_bytes(job_dir, ref).decode())
  except (UnicodeError, ValueError):
    raise PiJobError('bad-json')
  if not isinstance(data, dict):
    raise PiJobError('bad-json')
  return data


def pi_session_ok(value):
  return isinstance(value, str) and len(value) <= 200 and PI_SESSION_RE.fullmatch(value) is not None


def pid_alive_owned(pid):
  if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
    return False
  try:
    os.kill(pid, 0)
  except OSError:
    return False
  try:
    proc = subprocess.run(['ps', '-o', 'uid=', '-p', str(pid)], capture_output=True, text=True, timeout=5)
  except (OSError, subprocess.TimeoutExpired):
    return False
  if proc.returncode != 0:
    return False
  try:
    return int(proc.stdout.strip()) == os.getuid()
  except ValueError:
    return False


def pi_context(inp):
  if not isinstance(inp, dict):
    raise PiJobError('input')
  cwd = inp.get('cwd')
  if not isinstance(cwd, str) or not cwd.strip():
    raise PiJobError('cwd')
  job_dir, job_uuid = bind_pi_job(inp.get('session_id'), inp.get('job_dir'))
  manifest = load_json_in_job(job_dir, 'manifest.json')
  state = load_json_in_job(job_dir, 'state.json')
  if manifest.get('session_id') != inp.get('session_id'):
    raise PiJobError('session-mismatch')
  return {'session_id': inp.get('session_id'), 'job_dir': job_dir, 'job_uuid': job_uuid,
          'job_id': 'pi-' + job_uuid, 'manifest': manifest, 'state': state}


def pi_ticket_decision(ctx):
  decision = newest_decision(ctx['session_id'])
  if not decision:
    return None
  agent_type = ctx['manifest'].get('agent_type')
  if not isinstance(agent_type, str) or not agent_type:
    raise PiJobError('agent-type')
  if agent_type not in WORKER_AGENT_TYPES:
    audit('pi-register-non-worker', session=ctx['session_id'], agent_type=agent_type)
    return None
  description = ctx['manifest'].get('description')
  description = description if isinstance(description, str) else ''
  ticket = find_ticket(description, decision['tickets'])
  if not ticket:
    audit('pi-register-unmatched', session=ctx['session_id'], description=description[:200])
    return None
  return decision, ticket, description, agent_type


def pi_registry_entry(ctx):
  job_id = ctx['job_id']
  hits = [e for e in read_registry(ctx['session_id']) if e.get('agent_id') == job_id]
  return hits[-1] if hits else None


def same_pi_entry(got, expected):
  keys = ('agent_id', 'ticket', 'run_id', 'worktree', 'base_sha', 'foreground', 'description',
          'backend', 'job_dir', 'cwd', 'ticket_file')
  return all(got.get(key) == expected.get(key) for key in keys)


def checked_pi_registration(ctx, decision, ticket, description, existing=None):
  manifest = ctx['manifest']
  state = ctx['state']
  if manifest.get('job_id') != ctx['job_id']:
    raise PiJobError('job-id')
  if state.get('status') not in PI_START_STATUS:
    raise PiJobError('not-startable')
  if not pi_session_ok(manifest.get('pi_session_id')) or manifest.get('pi_session_id') != state.get('pi_session_id'):
    raise PiJobError('pi-session')
  # 第二次 register 時 worker 可能已跑完，pid 不必還活著；首登不行，否則會放未登記的 worker 開工。
  if manifest.get('pi_pid') != state.get('pi_pid'):
    raise PiJobError('pid')
  if existing is None and not pid_alive_owned(manifest.get('pi_pid')):
    raise PiJobError('pid')
  for key in ('logical_model', 'resolved_model', 'effort'):
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
      raise PiJobError('model-fields')
  cwd = manifest.get('cwd')
  if not isinstance(cwd, str) or not os.path.isabs(cwd) or os.path.islink(cwd) or not os.path.isdir(cwd):
    raise PiJobError('manifest-cwd')
  prompt_ref = manifest.get('prompt_file')
  if not isinstance(prompt_ref, str):
    raise PiJobError('prompt-file')
  try:
    prompt = read_owned_bytes(ctx['job_dir'], prompt_ref).decode()
  except UnicodeError:
    raise PiJobError('prompt-file')
  base = manifest.get('base_sha')
  worktree = pick_worktree(prompt, cwd)
  head = git_head(worktree) if worktree else None
  pinned = existing.get('base_sha') if existing else None
  if not isinstance(base, str) or SHA_RE.fullmatch(base) is None or (pinned is None and head != base) or (pinned is not None and base != pinned):
    raise PiJobError('base')
  extracted = find_ticket_file_from_prompt(prompt, ticket) or find_openspec_tasks_from_prompt(prompt, ticket)
  if 'ticket_file' in manifest and manifest.get('ticket_file') != extracted:
    raise PiJobError('ticket-file')
  entry = {'ts': now(), 'agent_id': ctx['job_id'], 'ticket': ticket, 'run_id': decision['run_id'],
           'worktree': worktree, 'base_sha': base, 'foreground': False, 'description': description[:200],
           'backend': 'pi-subtask', 'job_dir': str(ctx['job_dir']), 'cwd': cwd}
  if extracted:
    entry['ticket_file'] = extracted
  return entry


def list_round_results(job_dir):
  rounds = Path(job_dir) / 'rounds'
  try:
    st = rounds.lstat()
  except OSError:
    raise PiJobError('no-rounds')
  if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
    raise PiJobError('bad-rounds')
  items = []
  for child in rounds.iterdir():
    name = child.name
    if not name.isdigit() or str(int(name)) != name:
      raise PiJobError('bad-round-name')
    try:
      cst = child.lstat()
    except OSError:
      raise PiJobError('bad-round')
    if stat.S_ISLNK(cst.st_mode) or not stat.S_ISDIR(cst.st_mode) or cst.st_uid != os.getuid():
      raise PiJobError('bad-round')
    items.append((int(name), child / 'result.json'))
    if len(items) > 100:
      raise PiJobError('too-many-rounds')
  if not items:
    raise PiJobError('no-rounds')
  items.sort()
  return items


def delivery_fields(data):
  if not isinstance(data, dict):
    raise PiJobError('bad-result')
  return (data.get('status'), data.get('text_file'), data.get('full_body_path'), data.get('settled'))


def require_first_delivery(job_dir):
  rounds = list_round_results(job_dir)
  first = load_json_in_job(job_dir, str(rounds[0][1]))
  last = load_json_in_job(job_dir, str(rounds[-1][1]))
  pointer = load_json_in_job(job_dir, 'result.json')
  if delivery_fields(pointer) != delivery_fields(last):
    raise PiJobError('result-pointer')
  status, text_file, full_body, settled = delivery_fields(first)
  if status != 'completed' or settled is not True:
    raise PiJobError('not-settled')
  for ref in (text_file, full_body):
    if not read_owned_bytes(job_dir, ref).strip():
      raise PiJobError('empty-body')


def pi_reject(command, exc):
  audit(f'{command}-reject', reason=str(exc))
  print(f'{TAG} {command} reject: {exc}', file=sys.stderr)
  return 1


def cmd_pi_register(inp):
  try:
    ctx = pi_context(inp)
    decided = pi_ticket_decision(ctx)
    if not decided:
      return 0
    decision, ticket, description, _agent_type = decided
    existing = pi_registry_entry(ctx)
    if existing and existing.get('run_id') and existing.get('ticket'):
      # 同一 job 的再登記維持原 run／票。較新的 decision 不能把已登記身分改掉，也不該因此變成 conflict。
      decision = dict(decision)
      decision['run_id'] = existing['run_id']
      ticket = existing['ticket']
    entry = checked_pi_registration(ctx, decision, ticket, description, existing)
    if existing:
      if same_pi_entry(existing, entry):
        return 0
      raise PiJobError('registry-conflict')
    if not safe_append(registry_path(ctx['session_id']), json.dumps(entry, ensure_ascii=False)):
      raise PiJobError('registry-write')
    audit('pi-register', session=ctx['session_id'], ticket=ticket, agent=ctx['job_id'], job_dir=str(ctx['job_dir']))
    return 0
  except PiJobError as exc:
    return pi_reject('pi-register', exc)


def _pi_result_present(path):
  if path.is_symlink():
    raise PiJobError('symlink')
  return path.is_file()


def cmd_pi_deliver(inp):
  try:
    ctx = pi_context(inp)
    decision = newest_decision(ctx['session_id'])
    entry = pi_registry_entry(ctx)
    # 跟 cmd_deliver 一樣：只要這個 session 還有 decision，就用登記當下的 run／票，不因較新的 decision 改寫身分。
    registered = bool(decision and entry and entry.get('backend') == 'pi-subtask'
                      and entry.get('run_id') and entry.get('ticket')
                      and os.path.realpath(entry.get('job_dir') or '') == os.path.realpath(ctx['job_dir'])
                      and isinstance(entry.get('base_sha'), str) and entry.get('worktree'))
    # 已登記的交件以 registry 為準。改掉 manifest description 不能把首交件變成 no-op 逃過審查。
    if not registered:
      if not pi_ticket_decision(ctx):
        return 0
      raise PiJobError('unregistered')
    ticket = entry['ticket']
    sdir = state_dir(ctx['session_id'], entry['run_id'], ticket, ctx['job_id'])
    if _pi_result_present(sdir / 'verdict.json') or _pi_result_present(sdir / 'error.json') or _pi_result_present(sdir / 'skip.json'):
      audit('pi-deliver-already-reviewed', session=ctx['session_id'], ticket=ticket, agent=ctx['job_id'])
      return 0
    pending = sdir / 'pending.json'
    if pending.is_symlink():
      raise PiJobError('symlink')
    if pending.is_file():
      try:
        started = json.loads(pending.read_text()).get('started', 0)
      except (OSError, ValueError):
        started = 0
      if now() - started < PENDING_TTL:
        audit('pi-deliver-pending-dup', session=ctx['session_id'], ticket=ticket, agent=ctx['job_id'])
        return 0
    if ctx['manifest'].get('job_id') != ctx['job_id']:
      raise PiJobError('job-id')
    if ctx['state'].get('status') != 'completed':
      raise PiJobError('not-completed')
    require_first_delivery(ctx['job_dir'])
    return run_review(ctx['session_id'], entry['run_id'], ticket, ctx['job_id'], entry['worktree'], entry['base_sha'],
                      entry.get('cwd'), entry.get('ticket_file'), sync=True)
  except PiJobError as exc:
    return pi_reject('pi-deliver', exc)


def cmd_register(inp, sync=False):
  session = inp.get('session_id') or ''
  decision = newest_decision(session)
  if not decision:
    return 0
  ti = inp.get('tool_input') or {}
  if ti.get('subagent_type') not in WORKER_AGENT_TYPES:
    audit('register-non-worker', session=session, agent_type=ti.get('subagent_type'))
    return 0
  description = str(ti.get('description') or '')
  prompt = str(ti.get('prompt') or '')
  ticket = find_ticket(description, decision['tickets'])
  if not ticket:
    audit('register-unmatched', session=session, description=description[:200])
    return 0
  state, identity = agent_response_state(inp.get('tool_response'))
  if state not in ('foreground', 'background'):
    audit('register-unreviewed', session=session, ticket=ticket, reason=state)
    return 0
  foreground = state == 'foreground'
  agent = f'fg-{(inp.get("tool_use_id") or str(int(now())))[:24]}' if foreground else identity
  cwd = inp.get('cwd') or os.getcwd()
  worktree = pick_worktree(prompt, cwd)
  base = git_head(worktree) if worktree else None
  if not base:
    audit('register-no-git', session=session, ticket=ticket, worktree=worktree)
    if sync and foreground:
      return emit_context(unreviewed_text(ticket, 'runner-error', f'worktree 不是 git repo，取不到 base：{worktree}',
                                          session, decision['run_id'], worktree, '<dispatch_base_sha>'))
    return 0
  ticket_file = find_ticket_file_from_prompt(prompt, ticket) or find_openspec_tasks_from_prompt(prompt, ticket)
  entry = {'ts': now(), 'agent_id': agent, 'ticket': ticket, 'run_id': decision['run_id'], 'worktree': worktree,
           'base_sha': base, 'foreground': foreground, 'description': description[:200]}
  if ticket_file:
    entry['ticket_file'] = ticket_file
  if not safe_append(registry_path(session), json.dumps(entry, ensure_ascii=False)):
    audit('register-write-refused', session=session, ticket=ticket)
    if sync and foreground:
      return emit_context(unreviewed_text(ticket, 'runner-error', '登記簿拒寫（不是一般檔案）', session, decision['run_id'], worktree, base))
    return 0
  audit('register', session=session, ticket=ticket, agent=agent, foreground=foreground, prompt_ticket_file=ticket_file)
  if foreground:
    return run_review(session, decision['run_id'], ticket, agent, worktree, base, cwd, ticket_file, sync=sync)
  return 0


def cmd_deliver(inp):
  prompt = str(inp.get('prompt') or '')
  if '<task-notification>' not in prompt:
    return 0
  m = TASK_ID_RE.search(prompt)
  if not m:
    return 0
  task_id = m.group(1)
  session = inp.get('session_id') or ''
  decision = newest_decision(session)
  if not decision:
    return 0
  entries = [e for e in read_registry(session) if e.get('agent_id') == task_id]
  if not entries:
    audit('deliver-unregistered', session=session, task_id=task_id)
    return 0
  entry = entries[-1]
  st = TASK_STATUS_RE.search(prompt)
  if st and st.group(1).lower() not in ('completed', 'complete', 'done'):
    audit('deliver-not-completed', session=session, ticket=entry['ticket'], status=st.group(1))
    return 0
  sdir = state_dir(session, entry['run_id'], entry['ticket'], task_id)
  if (sdir / 'verdict.json').exists() or (sdir / 'error.json').exists():
    audit('deliver-already-reviewed', session=session, ticket=entry['ticket'], agent=task_id)
    return 0
  pending = sdir / 'pending.json'
  if pending.exists():
    try:
      started = json.loads(pending.read_text()).get('started', 0)
    except ValueError:
      started = 0
    if now() - started < PENDING_TTL:
      audit('deliver-pending-dup', session=session, ticket=entry['ticket'], agent=task_id)
      return 0
  return run_review(session, entry['run_id'], entry['ticket'], task_id, entry['worktree'], entry['base_sha'],
                    inp.get('cwd'), entry.get('ticket_file'))


def deny(reason):
  print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                           'permissionDecisionReason': f'{TAG} {reason}'}}, ensure_ascii=False))
  return 0


def new_text(inp):
  tool = inp.get('tool_name') or ''
  ti = inp.get('tool_input') or {}
  if tool == 'Edit':
    return str(ti.get('new_string') or '')
  if tool == 'Write':
    return str(ti.get('content') or '')
  if tool == 'MultiEdit':
    return '\n'.join(str(e.get('new_string') or '') for e in ti.get('edits') or [])
  return ''


def cmd_gate(inp):
  ti = inp.get('tool_input') or {}
  fpath = str(ti.get('file_path') or '')
  fm = TICKET_FILE_RE.search(fpath)
  if not fm:
    return 0
  if not STATUS_RE.search(new_text(inp)):
    return 0
  session = inp.get('session_id') or ''
  decision = newest_decision(session)
  if not decision:
    return 0
  ticket = fm.group(1)
  if ticket not in decision['tickets']:
    return 0
  try:
    entries = [e for e in read_registry(session) if e.get('ticket') == ticket]
    remedy = (f'補救：python3 {RUNNER} --manual --session {session} --run {decision["run_id"]} --ticket {ticket} '
              f'--worktree <worker worktree> --base <dispatch_base_sha>，跑完再改 Status。停用開關：touch {OFF}')
    manual_dir = state_dir(session, decision['run_id'], ticket, 'manual')
    if (manual_dir / 'verdict.json').exists() or (manual_dir / 'error.json').exists() or (manual_dir / 'skip.json').exists():
      entries.append({'agent_id': 'manual', 'ts': manual_dir.stat().st_mtime, 'run_id': decision['run_id']})
    if not entries:
      audit('gate-deny-unregistered', session=session, ticket=ticket, file=fpath)
      return deny(f'票 {ticket} 沒有登記 worker，YAGNI 未審，不能標完成。派工 description 帶「Ticket {ticket}」才會自動登記。{remedy}')
    entry = sorted(entries, key=lambda e: e.get('ts', 0))[-1]
    sdir = state_dir(session, entry.get('run_id') or decision['run_id'], ticket, entry['agent_id'])
    verdict = sdir / 'verdict.json'
    error = sdir / 'error.json'
    pending = sdir / 'pending.json'
    delivered = sdir / 'delivered'
    if verdict.exists():
      data = json.loads(verdict.read_text())
      flagged = [v for v in data.get('verdicts', []) if v.get('verdict') in ('kill', 'demote')]
      if flagged and not delivered.exists():
        delivered.write_text(str(now()))
        audit('gate-deny-verdict', session=session, ticket=ticket, flagged=len(flagged))
        items = '；'.join(f'{v["verdict"]} {v.get("item")}：{v.get("reason", "")}' for v in flagged[:30])
        return deny(f'票 {ticket} 的 YAGNI verdict 有 {len(flagged)} 項要處理（kill／demote），先送回 worker 處理、跑派工前測試，再改 Status。'
                    f'清單：{items}。verdict 檔：{verdict}。這個 deny 只出現一次，下一次改 Status 放行。')
      audit('gate-allow', session=session, ticket=ticket, flagged=len(flagged), delivered=delivered.exists())
      return 0
    if error.exists():
      if FAIL_OPEN_ON_ERROR:
        audit('gate-allow-fail-open-error', session=session, ticket=ticket)
        return 0
      return deny(f'票 {ticket} 的 YAGNI 審查失敗且政策為 fail-closed。{remedy}')
    if (sdir / 'skip.json').exists():
      audit('gate-allow-empty-diff', session=session, ticket=ticket)
      return 0
    if pending.exists():
      try:
        started = json.loads(pending.read_text()).get('started', 0)
      except ValueError:
        started = 0
      age = now() - started
      if age < PENDING_TTL:
        audit('gate-deny-pending', session=session, ticket=ticket, age=round(age))
        return deny(f'票 {ticket} 的 YAGNI 審查還在跑（{round(age)} 秒），跑完會自動叫醒你。先做其他不相依的事，不要輪詢。')
      if FAIL_OPEN_ON_ERROR:
        audit('gate-allow-fail-open-stale-pending', session=session, ticket=ticket, age=round(age))
        return 0
      return deny(f'票 {ticket} 的 YAGNI 審查 pending 超過 {PENDING_TTL} 秒且政策為 fail-closed。{remedy}')
    audit('gate-deny-no-delivery', session=session, ticket=ticket, agent=entry['agent_id'])
    return deny(f'票 {ticket} 的 worker 已登記但沒有交件審查紀錄（worker 還在跑，或交件通知沒被攔到）。{remedy}')
  except Exception as e:
    audit('gate-internal-error', session=session, ticket=ticket, error=f'{type(e).__name__}: {e}')
    return deny(f'gate 內部錯誤（{type(e).__name__}: {str(e)[:120]}），安全型預設擋下。停用開關：touch {OFF}')


def main():
  commands = ('register', 'deliver', 'gate', 'pi-register', 'pi-deliver')
  if len(sys.argv) < 2 or sys.argv[1] not in commands:
    print('usage: ticket-yagni.py register [--sync]|deliver|gate|pi-register|pi-deliver', file=sys.stderr)
    return 1
  if OFF.exists():
    return 0
  try:
    inp = read_input()
  except ValueError:
    if sys.argv[1] in ('pi-register', 'pi-deliver'):
      return 1
    return 0
  if sys.argv[1] == 'register':
    return cmd_register(inp, sync='--sync' in sys.argv[2:])
  if sys.argv[1] == 'pi-register':
    return cmd_pi_register(inp)
  if sys.argv[1] == 'pi-deliver':
    return cmd_pi_deliver(inp)
  return {'deliver': cmd_deliver, 'gate': cmd_gate}[sys.argv[1]](inp)


if __name__ == '__main__':
  sys.exit(main())
