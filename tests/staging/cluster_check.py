#!/usr/bin/env python3
"""Cluster checks against every node of a deployed cluster (RAIJU_NODE_URLS, the nodes' main ports, reached from
inside the VPC): the cluster listener, config sync, cross-node log reads, shared rate-limit counters, and a watch
that follows a partition and the rejoin.

Usage: tests/staging/cluster_check.py listener|sync|logs|counters|watch|all [options]
  listener  each node's cluster port (RAIJU_CLUSTER_PORT, 7946) answers a signed GET /api/cluster/leader with its
            node id and refuses an unsigned or stale one (401); the main port and BASE_URL (the ALB) answer 404;
            exactly one node leads.
  sync      a virtual key created on node 1 appears on every node, an update made on node 2 and a delete made on
            the last node reach every node, each within --timeout seconds (the times are printed).
  logs      a chat sent to each node (x-request-id) is readable from every node at /api/logs/<id>.
  counters  a rate limit of --limit requests is shared: --limit requests spread over the nodes, --gap seconds
            apart, then one more on each node must be 429.
  watch     every --every seconds for --duration: each node's leader view; every --probe-every seconds a key
            written on one node must reach the others. Start it, cut a node off (security group), restore it; the
            check passes when at the end one node leads and a probe reaches every node.
Needs RAIJU_NODE_URLS (at least 2), RAIJU_ADMIN_TOKEN, RAIJU_CLUSTER_SECRET (and RAIJU_CLUSTER_URLS when the nodes'
cluster ports differ); logs and counters also RAIJU_VKS and
RAIJU_MODEL (a cheap model: one short chat per node, --limit + nodes for counters).
"""
import argparse
import os
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402


def leader_view(s, node_url, ts_ms=None, signed=True, main=False):
    """(status, body dict) of GET /api/cluster/leader on a node's cluster listener (main: on node_url itself)."""
    url = node_url if main else kit.cluster_url(s, node_url)
    h = kit.leader_headers(s.cluster_secret, ts_ms) if signed else {}
    st, _, b = kit.request("GET", url + "/api/cluster/leader", headers=h, timeout=10, ca_file=s.ca_file)
    return st, (kit.jload(b) or {}) if st == 200 else {}


def leaders_summary(rounds):
    """rounds: [{node_url: view dict or None}]. Counts rounds with no node answering, with not exactly one leader,
    and whether the last round has every node answering and one leader."""
    split = sum(1 for r in rounds if sum(1 for v in r.values() if v and v.get("leader")) != 1)
    dark = sum(1 for r in rounds if any(v is None for v in r.values()))
    last = rounds[-1] if rounds else {}
    converged = bool(last) and all(v is not None for v in last.values()) and sum(1 for v in last.values() if v.get("leader")) == 1
    return {"rounds": len(rounds), "rounds_not_one_leader": split, "rounds_node_unreachable": dark, "converged": converged}


