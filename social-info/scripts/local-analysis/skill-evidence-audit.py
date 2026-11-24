#!/usr/bin/env python3
"""skill-evidence-audit.py — skill 退役判斷的第二個軸（2026-08-01 建，HKUDS/OpenSpace 抽件 3）。

## 問題

既有的死庫存偵測只看一個軸：這個 skill 被叫過幾次。零 invoke 不足以判退役——可能是沒用，
也可能是需求還沒來。加上「這個 skill 有沒有證據支撐」這個軸，兩軸交叉才有判斷力：

                零 invoke        有 invoke
  弱證據        ← 最該退役        ← 在用但沒驗過，該補驗證
  強證據        需求還沒來，留著   正常

## 這支量的是什麼（誠實聲明，不要當成別的）

量的是「**SKILL.md 自身有沒有引用證據的痕跡**」——踩過的坑、量化數字、實測／fixture 提及、
具體日期。**不是**「固化當下有沒有做過獨立驗證」。

原本要做的是後者（OpenSpace 的 capture contract 是要求兩組互斥證據），但實測還原不了：
從 session 歷史回推固化當時的驗證行為，光 grep 3 個 skill 就 290 秒（73 個約 2 小時），
且每個 skill 有 145-548 個候選 session 要讀。成本不成比例。

前者是後者的 proxy：有做過驗證的 skill 傾向會把證據寫進文件（踩過的坑、實測數字）。
proxy 會漏掉「驗過但沒寫」的情況，也會誤收「抄了漂亮數字但沒驗」的情況。
**用途僅限退役排序的參考軸，不作為品質裁決。**

## 為什麼不做成 INVENTORY.md 的手維護欄位

原案是加一欄手動填。但這個值 100% 可從 SKILL.md 算出來——手維護的衍生欄位必然 stale
（改了 SKILL.md 沒改 INVENTORY，欄位就開始說謊），而且 INVENTORY 主表已 7 欄、終端讀不下。
改成隨時可算的稽核，INVENTORY 零改動。

用法：
  python3 skill-evidence-audit.py            # 人讀報告
  python3 skill-evidence-audit.py --json     # 機器讀
  --skills-dir <path>（預設 ~/.claude/skills）
"""

import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"

SIGNALS = {
    "pit": (re.compile(r"踩過的坑|踩坑|反例|失敗模式"), "踩坑段"),
    "num": (re.compile(r"\d+\s*(?:次|筆|個|案)|(?<![\d/])\d+\s*/\d+(?![\d/])|\d+%"), "量化數字"),
    "test": (re.compile(r"實測|實跑|fixture|回歸|驗證輸出|probe|測試通過", re.IGNORECASE), "實測提及"),
    "date": (re.compile(r"(?<!\d)20\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?!\d)"), "具體日期"),
}

STRONG, WEAK, BARE = 3, 1, 0


def _has_valid_date(rx, text):
    for m in rx.finditer(text):
        try:
            datetime.date.fromisoformat(m.group(0))
            return True
        except ValueError:
            continue
    return False


def doc_signals(text):
    hit = {}
    for key, (rx, _) in SIGNALS.items():
        hit[key] = _has_valid_date(rx, text) if key == "date" else bool(rx.search(text))
    return hit


def grade(hit):
    n = sum(hit.values())
    if n >= STRONG:
        return "strong"
    if n > BARE:
        return "weak"
    return "bare"


def invoke_counts():
    counts = defaultdict(int)
    for p in PROJECTS.rglob("*.jsonl"):
        if "/subagents/" in str(p):
            continue
        try:
            with open(p, errors="ignore") as f:
                for line in f:
                    if '"Skill"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(d, dict) or d.get("type") != "assistant":
                        continue
                    msg = d.get("message")
                    if not isinstance(msg, dict):
                        continue
                    content = msg.get("content")
                    if not isinstance(content, list):
                        continue
                    for b in content:
                        if not isinstance(b, dict) or b.get("type") != "tool_use":
                            continue
                        if b.get("name") != "Skill":
                            continue
                        inp = b.get("input")
                        if not isinstance(inp, dict):
                            continue
                        s = inp.get("skill")
                        if isinstance(s, str):
                            counts[s.split(":")[-1]] += 1
        except OSError:
            continue
    return counts


_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _split_md_table_row(line):
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        bs = 0
        idx = len(stripped) - 2
        while idx >= 0 and stripped[idx] == "\\":
            bs += 1
            idx -= 1
        if bs % 2 == 0:
            stripped = stripped[:-1]
    cells = []
    buf = []
    i = 0
    n = len(stripped)
    while i < n:
        ch = stripped[i]
        if ch == "\\" and i + 1 < n and stripped[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf).strip())
    return cells


def _is_separator_row(cells):
    return bool(cells) and all(_SEP_CELL_RE.match(c) for c in cells)


def _extract_skill_name(cell):
    cleaned = _MD_LINK_RE.sub(r"\1", cell).strip()
    if not cleaned:
        return ""
    token = cleaned.split()[0]
    return token.strip("`*_")


