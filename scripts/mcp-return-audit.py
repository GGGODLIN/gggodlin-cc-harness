#!/usr/bin/env python3
"""mcp-return-audit.py — 量測檢索類 MCP tool 的「回傳品質」，不只數呼叫次數。

動機：搜尋 / 檢索 / RAG 類工具失敗時不報錯——回一堆看起來像樣但型別不對的結果，
agent 拿著噪音繼續推理。只統計 tool_use 呼叫數會判定「採用良好」而整條軸壞掉。
實例：semble 兩個月 768 次呼叫全綠，但回傳 6,401 個檔案路徑裡 .md 出現 0 次
（MCP server 註冊時沒帶 --content，只索引程式碼）。
紀律來源：memory feedback_adoption_metric_must_check_returned_content_2026_07_29

做法：從 session jsonl 配對 tool_use.id → tool_result.tool_use_id，解出回傳內容裡的
檔案路徑，出副檔名分佈。目標型別出現 0 次 = 結構性取不到。

用法:
  mcp-return-audit.py <tool-name-substring> [--since YYYY-MM-DD] [--want .md,.txt]

範例:
  mcp-return-audit.py semble-docs --since 2026-07-29 --want .md
  mcp-return-audit.py mcp__semble__ --want .md,.rst
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
# 只認回傳 JSON 的 file_path 欄位（含跳脫過的 \"file_path\"）。
# 不要改成通用路徑 regex：semble 這類工具的 result 內含 code snippet 與 URL，
# 通用 regex 會把 snippet 裡提到的路徑、和 example.com / foo.dev 這種網址
# 一起算進副檔名分佈，直接推翻結論（2026-07-30 首版就是這樣誤報 .md=33）。
PATH_RE = re.compile(r'\\?"(?:file_)?path\\?"\s*:\s*\\?"([^"\\]+)')
EXT_RE = re.compile(r"\.(\w{1,8})$")


def parse_args(argv):
    if not argv:
        sys.exit(__doc__)
    tool = argv[0]
    since = None
    want = []
    i = 1
    while i < len(argv):
        if argv[i] == "--since" and i + 1 < len(argv):
            since = argv[i + 1]
            i += 2
        elif argv[i] == "--want" and i + 1 < len(argv):
            want = [w if w.startswith(".") else "." + w for w in argv[i + 1].split(",")]
            i += 2
        else:
            sys.exit(f"unknown arg: {argv[i]}\n{__doc__}")
    return tool, since, want


def blocks(msg):
    content = msg.get("content")
    return content if isinstance(content, list) else []


def result_text(block):
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def scan(tool, since):
    calls = {}
    results = {}
    # 必須含 subagents/ transcript：實測 semble 的 4,558 個命中 jsonl 裡 3,942 個
    # （86%）在 subagent 底下——排掉它們會少算 4/5 的呼叫（2026-07-30 首版的錯）。
    for jsonl in PROJECTS.rglob("*.jsonl"):
        try:
            lines = jsonl.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if tool not in line and "tool_result" not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = rec.get("timestamp", "")
            if since and ts and ts[:10] < since:
                continue
            msg = rec.get("message") or {}
            for block in blocks(msg):
                btype = block.get("type")
                if btype == "tool_use" and tool in (block.get("name") or ""):
                    calls[block.get("id")] = {
                        "name": block.get("name"),
                        "input": block.get("input") or {},
                        "date": ts[:10],
                    }
                elif btype == "tool_result":
                    results[block.get("tool_use_id")] = result_text(block)
    return calls, results


def main():
    tool, since, want = parse_args(sys.argv[1:])
    calls, results = scan(tool, since)
    if not calls:
        print(f"0 calls matched '{tool}'" + (f" since {since}" if since else ""))
        return

    paired = {cid: results[cid] for cid in calls if cid in results}
    exts = Counter()
    empty = 0
    for text in paired.values():
        found = PATH_RE.findall(text)
        if not found:
            empty += 1
        for path in found:
            m = EXT_RE.search(path)
            exts["." + m.group(1).lower() if m else "(no-ext)"] += 1

    print(f"tool match      : {tool}" + (f"  (since {since})" if since else ""))
    print(f"calls           : {len(calls)}")
    print(f"paired results  : {len(paired)}  (unpaired {len(calls) - len(paired)})")
    print(f"zero-path result: {empty}   <- 呼叫成功但沒回傳任何檔案路徑")
    print(f"total paths     : {sum(exts.values())}")
    print("--- returned extension histogram ---")
    for ext, n in exts.most_common(15):
        print(f"  {ext:<8} {n}")
    if want:
        print("--- wanted types ---")
        for w in want:
            n = exts.get(w, 0)
            flag = "OK" if n else "*** 0 次 = 結構性取不到 ***"
            print(f"  {w:<8} {n}  {flag}")
    print("--- per-day calls ---")
    for day, n in sorted(Counter(c["date"] for c in calls.values()).items()):
        print(f"  {day}  {n}")


if __name__ == "__main__":
    main()
