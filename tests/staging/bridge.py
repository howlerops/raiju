#!/usr/bin/env python3
"""Mixed versions on one volume (re-audit 3 P1-C, re-audit 4 "wave 25/27 + 28 bridges 40/40"): during a rolling
upgrade an old and a new release write one config.json. Creates go to both at once, half each, for --rounds rounds,
and every acknowledged key must be on both afterwards (tests/staging/creates.py does the work).

Usage: tests/staging/bridge.py --old-url URL --new-url URL [--creates 40] [--rounds 3] [--settle 3]
Point --old-url and --new-url at tasks of the two task definitions (their private addresses inside the VPC, or two
target groups); RAIJU_ADMIN_TOKEN must be valid on both.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import creates  # noqa: E402
import kit  # noqa: E402


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--old-url", required=True)
    ap.add_argument("--new-url", required=True)
    ap.add_argument("--creates", type=int, default=40)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--settle", type=float, default=3.0)
    ap.add_argument("--max-refused", type=int, default=0)
    ap.add_argument("--config-file", default="", help="also count the keys in config.json on the shared volume, mounted here")
    ap.add_argument("--read-url", action="append", default=[], help="read back from these URLs only (default both)")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    rep = kit.Report(s)
    urls = [kit.norm_url(a.old_url), kit.norm_url(a.new_url)]
    for u in urls:
        st, _, b = kit.Gateway(u, s).api("GET", "/api/version", timeout=10)
        rep.note(f"{u}: /api/version {st} {b[:40].decode('utf8', 'replace')}")
    creates.run(rep, s, urls, a.creates, a.settle, a.rounds, a.max_refused, a.keep, label="bridge",
                read_urls=[kit.norm_url(u) for u in a.read_url], config_file=a.config_file)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
