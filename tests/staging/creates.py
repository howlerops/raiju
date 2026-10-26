#!/usr/bin/env python3
"""Concurrent creates and lost updates (production re-audits 1-5: "40/40 creates"): --creates virtual keys created at
once, spread round-robin over one or more gateway URLs, then one concurrent update of each, then every URL is read
back. Every create and update the gateway acknowledged (201 / 200) must be there on every URL: none lost.

Several URLs: give every node of a cluster (--url per node, or --all-nodes for RAIJU_NODE_URLS), or an old and a new
release on one volume during an upgrade (tests/staging/bridge.py does that in rounds). Each URL is read back after
--settle seconds, so the nodes must apply each other's saves (a cluster sharing config.json, config_sync "file"):
nodes that are not one cluster, or that keep their own files ("pull"), lose concurrent saves by design (docs/
operations.md, One writer). --read-url limits the reads; --config-file counts the keys in config.json itself when
the shared volume is mounted where this runs.

Usage: tests/staging/creates.py [--base-url URL | --url A --url B ...] [--creates 40] [--settle 3] [--rounds 1]
                                [--max-refused 0] [--keep]
Needs RAIJU_ADMIN_TOKEN (or RAIJU_ADMIN_USER / RAIJU_ADMIN_PASSWORD). The keys are named stg-<run>-<n> and deleted
at the end unless --keep. 503 (lock wait timed out) is allowed up to --max-refused per round; anything acknowledged
and then missing fails.
"""
import argparse
import os
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402


def verdict(acked, found_by_url, updated, upd_found_by_url, refused, max_refused):
    """(ok, numbers): acked names and updated ids must all be found on every URL; refused (5xx) at most max_refused."""
    lost = max((len(set(acked) - set(f)) for f in found_by_url.values()), default=0)
    lost_upd = max((len(set(updated) - set(f)) for f in upd_found_by_url.values()), default=0)
    ok = lost == 0 and lost_upd == 0 and refused <= max_refused and len(acked) > 0
    return ok, {"acknowledged": len(acked), "refused": refused, "lost": lost, "updated": len(updated), "lost_updates": lost_upd}


def names_in_file(path, names, prefix):
    """The names among `names` in a config.json on a mounted volume, and the ids of updated keys there."""
    import json
    with open(path) as f:
        cfg = json.load(f)
    listing = {"virtual_keys": (cfg.get("governance") or {}).get("virtual_keys") or []}
    rows = kit.vk_rows(listing, prefix)
    return kit.names_found(listing, names), [r.get("id") for r in rows if str(r.get("description", "")).startswith("updated ")]


def one_round(rep, s, urls, n, settle, max_refused, label, prefix, read_urls=None, config_file=""):
    gws = [kit.Gateway(u, s) for u in urls]
    for g in gws:
        g.admin_headers()  # sign in once, before the burst
    codes, lat, acked, ids = {}, [], [], {}
    lock = threading.Lock()

    def create(i):
        g = gws[i % len(gws)]
        name = f"{prefix}{i}"
        t0 = time.time()
        st, _, b = g.api("POST", "/api/governance/virtual-keys", {"name": name, "description": "staging create check"})
        with lock:
            lat.append(time.time() - t0)
            codes[st] = codes.get(st, 0) + 1
            if st in (200, 201):
                acked.append(name)
                rid = (kit.jload(b) or {}).get("id")
                if rid:
                    ids[name] = rid

    ts = [threading.Thread(target=create, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)

    # one concurrent update of each acknowledged key, through another URL than the one that made it
    updated, ucodes = [], {}

    def update(j, name, rid):
        g = gws[(j + 1) % len(gws)]
        st, _, _ = g.api("PUT", "/api/governance/virtual-keys/" + urllib.parse.quote(str(rid), safe=""), {"description": "updated " + name})
        with lock:
            ucodes[st] = ucodes.get(st, 0) + 1
            if st in (200, 201):
                updated.append(rid)

    ts = [threading.Thread(target=update, args=(j, name, rid)) for j, (name, rid) in enumerate(ids.items())]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)
    time.sleep(settle)

    found, ufound = {}, {}
    for g in [kit.Gateway(u, s) for u in (read_urls or urls)]:
        st, _, b = g.api("GET", "/api/governance/virtual-keys")
        listing = kit.jload(b) or {}
        found[g.base] = kit.names_found(listing, acked) if st == 200 else []
        rows = kit.vk_rows(listing, prefix)
        ufound[g.base] = [r.get("id") for r in rows if str(r.get("description", "")).startswith("updated ")]
    if config_file:
        found["file"], ufound["file"] = names_in_file(config_file, acked, prefix)
    refused = sum(v for k, v in codes.items() if k >= 500 or k == 0) + sum(v for k, v in ucodes.items() if k >= 500 or k == 0)
    ok, nums = verdict(acked, found, updated, ufound, refused, max_refused)
    nums.update({"creates": n, "urls": len(urls), "p50_s": kit.percentile(lat, 50), "max_s": max(lat) if lat else 0})
    detail = "create codes " + ", ".join(f"{k}x{v}" for k, v in sorted(codes.items())) + "; update codes " + ", ".join(f"{k}x{v}" for k, v in sorted(ucodes.items()))
    rep.add(label, ok, nums, detail)
    return ok


def run(rep, s, urls, creates, settle, rounds, max_refused, keep, label="creates", read_urls=None, config_file=""):
    if not (s.admin_token or s.admin_user):
        return rep.add(label, False, {}, "no RAIJU_ADMIN_TOKEN")
    if not urls:
        return rep.add(label, False, {}, "no URL")
    prefix = "stg-" + kit.run_id() + "-"
    ok = True
    try:
        for r in range(rounds):
            name = label if rounds == 1 else f"{label}.round{r + 1}"
            ok = one_round(rep, s, urls, creates, settle, max_refused, name, f"{prefix}{r}-", read_urls, config_file) and ok
    finally:
        if not keep:
            n = kit.cleanup_vks(kit.Gateway(urls[0], s), prefix)
            rep.note(f"cleanup: deleted {n} staging keys ({prefix}*)")
    return ok


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--url", action="append", default=[], help="a gateway URL (repeat; default the base URL)")
    ap.add_argument("--all-nodes", action="store_true", help="use every RAIJU_NODE_URLS entry")
    ap.add_argument("--creates", type=int, default=40)
    ap.add_argument("--settle", type=float, default=3.0, help="seconds between the writes and the reads (cluster sync)")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--max-refused", type=int, default=0, help="5xx answers allowed per round (nothing acknowledged may be lost)")
    ap.add_argument("--read-url", action="append", default=[], help="read back from these URLs only (default: every --url)")
    ap.add_argument("--config-file", default="", help="also count the keys in this config.json (the shared volume mounted here)")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    urls = [kit.norm_url(u) for u in a.url] or (s.node_urls if a.all_nodes else [s.base_url] if s.base_url else [])
    rep = kit.Report(s)
    run(rep, s, urls, a.creates, a.settle, a.rounds, a.max_refused, a.keep, read_urls=[kit.norm_url(u) for u in a.read_url], config_file=a.config_file)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
