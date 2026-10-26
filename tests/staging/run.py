#!/usr/bin/env python3
"""Runs a chosen set of staging checks against a deployed gateway and collects their results in one folder.

Usage: tests/staging/run.py --checks smoke,creates,trickle,declared,dcr [--out staging-results] [--soak-duration 30m]
                            [-- extra arguments for every check]
Checks: smoke (smoke_check.py), creates, bridge (needs RAIJU_OLD_URL and RAIJU_NEW_URL), soak (body_soak.py),
trickle, declared, dcr (dcr_flood.py), cluster (cluster_check.py all), watch (cluster_check.py watch).
"all" is smoke,creates,trickle,declared,dcr; the soak, the cluster checks and the bridge run only when named.
Settings come from the environment (tests/staging/kit.py). The folder gets results.jsonl (one line per result),
<check>.log (each check's output), summary.md (a table) and, for the soak, its samples, chart and summary.
The exit status is 1 when a check failed or could not run, 0 when every check passed or skipped.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402

DEFAULT = ["smoke", "creates", "trickle", "declared", "dcr"]
KNOWN = ["smoke", "creates", "bridge", "soak", "trickle", "declared", "dcr", "cluster", "watch"]


def plan(checks, env, out, soak_duration):
    """[(check, argv)] for the named checks; raises ValueError for an unknown one."""
    names = []
    for c in kit.split_list(checks):
        if c == "all":
            names += DEFAULT
        elif c in KNOWN:
            names.append(c)
        else:
            raise ValueError(f"unknown check {c!r} (known: all, {', '.join(KNOWN)})")
    seen, steps = set(), []
    for c in names:
        if c in seen:
            continue
        seen.add(c)
        if c == "smoke":
            steps.append((c, ["smoke_check.py"]))
        elif c == "creates":
            steps.append((c, ["creates.py"]))
        elif c == "bridge":
            steps.append((c, ["bridge.py", "--old-url", env.get("RAIJU_OLD_URL", ""), "--new-url", env.get("RAIJU_NEW_URL", "")]))
        elif c == "soak":
            steps.append((c, ["body_soak.py", "--duration", soak_duration, "--out", os.path.join(out, "soak")]))
        elif c == "trickle":
            steps.append((c, ["trickle.py"]))
        elif c == "declared":
            steps.append((c, ["declared.py"]))
        elif c == "dcr":
            steps.append((c, ["dcr_flood.py"]))
        elif c == "cluster":
            steps.append((c, ["cluster_check.py", "all"]))
        elif c == "watch":
            steps.append((c, ["cluster_check.py", "watch"]))
    return steps


def summary_md(results, codes):
    lines = ["| Check | Status | Numbers |", "|---|---|---|"]
    for r in results:
        nums = ", ".join(f"{k}={kit.fmt_num(v)}" for k, v in r.get("numbers", {}).items())
        lines.append(f"| {r['check']} | {r['status']} | {nums} |")
    lines += ["", "| Script | Exit |", "|---|---|"]
    lines += [f"| {c} | {code} |" for c, code in codes.items()]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--checks", default="smoke")
    ap.add_argument("--out", default="staging-results")
    ap.add_argument("--soak-duration", default="30m")
    ap.add_argument("extra", nargs="*", help="arguments passed to every check (after --)")
    a = ap.parse_args(argv)
    env = dict(os.environ)
    if not kit.norm_url(env.get("RAIJU_BASE_URL") or env.get("BASE_URL") or ""):
        print("FAIL run: no RAIJU_BASE_URL: nothing was run", flush=True)
        return 1
    try:
        steps = plan(a.checks, env, a.out, a.soak_duration)
    except ValueError as e:
        print(f"FAIL run: {e}", flush=True)
        return 1
    os.makedirs(a.out, exist_ok=True)
    env["RAIJU_RESULTS_DIR"] = os.path.abspath(a.out)
    results_file = os.path.join(a.out, "results.jsonl")
    codes = {}
    for name, cmd in steps:
        print(f"== {name}: {' '.join(cmd)}", flush=True)
        t0 = time.time()
        with open(os.path.join(a.out, name + ".log"), "w") as log:
            p = subprocess.Popen([sys.executable, os.path.join(HERE, cmd[0])] + cmd[1:] + a.extra, env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                sys.stdout.write(line)
                log.write(line)
            codes[name] = p.wait()
        print(f"== {name}: exit {codes[name]} in {time.time() - t0:.0f} s", flush=True)
    results = []
    if os.path.exists(results_file):
        with open(results_file) as f:
            results = [json.loads(line) for line in f if line.strip()]
    with open(os.path.join(a.out, "summary.md"), "w") as f:
        f.write(summary_md(results, codes))
    failed = [r for r in results if r["status"] == "FAIL"]
    bad_exit = [c for c, code in codes.items() if code != 0]
    print(f"staging: {sum(r['status'] == 'PASS' for r in results)} passed, {len(failed)} failed, "
          f"{sum(r['status'] == 'SKIP' for r in results)} skipped; results in {a.out}", flush=True)
    return 1 if failed or bad_exit else 0


if __name__ == "__main__":
    sys.exit(main())
