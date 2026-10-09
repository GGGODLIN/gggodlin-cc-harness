#!/usr/bin/python3
# 本檔在契約測試底下：bash ~/.claude/hooks/memory-ripple.test.sh
import fcntl
import json
import os
import re
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

KINDS = {
  "state-reversal",
  "dependency-invalidation",
  "schema-change",
  "migration",
  "incremental",
  "unclear",
}
# 最後一層 fallback：Jev（Experiential /v1/systemone，2026-09-29 使用者拍板所有 session 都可送 Jev）。
# 只在主判官與 Gemini fallback 都沒得到 judged 時才呼叫；直連 Experiential、不經 relay。
# 題目＝jev-hook-backtest 的 B 臂：hook 現行 prompt 的判準段原文（「輸出單一 JSON」之前）＋一個 Noul 問句＋一個 Choice 問句。
# 不承諾 Jev 判得跟主判官一樣準（Noul 機率、門檻 0.5）；只承諾「前兩層都掛時不讓事件停在 unavailable」。
# key 只在記憶體，不進 audit／stdout／例外訊息；error_class 只放固定字串。
JEV_URL = "https://api.experientiallabs.ai/v1/systemone"
JEV_MODEL = "jev-latest"
JEV_STATE_CHARS = 20000
JEV_THRESHOLD = 0.5
JEV_FIRE_QUESTION = "問題：這次 memory 寫入是否可能讓其他 memory 的現況敘述、前提、schema、工具替代關係或遷移狀態一起過時？"
JEV_KIND_QUESTION = "問題：這次 memory 寫入屬於哪一種狀態變更？沒有任何狀態影響選 incremental；看不出是否會影響其他 memory 選 unclear。"
# hook 本身沒有給 kind 定義；這些說明是依 kind 名稱與 prompt 用語寫的（同 jev-hook-backtest 的 MR_KIND_CRITERIA，去掉 none／other 以對齊 KINDS）
JEV_KIND_CRITERIA = {
  "state-reversal": "既有的現況敘述被推翻、退役、取消或結案（狀態反轉）",
  "dependency-invalidation": "其他 memory 賴以成立的前提或依賴不再成立",
  "schema-change": "資料、設定或檔案的結構與欄位形狀改變",
  "migration": "工具、系統或流程遷移到新的替代方案",
  "incremental": "只是一般補充、歷史快照或文字潤飾，不影響其他 memory 的現況",
  "unclear": "看不出是否會影響其他 memory",
}
MODEL_SUFFIXES = ("-extra-low", "-medium", "-low", "-high")
GEMINI_FLASH_MODEL_RE = re.compile(r"^gemini-[0-9]+(?:\.[0-9]+)*-flash(?:-(?:extra-low|medium|low|high))?$")
FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.I | re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]")
STOPWORDS = re.compile(r"^(user|feedback|reference|project|trial|eval|setup|config|deployed|pending|progress|review|daily|weekly|index|memory|hook|skill|claude|model|profile|ended|closed|completed|subscription|20[0-9]{2}|[0-9]+)$", re.I)
CUES = re.compile(r"沒有.{0,20}(?:欄位|功能|支援|資料|紀錄)|缺少.{0,20}(?:欄位|功能|支援|資料|紀錄)|未收錄|未包含|不含.{0,20}(?:欄位|功能|資料)|\bschema\b|\bstale\b|遷移|\bmigration\b|未確認|已確認|\bhold\b|原.{1,60}(?:現|後隨|改用|轉用|轉為)", re.I | re.S)


def now():
  return datetime.now().astimezone().isoformat(timespec="seconds")