def wait_until(fn, timeout, every=0.5):
    """Seconds until fn() is true, or None after timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return time.time() - t0
        time.sleep(every)
    return None


def listing(gw):
    st, _, b = gw.api("GET", "/api/governance/virtual-keys", timeout=15)
    return (kit.jload(b) or {}) if st == 200 else None


def check_listener(rep, s, nodes):
    ok, ids, leaders, rows = True, [], 0, []
    for u in nodes:
        st, v = leader_view(s, u)
        ust, _ = leader_view(s, u, signed=False)
        sst, _ = leader_view(s, u, ts_ms=int(time.time() * 1000) - 120000)
        mst, _ = leader_view(s, u, main=True)
        good = st == 200 and ust == 401 and sst == 401 and mst == 404
        ok = ok and good
        ids.append(v.get("node", "?"))
        leaders += 1 if v.get("leader") else 0
        rows.append(f"{u}: signed {st} node={v.get('node')} leader={v.get('leader')}, unsigned {ust}, stale {sst}, main port {mst}")
    alb = 0
    if s.base_url:
        alb, _ = leader_view(s, s.base_url, main=True)
        ok = ok and alb == 404
    ok = ok and leaders == 1 and len(set(ids)) == len(ids)
    rep.add("cluster.listener", ok, {"nodes": len(nodes), "leaders": leaders, "distinct_ids": len(set(ids)), "alb_status": alb}, "; ".join(rows))


def check_sync(rep, s, nodes, timeout):
    gws = [kit.Gateway(u, s) for u in nodes]
    prefix = "stg-" + kit.run_id() + "-sync"
    nums, ok = {}, True
    try:
        st, _, b = gws[0].api("POST", "/api/governance/virtual-keys", {"name": prefix, "description": "v1"})
        rid = (kit.jload(b) or {}).get("id", "")
        if st not in (200, 201) or not rid:
            return rep.add("cluster.sync", False, {"status": st}, "create failed: " + b[:200].decode("utf8", "replace"))

        def seen_on(g, pred):
            lst = listing(g)
            return lst is not None and pred(kit.vk_rows(lst, prefix))

        for i, g in enumerate(gws[1:], 2):
            t = wait_until(lambda: seen_on(g, lambda rows: len(rows) == 1), timeout)
            nums[f"create_node{i}_s"] = -1 if t is None else round(t, 2)
            ok = ok and t is not None
        upd = gws[1 % len(gws)]
        st, _, _ = upd.api("PUT", "/api/governance/virtual-keys/" + urllib.parse.quote(rid, safe=""), {"description": "v2"})
        ok = ok and st in (200, 201)
        for i, g in enumerate(gws, 1):
            t = wait_until(lambda: seen_on(g, lambda rows: rows and rows[0].get("description") == "v2"), timeout)
            nums[f"update_node{i}_s"] = -1 if t is None else round(t, 2)
            ok = ok and t is not None
        st, _, _ = gws[-1].api("DELETE", "/api/governance/virtual-keys/" + urllib.parse.quote(rid, safe=""))
        ok = ok and st in (200, 204)
        for i, g in enumerate(gws, 1):
            t = wait_until(lambda: seen_on(g, lambda rows: len(rows) == 0), timeout)
            nums[f"delete_node{i}_s"] = -1 if t is None else round(t, 2)
            ok = ok and t is not None
    finally:
        kit.cleanup_vks(gws[0], prefix)
    rep.add("cluster.sync", ok, nums, f"timeout {timeout} s")


def check_logs(rep, s, nodes, timeout):
    gws = [kit.Gateway(u, s) for u in nodes]
    rids = []
    for i, g in enumerate(gws):
        rid = f"stg-{kit.run_id()}-n{i + 1}"
        st, _, b = g.infer("/v1/chat/completions", {"model": s.model, "max_tokens": 4, "messages": [{"role": "user", "content": "Reply with: ok"}]}, headers={"x-request-id": rid})
        if st == 0:
            return rep.add("cluster.logs", False, {}, f"node {i + 1} did not answer: {b[:200]!r}")
        rids.append(rid)
    found, total, slowest = 0, 0, 0.0
    missing = []
    for j, g in enumerate(gws):
        for rid in rids:
            total += 1
            t = wait_until(lambda: g.api("GET", "/api/logs/" + urllib.parse.quote(rid, safe=""), timeout=15)[0] == 200, timeout)
            if t is None:
                missing.append(f"{rid} from node {j + 1}")
            else:
                found += 1
                slowest = max(slowest, t)
    rep.add("cluster.logs", found == total, {"rows_expected": total, "rows_found": found, "slowest_s": round(slowest, 2)}, "; ".join(missing[:6]))


def check_counters(rep, s, nodes, limit, gap):
    gws = [kit.Gateway(u, s) for u in nodes]
    prefix = "stg-" + kit.run_id() + "-rl"
    rl_id = prefix
    st, _, b = gws[0].api("POST", "/api/governance/rate-limits", {"id": rl_id, "request_max_limit": limit, "request_reset_duration": "1h"})
    if st not in (200, 201):
        return rep.add("cluster.counters", False, {"status": st}, "rate limit create failed: " + b[:200].decode("utf8", "replace"))
    try:
        st, _, b = gws[0].api("POST", "/api/governance/virtual-keys", {"name": prefix, "rate_limit_id": rl_id})
        vk = (kit.jload(b) or {}).get("value", "")
        if st not in (200, 201) or not vk:
            return rep.add("cluster.counters", False, {"status": st}, "virtual key create failed")
        time.sleep(max(3.0, gap))  # the key reaches every node
        body = {"model": s.model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
        admitted, codes = 0, {}
        for i in range(limit):
            st, _, _ = gws[i % len(gws)].infer("/v1/chat/completions", body, vk=vk)
            codes[st] = codes.get(st, 0) + 1
            admitted += st != 429
            time.sleep(gap)
        extra = []
        for g in gws:
            st, _, _ = g.infer("/v1/chat/completions", body, vk=vk)
            extra.append(st)
        ok = admitted == limit and all(st == 429 for st in extra)
        rep.add("cluster.counters", ok, {"limit": limit, "admitted": admitted, "extra_429": sum(1 for x in extra if x == 429), "nodes": len(gws)},
                f"codes {codes}; extra {extra}")
    finally:
        kit.cleanup_vks(gws[0], prefix)
        gws[0].api("DELETE", "/api/governance/rate-limits/" + urllib.parse.quote(rl_id, safe=""))


def check_watch(rep, s, nodes, duration, every, probe_every, timeout):
    gws = [kit.Gateway(u, s) for u in nodes]
    prefix = "stg-" + kit.run_id() + "-watch"
    rounds, probes, n = [], [], 0
    stop = time.time() + duration
    next_probe = time.time()
    try:
        while True:
            r = {}
            for u in nodes:
                st, v = leader_view(s, u)
                r[u] = v if st == 200 else None
            rounds.append(r)
            line = "  " + time.strftime("%H:%M:%S") + "  " + "  ".join(
                f"{i + 1}:{'down' if v is None else (v.get('node', '?') + ('*' if v.get('leader') else ''))}" for i, v in enumerate(r.values()))
            last = time.time() >= stop
            if time.time() >= next_probe or last:
                n += 1
                src = gws[(n - 1) % len(gws)]
                name = f"{prefix}{n}"
                st, _, _ = src.api("POST", "/api/governance/virtual-keys", {"name": name}, timeout=20)
                reached = 0
                if st in (200, 201):
                    for g in gws:
                        if wait_until(lambda: (lambda l: l is not None and kit.names_found(l, [name]) == [name])(listing(g)), timeout) is not None:
                            reached += 1
                probes.append((st, reached))
                line += f"  probe from node {(n - 1) % len(gws) + 1}: {st}, reached {reached}/{len(gws)}"
                next_probe = time.time() + probe_every
            rep.note(line)
            if last:
                break
            time.sleep(every)
    finally:
        kit.cleanup_vks(gws[0], prefix)
    summ = leaders_summary(rounds)
    final_probe = probes[-1] if probes else (0, 0)
    ok = summ["converged"] and final_probe[0] in (200, 201) and final_probe[1] == len(gws)
    summ.update({"probes": len(probes), "probes_reaching_all": sum(1 for st, r in probes if r == len(gws)), "final_probe_reached": final_probe[1]})
    rep.add("cluster.watch", ok, summ)


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("check", choices=["listener", "sync", "logs", "counters", "watch", "all"])
    ap.add_argument("--node-urls", help="comma-separated node URLs (RAIJU_NODE_URLS)")
    ap.add_argument("--cluster-secret", help="RAIJU_CLUSTER_SECRET")
    ap.add_argument("--cluster-port", type=int, help="RAIJU_CLUSTER_PORT (7946)")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--gap", type=float, default=2.0, help="seconds between the counted requests (above cluster.interval_ms)")
    ap.add_argument("--duration", default="10m")
    ap.add_argument("--every", type=float, default=5.0)
    ap.add_argument("--probe-every", type=float, default=30.0)
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    rep = kit.Report(s)
    nodes = s.node_urls
    if len(nodes) < 2 or not s.cluster_secret or not (s.admin_token or s.admin_user):
        rep.add("cluster." + a.check, False, {"nodes": len(nodes)}, "needs RAIJU_NODE_URLS (2 or more), RAIJU_CLUSTER_SECRET and RAIJU_ADMIN_TOKEN")
        return rep.exit_code()
    todo = ["listener", "sync", "logs", "counters"] if a.check == "all" else [a.check]
    for c in todo:
        if c == "listener":
            check_listener(rep, s, nodes)
        elif c == "sync":
            check_sync(rep, s, nodes, a.timeout)
        elif c == "logs":
            check_logs(rep, s, nodes, a.timeout)
        elif c == "counters":
            check_counters(rep, s, nodes, a.limit, a.gap)
        elif c == "watch":
            check_watch(rep, s, nodes, kit.parse_duration(a.duration), a.every, a.probe_every, a.timeout)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
