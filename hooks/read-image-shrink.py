#!/usr/bin/env python3
"""PreToolUse(Read)：大圖先縮成長邊 1568 的 JPEG 再讀，原圖不動。

為什麼：主模型支援高解析度時，CC 會把 1920x1080 截圖原尺寸存進 transcript（每張約 430KB、還存兩份），
讀 session 的機制（session-audit、每日分析、auto-memory 64MB 上限）全被拖大。1568 是官方 Standard 解析度上限。
提示型：任何判斷不出或出錯的情況都照原樣讀原圖，不擋 Read。不保證像素級細節；要看原圖時建立停用檔。
停用：touch ~/.local/state/read-image-shrink/disabled
"""
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

LONG_EDGE = 1568
MIN_BYTES = 150 * 1024
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".tif", ".tiff", ".bmp"}
STATE = Path(os.environ.get("READ_IMAGE_SHRINK_STATE", Path.home() / ".local/state/read-image-shrink"))
CACHE = Path(os.environ.get("READ_IMAGE_SHRINK_CACHE", Path.home() / ".cache/read-image-shrink"))
KEEP_SECONDS = 7 * 86400


def dimensions(path):
  out = subprocess.run(["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                       capture_output=True, text=True, timeout=10).stdout
  width = re.search(r"pixelWidth: (\d+)", out)
  height = re.search(r"pixelHeight: (\d+)", out)
  return (int(width.group(1)), int(height.group(1))) if width and height else None


def safe_cache():
  # 快取資料夾被換成 symlink 時不寫，避免縮圖寫到別處
  CACHE.mkdir(parents=True, exist_ok=True)
  info = os.lstat(CACHE)
  return stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def prune():
  now = time.time()
  for item in CACHE.iterdir():
    try:
      if now - item.lstat().st_mtime > KEEP_SECONDS:
        item.unlink()
    except OSError:
      pass


def shrink(source, info):
  # 檔名由原路徑＋修改時間＋大小組成：原圖一改就換新檔，不需要內容雜湊
  name = re.sub(r"[^A-Za-z0-9._-]", "_", str(source))[-150:]
  target = CACHE / f"{name}.{info.st_mtime_ns}.{info.st_size}.jpg"
  if not target.exists():
    temp = target.with_suffix(".tmp.jpg")
    subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "75", "-Z", str(LONG_EDGE),
                    str(source), "--out", str(temp)], capture_output=True, timeout=30, check=True)
    os.replace(temp, target)
  return target


def decide(payload):
  if payload.get("tool_name") != "Read" or (STATE / "disabled").exists():
    return None
  tool_input = payload.get("tool_input") or {}
  path = tool_input.get("file_path")
  if not isinstance(path, str):
    return None
  source = Path(path)
  if source.suffix.lower() not in EXTENSIONS:
    return None
  if source.resolve().is_relative_to(CACHE.resolve()):
    return None
  info = source.stat()
  if not stat.S_ISREG(info.st_mode) or info.st_size < MIN_BYTES:
    return None
  size = dimensions(source)
  if size is None or max(size) <= LONG_EDGE:
    return None
  if not safe_cache():
    return None
  target = shrink(source, info)
  prune()
  return {
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "updatedInput": dict(tool_input, file_path=str(target)),
      "additionalContext": f"read-image-shrink：{path}（{size[0]}x{size[1]}）已縮成長邊 {LONG_EDGE} 供讀取，原圖未改；要看原尺寸細節請說明，使用者可停用此 hook。",
    }
  }


def main():
  try:
    result = decide(json.loads(sys.stdin.read() or "{}"))
  except Exception:
    result = None
  if result:
    print(json.dumps(result, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  sys.exit(main())