def secure_dir(path, require_private):
  path = Path(path).expanduser()
  if not path.is_absolute():
    raise RuntimeError("relative_path")
  flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
  parent_fd = os.open("/", flags)
  try:
    for part in path.parts[1:]:
      try:
        child_fd = os.open(part, flags, dir_fd=parent_fd)
      except FileNotFoundError:
        try:
          os.mkdir(part, 0o700, dir_fd=parent_fd)
        except FileExistsError:
          pass
        os.fsync(parent_fd)
        child_fd = os.open(part, flags, dir_fd=parent_fd)
      os.close(parent_fd)
      parent_fd = child_fd
    directory_stat = os.fstat(parent_fd)
    if directory_stat.st_uid != os.getuid() or require_private and directory_stat.st_mode & 0o077:
      raise RuntimeError("unsafe_directory")
    return parent_fd
  except OSError as error:
    os.close(parent_fd)
    raise RuntimeError("unsafe_directory") from error
  except Exception:
    os.close(parent_fd)
    raise


def encode_json(record):
  return json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_all(fd, payload):
  offset = 0
  while offset < len(payload):
    written = os.write(fd, payload[offset:])
    if written <= 0:
      raise OSError("short_write")
    offset += written


def safe_name(name):
  name = str(name)
  if not name or name in {".", ".."} or "/" in name:
    raise RuntimeError("invalid_name")
  return name


def test_mode():
  return os.environ.get("MEMORY_RIPPLE_TEST_MODE") == "1"


def environment_path(name, default):
  return os.environ.get(name, default) if test_mode() else default


def model_routing_path():
  override = os.environ.get("CLAUDE_MODEL_ROUTING_FILE") if test_mode() else None
  return Path(override).expanduser() if override else Path(__file__).resolve().parent.parent / "model-routing.env"


def gemini_flash_model():
  try:
    lines = model_routing_path().read_text(encoding="utf-8").splitlines()
  except OSError:
    return ""
  prefix = "GEMINI_FLASH_MODEL="
  values = [line[len(prefix):].strip() for line in lines if line.startswith(prefix)]
  if len(values) != 1:
    return ""
  value = values[0]
  if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
    value = value[1:-1]
  return value if GEMINI_FLASH_MODEL_RE.fullmatch(value) else ""


def validate_runtime_fd(fd, error_class, max_links=1):
  file_stat = os.fstat(fd)
  if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_uid != os.getuid() or file_stat.st_nlink < 1 or file_stat.st_nlink > max_links:
    raise RuntimeError(error_class)
  return file_stat


def append_json_at(dir_fd, name, record):
  name = safe_name(name)
  flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
  fd = os.open(name, flags, 0o600, dir_fd=dir_fd)
  try:
    validate_runtime_fd(fd, "invalid_audit_path")
    os.fchmod(fd, 0o600)
    payload = (encode_json(record) + "\n").encode("utf-8")
    locked = False
    for _ in range(20):
      try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        break
      except BlockingIOError:
        time.sleep(0.005)
    if not locked:
      raise RuntimeError("audit_lock_busy")
    write_all(fd, payload)
    os.fsync(fd)
    fsync_dir(dir_fd)
  finally:
    os.close(fd)


def append_json(path, record):
  path = Path(path).expanduser()
  parent_fd = secure_dir(path.parent, False)
  try:
    append_json_at(parent_fd, path.name, record)
  finally:
    os.close(parent_fd)


def fsync_dir(dir_fd):
  os.fsync(dir_fd)


def read_input():
  data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
  if not isinstance(data, dict):
    raise ValueError("input_not_object")
  return data


def output_text(text):
  sys.stdout.buffer.write((text + "\n").encode("utf-8"))
  sys.stdout.buffer.flush()


def bounded(text):
  if len(text) <= 5000:
    return text
  return text[:2500] + "\n…\n" + text[-2500:]


def clip(text):
  if len(text) <= 5000:
    return text
  match = CUES.search(text)
  if match:
    return text[max(0, match.start() - 2200):min(len(text), match.end() + 2700)]
  return bounded(text)


