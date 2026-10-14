#!/usr/bin/env python3
"""Run `tov check --json` on files and apply every fix marked "safe".

Usage: scripts/check.py [--no-fix] FILE...
"""
import json, subprocess, sys

def run(files):
    out = subprocess.run(["tov", "check", "--json", *files], capture_output=True, text=True).stdout
    return json.loads(out)

def apply_safe(diags):
    by_file = {}
    for d in diags:
        for f in d.get("fixes", []):
            if f.get("applicability") == "safe":
                for e in f["edits"]:
                    by_file.setdefault(d["file"], []).append(e)
                break
    for path, edits in by_file.items():
        lines = open(path).read().split("\n")
        # apply bottom-up so earlier offsets stay valid
        for e in sorted(edits, key=lambda e: (e["start"]["line"], e["start"]["col"]), reverse=True):
            sl, sc, el, ec = e["start"]["line"] - 1, e["start"]["col"] - 1, e["end"]["line"] - 1, e["end"]["col"] - 1
            # tov reports columns in characters (code points), not bytes
            head = lines[sl][:sc]
            tail = lines[el][ec:]
            lines[sl:el + 1] = (head + e["text"] + tail).split("\n")
        open(path, "w").write("\n".join(lines))
    return sum(len(v) for v in by_file.values())

def main():
    args = sys.argv[1:]
    fix = "--no-fix" not in args
    files = [a for a in args if a != "--no-fix"]
    for _ in range(5):
        d = run(files)
        if not fix or apply_safe(d["diagnostics"]) == 0:
            break
        print("applied safe fixes; re-checking", file=sys.stderr)
    for x in d["diagnostics"]:
        print(f'{x["code"]} {x["file"]}:{x["start"]["line"]}:{x["start"]["col"]} {x["message"]}')
        for n in x.get("notes", []):
            print(f'    {n["label"]}: {n["text"]}')
    sys.exit(1 if d["errors"] else 0)

main()
