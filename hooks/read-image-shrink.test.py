#!/usr/bin/env python3
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().with_name("read-image-shrink.py")


def noise_png(path, width, height):
  # 隨機雜訊壓不小，確保檔案大小超過門檻、只剩尺寸這個變因
  row = (width * 3 + 3) & ~3
  pixels = os.urandom(row * height)
  header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
  info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
  bmp = path.with_suffix(".bmp")
  bmp.write_bytes(header + info + pixels)
  subprocess.run(["/usr/bin/sips", "-s", "format", "png", str(bmp), "--out", str(path)], capture_output=True, check=True)
  bmp.unlink()
  return path


def dims(path):
  out = subprocess.run(["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], capture_output=True, text=True).stdout
  return int(re.search(r"pixelWidth: (\d+)", out).group(1)), int(re.search(r"pixelHeight: (\d+)", out).group(1))


class ReadImageShrinkTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    root = Path(self.tmp.name)
    self.root, self.state, self.cache = root, root / "state", root / "cache"
    self.env = dict(os.environ, READ_IMAGE_SHRINK_STATE=str(self.state), READ_IMAGE_SHRINK_CACHE=str(self.cache))

  def tearDown(self):
    self.tmp.cleanup()

  def hook(self, path, tool="Read", extra=None):
    payload = {"tool_name": tool, "tool_input": dict({"file_path": str(path)}, **(extra or {}))}
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=self.env, timeout=60)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None

  def test_large_image_is_read_through_a_1568_copy_and_original_is_untouched(self):
    source = noise_png(self.root / "shot.png", 1920, 1080)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    out = self.hook(source, extra={"offset": 1})
    target = Path(out["updatedInput"]["file_path"])
    self.assertEqual(out["updatedInput"]["offset"], 1)
    self.assertEqual(max(dims(target)), 1568)
    self.assertTrue(target.is_relative_to(self.cache))
    self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), before)
    self.assertIn(str(source), out["additionalContext"])
    self.assertEqual(self.hook(source)["updatedInput"]["file_path"], str(target))

  def test_boundary_is_strictly_above_1568(self):
    self.assertIsNone(self.hook(noise_png(self.root / "edge.png", 1568, 900)))
    self.assertIsNotNone(self.hook(noise_png(self.root / "over.png", 1569, 900)))

  def test_small_files_non_images_other_tools_and_missing_files_pass_through(self):
    self.assertIsNone(self.hook(noise_png(self.root / "small.png", 200, 100)))
    text = self.root / "notes.md"
    text.write_text("x" * 300000)
    self.assertIsNone(self.hook(text))
    big = noise_png(self.root / "big.png", 2000, 1200)
    self.assertIsNone(self.hook(big, tool="Write"))
    self.assertIsNone(self.hook(self.root / "missing.png"))

  def test_disabled_and_symlinked_cache_fall_back_to_the_original(self):
    big = noise_png(self.root / "big.png", 2000, 1200)
    self.state.mkdir()
    (self.state / "disabled").write_text("")
    self.assertIsNone(self.hook(big))
    (self.state / "disabled").unlink()
    elsewhere = self.root / "elsewhere"
    elsewhere.mkdir()
    self.cache.symlink_to(elsewhere)
    self.assertIsNone(self.hook(big))
    self.assertEqual(list(elsewhere.iterdir()), [])

  def test_reading_the_cached_copy_is_not_shrunk_again(self):
    big = noise_png(self.root / "big.png", 2000, 1200)
    target = Path(self.hook(big)["updatedInput"]["file_path"])
    self.assertIsNone(self.hook(target))


if __name__ == "__main__":
  unittest.main(verbosity=2)