def diff_clips(before, after):
  prefix = 0
  limit = min(len(before), len(after))
  while prefix < limit and before[prefix] == after[prefix]:
    prefix += 1
  suffix = 0
  limit = min(len(before) - prefix, len(after) - prefix)
  while suffix < limit and before[len(before) - 1 - suffix] == after[len(after) - 1 - suffix]:
    suffix += 1
  start = max(0, prefix - 2200)
  return bounded(before[start:min(len(before), len(before) - suffix + 2700)]), bounded(after[start:min(len(after), len(after) - suffix + 2700)])


def user_message(data):
  old = str(data.get("old") or "")
  new = str(data.get("new") or "")
  if old and new and old != new and (len(old) > 5000 or len(new) > 5000):
    old, new = diff_clips(old, new)
  else:
    old, new = clip(old), clip(new)
  return "<memory-ripple-data>\n檔名：" + str(data.get("file") or "") + "\n\n修改前：\n" + old + "\n\n修改後：\n" + new + "\n</memory-ripple-data>"


def c068_message(data):
  user = str(data.get("user") or "")[:4000]
  final = str(data.get("final") or "")[:4000]
  if not final:
    final = "(the assistant produced no final text message)"
  payload = json.dumps({"user": user, "final": final}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
  return "<c068-data>\n<<<BEGIN_CONVERSATION_DATA_JSON\n" + payload + "\nEND_CONVERSATION_DATA_JSON>>>\n</c068-data>"


def prompt_path(mode):
  override = os.environ.get("MEMORY_RIPPLE_PROMPT") if test_mode() else None
  if override:
    return Path(override).expanduser()
  if mode == "c068":
    return Path(__file__).with_name("c068-answer-judge-prompt-v1.txt")
  return Path(__file__).with_name("memory-ripple-" + mode + "-prompt-v1.txt")


def positive_timeout(value):
  timeout = float(value)
  if not 0 < timeout < 300:
    raise ValueError("invalid_timeout")
  return timeout


def retry_count(value):
  retries = int(value)
  if retries < 0 or retries > 5:
    raise ValueError("invalid_retries")
  return retries


def model_config(mode):
  key = os.environ.get("MEMORY_RIPPLE_GEMINI_KEY", "") if test_mode() else ""
  key_file = Path(environment_path("MEMORY_RIPPLE_GEMINI_KEY_FILE", "~/.cli-proxy-api/keys.env")).expanduser()
  if not key and key_file.is_file():
    for line in key_file.read_text(encoding="utf-8").splitlines():
      if line.startswith("CLIPROXY_KEY_CC="):
        key = line.split("=", 1)[1].strip()
        break
  default_model = "groq-qwen-3.8-27b"
  fallback_model = environment_path("MEMORY_RIPPLE_FALLBACK_MODEL", gemini_flash_model())
  return {
    "fallback_model": fallback_model,
    "url": environment_path("MEMORY_RIPPLE_GEMINI_URL", "http://127.0.0.1:8317/v1/chat/completions"),
    "model": environment_path("MEMORY_RIPPLE_GEMINI_MODEL", default_model),
    "timeout": positive_timeout(environment_path("MEMORY_RIPPLE_GEMINI_TIMEOUT", "12")),
    "auth": key,
  }


def verdict_content(content):
  stripped = content.strip()
  fenced = FENCED_JSON_RE.fullmatch(stripped)
  return fenced.group(1).strip() if fenced else stripped


def wikilink_target_only(data):
  old = str(data.get("old") or "")
  new = str(data.get("new") or "")
  if old == new or not WIKILINK_RE.search(old) or not WIKILINK_RE.search(new):
    return False
  normalize = lambda text: WIKILINK_RE.sub(lambda match: "[[target" + (match.group(2) or "") + "]]", text)
  return normalize(old) == normalize(new)


def compatible_model(requested, returned):
  if requested == "gemini-3.5-flash-low" and returned == "gemini-default":
    return True
  if requested == "groq-qwen-3.8-27b" and returned == "qwen/qwen3.8-27b":
    return True
  for suffix in MODEL_SUFFIXES:
    if requested.endswith(suffix) and returned == requested[:-len(suffix)]:
      return True
  return False


def parse_response(raw, requested_model, mode="gemini"):
  response = json.loads(raw)
  if not isinstance(response, dict):
    raise ValueError("response_not_object")
  returned_model = response.get("model")
  if not isinstance(returned_model, str) or not returned_model:
    raise RuntimeError("model_missing")
  if returned_model != requested_model and not compatible_model(requested_model, returned_model):
    raise RuntimeError("model_mismatch")
  choices = response.get("choices")
  if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
    raise ValueError("response_shape")
  message = choices[0].get("message")
  if not isinstance(message, dict) or not isinstance(message.get("content"), str):
    raise ValueError("response_shape")
  verdict = json.loads(verdict_content(message["content"]), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non_finite")))
  if mode == "c068":
    if not isinstance(verdict, dict) or set(verdict) != {"verdict", "reason"}:
      raise ValueError("verdict_shape")
    if verdict["verdict"] not in {"YES", "NO"} or not isinstance(verdict["reason"], str):
      raise ValueError("verdict_value")
    return verdict, returned_model
  if not isinstance(verdict, dict) or set(verdict) != {"should_fire", "kind", "confidence"}:
    raise ValueError("verdict_shape")
  if not isinstance(verdict["should_fire"], bool) or not isinstance(verdict["kind"], str) or verdict["kind"] not in KINDS:
    raise ValueError("verdict_value")
  if isinstance(verdict["confidence"], bool) or not isinstance(verdict["confidence"], (int, float)):
    raise ValueError("verdict_value")
  confidence = float(verdict["confidence"])
  if confidence < 0 or confidence > 1:
    raise ValueError("verdict_value")
  return verdict, returned_model or requested_model


def judge(data, mode, model=None):
  started = time.monotonic()
  result = {
    "status": "unavailable",
    "mode": mode,
    "requested_model": "",
    "returned_model": "",
    "latency_ms": 0,
    "error_class": "",
  }
  try:
    prompt = prompt_path(mode)
    config = model_config(mode)
    if model is None:
      model = config["model"]
    result["requested_model"] = model
    prompt_bytes = prompt.read_bytes()
    payload = {
      "model": model,
      "messages": [
        {"role": "system", "content": prompt_bytes.decode("utf-8")},
        {"role": "user", "content": c068_message(data) if mode == "c068" else user_message(data)},
      ],
      "max_tokens": 180,
      "temperature": 0,
      "stream": False,
    }
    override = os.environ.get("MEMORY_RIPPLE_GEMINI_RESPONSE") if test_mode() else None
    if override is not None:
      if mode == "c068" and override == "__TIMEOUT__":
        raise RuntimeError("timeout")
      raw = override
    else:
      headers = {"Content-Type": "application/json"}
      if config["auth"]:
        headers["Authorization"] = "Bearer " + config["auth"]
      request = urllib.request.Request(config["url"], data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"), headers=headers, method="POST")
      opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
      try:
        with opener.open(request, timeout=config["timeout"]) as response:
          raw = response.read().decode("utf-8")
      except TimeoutError:
        raise RuntimeError("timeout")
      except urllib.error.HTTPError:
        raise RuntimeError("http_error")
      except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
          raise RuntimeError("timeout")
        raise RuntimeError("transport_error")
    verdict, returned_model = parse_response(raw, model, mode)
    result.update({
      "status": "judged",
      "returned_model": returned_model,
    })
    if mode == "c068":
      result.update({"verdict": verdict["verdict"], "reason": verdict["reason"]})
    else:
      result.update({
        "should_fire": verdict["should_fire"],
        "kind": verdict["kind"],
        "confidence": verdict["confidence"],
      })
  except FileNotFoundError:
    result["error_class"] = "missing_dependency"
  except json.JSONDecodeError:
    result["error_class"] = "malformed_json"
  except UnicodeDecodeError:
    result["error_class"] = "encoding_error"
  except PermissionError:
    result["error_class"] = "permission"
  except OSError:
    result["error_class"] = "io_error"
  except (RuntimeError, ValueError, TypeError) as error:
    result["error_class"] = str(error)
  result["latency_ms"] = round((time.monotonic() - started) * 1000)
  return result


def jev_endpoint():
  # None = 不嘗試 Jev：kill switch（recovery 開關，production 也認），或 test mode 沒指定測試端點（避免既有 fixture 打真的 Jev）
  if os.environ.get("MEMORY_RIPPLE_DISABLE_JEV") == "1":
    return None
  if test_mode():
    return os.environ.get("MEMORY_RIPPLE_JEV_URL") or None
  return JEV_URL


def jev_key(url):
  if test_mode():
    override = os.environ.get("MEMORY_RIPPLE_JEV_KEY")
    if override:
      return override
    # 測試端點沒給測試 key 時不讀 Keychain，避免真 key 被送到非 Experiential 的位址
    if url != JEV_URL:
      raise RuntimeError("url_overridden_without_key")
  try:
    completed = subprocess.run(["security", "find-generic-password", "-s", "experiential-api-key", "-w"], capture_output=True, text=True, timeout=5)
  except subprocess.TimeoutExpired:
    raise RuntimeError("keychain_timeout")
  key = completed.stdout.strip()
  if completed.returncode != 0 or not key:
    raise RuntimeError("keychain_key_missing")
  return key


def jev_verdict(raw):
  try:
    answers = json.loads(raw)["answers"]
    probability = answers["should_fire"]["noul"]
    kind = answers["kind"]["choice"]
  except (KeyError, TypeError):
    raise ValueError("response_shape")
  if isinstance(probability, bool) or not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
    raise ValueError("verdict_value")
  if not isinstance(kind, str) or kind not in KINDS:
    raise ValueError("verdict_value")
  should_fire = probability >= JEV_THRESHOLD
  return {"should_fire": should_fire, "kind": kind, "confidence": round(float(probability if should_fire else 1 - probability), 4)}


def judge_jev(data):
  url = jev_endpoint()
  if url is None:
    return None
  started = time.monotonic()
  result = {
    "status": "unavailable",
    "mode": "gemini",
    "requested_model": JEV_MODEL,
    "returned_model": "",
    "latency_ms": 0,
    "error_class": "",
  }
  try:
    timeout = model_config("gemini")["timeout"]
    prompt_bytes = prompt_path("gemini").read_bytes()
    prompt = prompt_bytes.decode("utf-8")
    marker = prompt.find("輸出單一 JSON")
    if marker < 0:
      raise RuntimeError("rubric_marker_missing")
    rubric = prompt[:marker].rstrip()
    body = {
      "model": JEV_MODEL,
      "state": user_message(data)[:JEV_STATE_CHARS],
      "questions": {
        "should_fire": {"type": "noul", "instructions": rubric + "\n\n" + JEV_FIRE_QUESTION},
        "kind": {"type": "choice", "instructions": rubric + "\n\n" + JEV_KIND_QUESTION, "criteria": JEV_KIND_CRITERIA},
      },
    }
    key = jev_key(url)
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
      with opener.open(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    except (TimeoutError, socket.timeout):
      # /usr/bin/python3 是 3.9，socket.timeout 還不是 TimeoutError 的別名；漏接會被下面的 OSError 分支記成 io_error
      raise RuntimeError("timeout")
    except urllib.error.HTTPError:
      raise RuntimeError("http_error")
    except urllib.error.URLError as error:
      if isinstance(error.reason, (TimeoutError, socket.timeout)):
        raise RuntimeError("timeout")
      raise RuntimeError("transport_error")
    verdict = jev_verdict(raw)
    result.update({"status": "judged", "returned_model": JEV_MODEL, **verdict})
  except FileNotFoundError:
    result["error_class"] = "missing_dependency"
  except json.JSONDecodeError:
    result["error_class"] = "malformed_json"
  except UnicodeDecodeError:
    result["error_class"] = "encoding_error"
  except PermissionError:
    result["error_class"] = "permission"
  except OSError:
    result["error_class"] = "io_error"
  except (RuntimeError, ValueError, TypeError) as error:
    result["error_class"] = str(error)
  result["latency_ms"] = round((time.monotonic() - started) * 1000)
  return result


def audit_target(label, names, production):
  if not test_mode():
    return production
  for name in names:
    value = os.environ.get(name)
    if value:
      return value
  return str(Path(os.environ.get("TMPDIR", "/tmp")) / ("memory-ripple-test-" + label + "-audit.jsonl"))


def audit_path():
  return audit_target("runtime", ("MEMORY_RIPPLE_RUNTIME_AUDIT",), "~/.claude/logs/memory-ripple-runtime-audit.jsonl")


def base_record(data, result):
  return {
    "ts": now(),
    "file": str(data.get("file") or ""),
    "relative_path": str(data.get("relative_path") or ""),
    "session_id": str(data.get("session_id") or ""),
    "agent_id": str(data.get("agent_id") or ""),
    **result,
  }


def main_audit(data):
  append_json(audit_target("main", ("MEMORY_RIPPLE_AUDIT",), "~/.claude/logs/memory-ripple-audit.jsonl"), data)
  output_text(encode_json({"audit_written": True}))


def relative_tokens(relative_path):
  stem = Path(relative_path).stem
  stem = re.sub(r"^(user|feedback|reference|project)_", "", stem)
  stem = re.sub(r"_20[0-9]{2}(?:[_-][0-9]{2})*$", "", stem)
  return [part for part in stem.split("_") if len(part) >= 3 and not STOPWORDS.match(part)][:3]


def sibling_summary(data):
  memory_dir = Path(environment_path("MEMORY_RIPPLE_DIR", "~/.claude/memory")).expanduser()
  relative_path = str(data.get("relative_path") or "")
  source = memory_dir / relative_path
  tokens = relative_tokens(relative_path)
  found = set()
  if memory_dir.is_dir():
    for path in memory_dir.rglob("*.md"):
      if path == source or path.name in {"MEMORY.md", "_orphan_registry.md"}:
        continue
      try:
        text = path.read_text(encoding="utf-8", errors="ignore")
      except OSError:
        continue
      if any(token.lower() in text.lower() for token in tokens):
        found.add(path)
  leaves = sorted(path for path in found if not re.search(r"/(?:_index_[^/]*|_INDEX)\.md$", str(path)))[:6]
  indexes = sorted(path for path in found if re.search(r"/(?:_index_[^/]*|_INDEX)\.md$", str(path)))[:2]
  displayed = leaves + indexes
  return tokens, found, displayed


def fill_message(data):
  tokens, siblings, displayed = sibling_summary(data)
  memory_dir = Path(environment_path("MEMORY_RIPPLE_DIR", "~/.claude/memory")).expanduser()
  label = " ".join(tokens)
  follow_up = "\n請處理這則 memory-ripple 補漏提醒，確認是否要更新 sibling memory。"
  if not siblings:
    return "[memory-ripple] Gemini 語意補漏：這次 memory 寫入可能讓其他檔案的舊前提失效，但檔名 token 未找到 sibling；仍請人工確認跨檔波及面。" + follow_up
  lines = "\n".join("- " + str(path.relative_to(memory_dir)) for path in displayed)
  remainder = len(siblings) - len(displayed)
  if remainder > 0:
    lines += "\n- …另 " + str(remainder) + " 個（token: " + label + "全量 grep 可復原）"
  return "[memory-ripple] Gemini 語意補漏：這次 memory 寫入可能讓其他檔案的舊前提失效，共 " + str(len(siblings)) + " 檔提到同主題（" + label + "），請逐檔 triage。\n" + lines + follow_up


def audit_result(data, result, attempt):
  record = base_record(data, result)
  record["attempt"] = attempt
  try:
    append_json(audit_path(), record)
  except Exception:
    pass


def gemini(data):
  try:
    retries = retry_count(os.environ.get("MEMORY_RIPPLE_GEMINI_RETRIES", "0"))
  except (ValueError, TypeError):
    result = {"status": "unavailable", "mode": "gemini", "requested_model": "", "returned_model": "", "latency_ms": 0, "error_class": "invalid_retries"}
    audit_result(data, result, 0)
    output_text(encode_json(result))
    return
  if wikilink_target_only(data):
    result = {
      "status": "judged",
      "mode": "gemini",
      "requested_model": environment_path("MEMORY_RIPPLE_GEMINI_MODEL", "groq-qwen-3.8-27b"),
      "returned_model": "",
      "latency_ms": 0,
      "error_class": "",
      "should_fire": False,
      "kind": "incremental",
      "confidence": 1.0,
      "classifier": "wikilink-only",
    }
    audit_result(data, result, 0)
    output_text(encode_json(result))
    return
  try:
    config = model_config("gemini")
  except (ValueError, TypeError):
    config = {"model": environment_path("MEMORY_RIPPLE_GEMINI_MODEL", "groq-qwen-3.8-27b"), "fallback_model": None}
  result = {"status": "unavailable", "mode": "gemini", "latency_ms": 0, "error_class": "not_attempted"}
  for attempt in range(retries + 1):
    result = judge(data, "gemini")
    audit_result(data, result, attempt + 1)
    if result.get("status") == "judged":
      break
    if attempt < retries:
      time.sleep(1)
  attempts_used = retries + 1
  if result.get("status") != "judged" and config["fallback_model"] and config["fallback_model"] != config["model"]:
    attempts_used += 1
    fallback_result = judge(data, "gemini", config["fallback_model"])
    audit_result(data, fallback_result, attempts_used)
    if fallback_result.get("status") == "judged":
      fallback_result["fallback_used"] = True
      result = fallback_result
  # 最後一層：主判官與 Gemini fallback 都沒得到 judged 才試 Jev；Jev 也失敗時 result 維持原本的 unavailable
  if result.get("status") != "judged":
    jev_result = judge_jev(data)
    if jev_result is not None:
      audit_result(data, jev_result, attempts_used + 1)
      if jev_result.get("status") == "judged":
        jev_result["fallback_used"] = True
        result = jev_result
  if result.get("status") == "judged" and result.get("should_fire") is True and data.get("mechanical_fired") is not True:
    try:
      result["message"] = fill_message(data)
    except Exception:
      result["message"] = ""
  output_text(encode_json(result))


def c068(data):
  result = judge(data, "c068")
  audit_result(data, result, 1)
  try:
    config = model_config("c068")
  except (ValueError, TypeError):
    config = {"model": environment_path("MEMORY_RIPPLE_GEMINI_MODEL", "groq-qwen-3.8-27b"), "fallback_model": None}
  if result.get("status") != "judged" and config["fallback_model"] and config["fallback_model"] != config["model"]:
    fallback_result = judge(data, "c068", config["fallback_model"])
    audit_result(data, fallback_result, 2)
    if fallback_result.get("status") == "judged":
      fallback_result["fallback_used"] = True
      result = fallback_result
  output_text(encode_json(result))


def main():
  arguments = sys.argv[1:]
  if len(arguments) != 1:
    raise SystemExit(2)
  mode = arguments[0]
  data = read_input()
  if mode == "main-audit":
    main_audit(data)
  elif mode == "gemini":
    gemini(data)
  elif mode == "c068":
    c068(data)
  else:
    raise SystemExit(2)


if __name__ == "__main__":
  main()