def origins(skills_dir):
    """從 INVENTORY.md 讀 Origin 欄。cloned skill 沒有『踩過的坑』段是因為那是使用者自己的
    寫作慣例、不是沒驗證——不分 origin 就會系統性冤枉 clone 來的 skill。"""
    inv = skills_dir / "INVENTORY.md"
    out = {}
    if not inv.is_file():
        return out
    try:
        text = inv.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    in_fence = None
    table_cols = None
    for line in text.splitlines():
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = marker
                table_cols = None
            elif in_fence == marker:
                in_fence = None
            continue
        if in_fence is not None:
            continue
        cells = _split_md_table_row(line)
        if cells is None:
            table_cols = None
            continue
        if _is_separator_row(cells):
            continue
        lowered = [c.strip("`*_ ").lower() for c in cells]
        if "skill" in lowered and "origin" in lowered:
            table_cols = (lowered.index("skill"), lowered.index("origin"))
            continue
        if table_cols is None:
            continue
        skill_idx, origin_idx = table_cols
        if len(cells) <= max(skill_idx, origin_idx):
            continue
        name = _extract_skill_name(cells[skill_idx])
        origin = cells[origin_idx].strip().lower()
        if not name or not origin or set(name) <= set("-: "):
            continue
        if name.lower() in ("skill", "audit", "name", "origin"):
            continue
        out[name] = "self" if "self-written" in origin else "cloned"
    return out


def collect(skills_dir):
    out = []
    if not skills_dir.is_dir():
        return out
    try:
        entries = sorted(skills_dir.iterdir())
    except OSError:
        return out
    for d in entries:
        if not d.is_dir():
            continue
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        t = raw.decode("utf-8", errors="ignore")
        hit = doc_signals(t)
        out.append(
            {
                "skill": d.name,
                "bytes": len(raw),
                "signals": hit,
                "signal_count": sum(hit.values()),
                "evidence": grade(hit),
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", default=str(HOME / ".claude" / "skills"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sd = Path(args.skills_dir)
    if not sd.is_dir():
        print(f"skills directory not found or not a directory: {sd}", file=sys.stderr)
        return 2
    rows = collect(sd)
    counts = invoke_counts()
    orig = origins(sd)
    for r in rows:
        r["invokes"] = counts.get(r["skill"], 0)
        r["origin"] = orig.get(r["skill"], "unknown")

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print("## Skill 證據強度 × 使用量")
    print()
    print("量的是 **SKILL.md 有沒有引用證據的痕跡**（踩坑段／量化數字／實測提及／具體日期，4 選 N），")
    print("**不是**「固化當下有沒有獨立驗證過」——後者從 session 歷史還原成本不成比例（實測 73 個約 2 小時）。")
    print("僅作退役排序參考軸，不是品質裁決。invoke 數只計 Skill tool 自動觸發，手打 slash 不計入。")
    print()
    print("⚠️ **分 origin 看**：cloned skill 沒有踩坑段是因為那是自寫慣例、不代表沒驗證，")
    print("所以外部 skill 的弱訊號**不構成退役理由**，只有零使用才是。兩類判準不同、不要混。")
    print()

    def marks_of(r):
        return "".join(
            (SIGNALS[k][1][0] if r["signals"][k] else "·") for k in ("pit", "num", "test", "date")
        )

    selfw = [r for r in rows if r["origin"] == "self"]
    other = [r for r in rows if r["origin"] != "self"]

    print(f"### 🔴 自寫 + 零 invoke + 弱證據 — 最該檢討（自寫共 {len(selfw)}）")
    hot = sorted(
        [r for r in selfw if r["invokes"] == 0 and r["evidence"] != "strong"],
        key=lambda x: (x["signal_count"], -x["bytes"]),
    )
    if not hot:
        print("（無——自寫 skill 沒有同時零使用且缺證據的）")
    for r in hot:
        print(f"- `{r['skill']}` — invoke 0、訊號 {marks_of(r)}（{r['signal_count']}/4）")
    print()

    print("### 🟡 自寫 + 有 invoke + 弱證據 — 在用但文件沒證據，該補")
    warm = sorted(
        [r for r in selfw if r["invokes"] > 0 and r["evidence"] != "strong"],
        key=lambda x: -x["invokes"],
    )
    for r in warm[:8]:
        print(f"- `{r['skill']}` — invoke {r['invokes']}、訊號 {marks_of(r)}（{r['signal_count']}/4）")
    if len(warm) > 8:
        print(f"- …另 {len(warm) - 8} 個")
    if not warm:
        print("（無）")
    print()

    name_only = set()
    for sp in ("~/.claude/settings.json", "~/.claude-team/settings.json"):
        try:
            cfg = json.loads(Path(sp).expanduser().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(cfg, dict):
            continue
        ov = cfg.get("skillOverrides")
        if not isinstance(ov, dict):
            continue
        name_only.update(k for k, v in ov.items() if v == "name-only")

    print(f"### ⚪ 外部 skill 零使用（共 {len(other)} 個外部/未知 origin）")
    print("判準只看使用量——外部 skill 的證據訊號不適用。零使用代表庫存成本（context 注入 + 上游追蹤）沒回報。")
    cold_all = sorted([r for r in other if r["invokes"] == 0], key=lambda x: x["skill"])
    cold = [r for r in cold_all if r["skill"] not in name_only]
    excluded = len(cold_all) - len(cold)
    print(f"零使用 {len(cold)} 個：" + "、".join(f"`{r['skill']}`" for r in cold[:20]))
    if len(cold) > 20:
        print(f"…另 {len(cold) - 20} 個")
    if excluded:
        print(f"（另 {excluded} 個零使用但為 name-only——listing 只注入名字、由 router/手動叫用，零 invoke 屬設計預期，不列退役候選；2026-08-04 拍板）")
    print()

    strong_used = [r for r in rows if r["invokes"] > 0 and r["evidence"] == "strong"]
    print(f"✅ 有 invoke + 強證據：{len(strong_used)} 個（正常，不列）")
    print()
    print(
        f"（共 {len(rows)} 個 skill：自寫 {len(selfw)}、外部/未知 {len(other)}；"
        "訊號符號依序為 踩坑段／量化數字／實測提及／具體日期，`·` 表示缺）"
    )


if __name__ == "__main__":
    sys.exit(main())
