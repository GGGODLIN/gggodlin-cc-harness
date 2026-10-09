import json, os, glob, sys, re
from collections import defaultdict

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
root = os.path.expanduser("~/.claude/projects")

mcp_code = defaultdict(int)
mcp_docs = defaultdict(int)
cli_any = defaultdict(int)
cli_docs = defaultdict(int)
sub_any = defaultdict(int)
sessions_by_day = defaultdict(set)

cli_re = re.compile(r"\bsemble\b\s+(search|find-related)")

for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
    sid = os.path.basename(f)[:-6]
    try:
        with open(f, "r", errors="ignore") as fh:
            for line in fh:
                if '"tool_use"' not in line and '"semble' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = (rec.get("timestamp") or "")[:10]
                if not ts:
                    continue
                sessions_by_day[ts].add(sid)
                msg = rec.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                        continue
                    name = blk.get("name", "")
                    inp = blk.get("input") or {}
                    if name.startswith("mcp__semble-docs__"):
                        mcp_docs[ts] += 1
                    elif name.startswith("mcp__semble__"):
                        mcp_code[ts] += 1
                    elif name == "Bash":
                        cmd = str(inp.get("command", ""))
                        if cli_re.search(cmd):
                            cli_any[ts] += 1
                            if "--content docs" in cmd or "--content all" in cmd:
                                cli_docs[ts] += 1
                    elif name in ("Agent", "Task"):
                        p = json.dumps(inp)
                        if "semble" in p:
                            sub_any[ts] += 1
    except Exception:
        continue

days = sorted(set(list(mcp_code) + list(mcp_docs) + list(cli_any) + list(sub_any)))[-DAYS:]
print(f"{'日期':<12}{'MCP-code':>9}{'MCP-docs':>10}{'CLI':>6}{'(其中docs)':>11}{'subagent':>10}{'活躍session':>12}")
tc = td = tl = tld = ts_ = 0
for d in days:
    print(f"{d:<12}{mcp_code[d]:>9}{mcp_docs[d]:>10}{cli_any[d]:>6}{cli_docs[d]:>11}{sub_any[d]:>10}{len(sessions_by_day[d]):>12}")
    tc += mcp_code[d]; td += mcp_docs[d]; tl += cli_any[d]; tld += cli_docs[d]; ts_ += sub_any[d]
print("-" * 70)
print(f"{'合計':<12}{tc:>9}{td:>10}{tl:>6}{tld:>11}{ts_:>10}")
print(f"\n三 path 佔比: MCP {tc+td} / CLI {tl} / subagent {ts_}")
