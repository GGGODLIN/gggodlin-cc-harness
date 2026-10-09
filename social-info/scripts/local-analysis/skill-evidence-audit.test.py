#!/usr/bin/env python3
"""skill-evidence-audit.py 的回歸 fixture。

鎖住的線：
  (1) 四個訊號各自抓得到、缺的抓不到（訊號定義是這支的全部判斷力）
  (2) grade 分級門檻正確
  (3) origin 解析正確——**分 origin 是本檔最重要的修正**：不分的話 31 個外部 skill 被誤判
      「最該退役」，分了之後收斂成 2 個。這條迴歸防止有人把 origin 拿掉。
  (4) INVENTORY 表格雜訊（分隔列 / 表頭 / 粗體名）不得被當成 skill 名
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sea", Path(__file__).parent / "skill-evidence-audit.py"
)
sea = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sea)

PASS = FAIL = 0


def check(name, want, got):
    global PASS, FAIL
    if want == got:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}\n        want {want!r}\n        got  {got!r}")
        FAIL += 1


print("\n=== 訊號偵測 ===")
check("踩坑段", True, sea.doc_signals("## 踩過的坑\n- 撞過 X")["pit"])
check("反例也算踩坑類", True, sea.doc_signals("反例：不要這樣做")["pit"])
check("量化數字（次）", True, sea.doc_signals("實際跑了 47 次")["num"])
check("量化數字（百分比）", True, sea.doc_signals("命中率 91%")["num"])
check("量化數字（分數式）", True, sea.doc_signals("通過 18/18")["num"])
check("實測提及", True, sea.doc_signals("2026-08-01 實測驗證")["test"])
check("fixture 也算實測", True, sea.doc_signals("備 fixture 回歸")["test"])
check("具體日期", True, sea.doc_signals("2026-07-12 拍板")["date"])
bare = sea.doc_signals("這是一個純描述的 skill，沒有任何證據。")
check("純散文四個訊號全無", 0, sum(bare.values()))

print("\n=== 分級門檻 ===")
check("4 訊號 → strong", "strong", sea.grade({"a": 1, "b": 1, "c": 1, "d": 1}))
check("3 訊號 → strong", "strong", sea.grade({"a": 1, "b": 1, "c": 1, "d": 0}))
check("2 訊號 → weak", "weak", sea.grade({"a": 1, "b": 1, "c": 0, "d": 0}))
check("1 訊號 → weak", "weak", sea.grade({"a": 1, "b": 0, "c": 0, "d": 0}))
check("0 訊號 → bare", "bare", sea.grade({"a": 0, "b": 0, "c": 0, "d": 0}))

print("\n=== origin 解析（本檔最重要的修正，不得退化）===")
with tempfile.TemporaryDirectory() as td:
    sd = Path(td)
    (sd / "INVENTORY.md").write_text(
        "\n".join(
            [
                "# Skill Inventory",
                "",
                "| Skill | Origin | Audit | 備註 |",
                "| ----- | ------ | ----- | ---- |",
                "| my-skill | self-written | yes | 自寫 |",
                "| their-skill | Anthropic 官方 | no | clone |",
                "| **bold-skill** | self-written | yes | 粗體名 |",
                "| forked-one | Anthropic 官方 (frozen fork) | yes (patched) | fork |",
            ]
        )
    )
    o = sea.origins(sd)
    check("self-written → self", "self", o.get("my-skill"))
    check("外部 → cloned", "cloned", o.get("their-skill"))
    check("粗體名去星號", "self", o.get("bold-skill"))
    check("frozen fork 仍算 cloned", "cloned", o.get("forked-one"))
    check("表頭不得被當 skill", None, o.get("Skill"))
    check("分隔列不得被當 skill", None, o.get("-----"))

print("\n=== collect：只收有 SKILL.md 的目錄 ===")
with tempfile.TemporaryDirectory() as td:
    sd = Path(td)
    (sd / "has-skill").mkdir()
    (sd / "has-skill" / "SKILL.md").write_text("## 踩過的坑\n2026-08-01 實測 5 次")
    (sd / "no-skill").mkdir()
    (sd / "no-skill" / "README.md").write_text("x")
    (sd / "INVENTORY.md").write_text("| Skill | Origin |\n| has-skill | self-written |")
    rows = sea.collect(sd)
    check("只收到 1 個", 1, len(rows))
    check("名稱正確", "has-skill", rows[0]["skill"])
    check("四訊號全中 → strong", "strong", rows[0]["evidence"])

print(f"\n---- {PASS} passed, {FAIL} failed ----")
sys.exit(1 if FAIL else 0)
