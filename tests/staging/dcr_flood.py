#!/usr/bin/env python3
"""MCP OAuth dynamic client registration flood (re-audit 3 P1-B, re-audit 4 P1-F): --conns clients register at
/oauth2/register for --seconds, half of them with forged X-Forwarded-For values. Behind the ALB with
RAIJU_TRUSTED_PROXIES the gateway counts them all as this one address, so they must get 429 after the per-address
allowance (10 a minute by default), forged headers included; /health must stay fast meanwhile; and a client that
registered before the flood must still reach the consent page at /oauth2/authorize.

Usage: tests/staging/dcr_flood.py [--seconds 30] [--conns 32] [--max-health-ms 500]
Needs client.mcp_server_auth_mode "both" or "oauth" on the gateway (404 at /oauth2/register: SKIP). Sends no
credential: this is what anyone on the internet can do.
"""
import argparse
import base64
import collections
import hashlib
import os
import random
import sys
import threading
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402

REDIRECT = "http://127.0.0.1:8080/cb"  # a loopback callback: registered, never called


def health_latencies(gw, n, out):
    for _ in range(n):
        t0 = time.time()
        st, _, _ = gw.get("/health", timeout=10)
        out.append((time.time() - t0) * 1000.0 if st == 200 else None)
        time.sleep(0.05)


def forged_xff(rng):
    return f"{rng.randint(1, 223)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


def verdict(codes, forged_codes, during, max_health_ms, authorize_status, max_created=20):
    lat = [v for v in during if v is not None]
    failed = sum(1 for v in during if v is None)
    p99 = kit.percentile(lat, 99)
    limited = codes.get(429, 0) > 0
    # forged X-Forwarded-For must not buy a fresh allowance: everything counts as this one address (the gateway
    # believes only the ALB's own entry), so the whole flood gets about one address's allowance
    forged_created = forged_codes.get(201, 0)
    ok = limited and failed == 0 and (p99 == p99 and p99 <= max_health_ms) and authorize_status == 302 and codes.get(201, 0) <= max_created
    return ok, {"registered_201": codes.get(201, 0), "limited_429": codes.get(429, 0), "forged_xff_201": forged_created,
                "health_p50_ms": round(kit.percentile(lat, 50), 1), "health_p99_ms": round(p99, 1), "health_failed": failed,
                "authorize_status": authorize_status}


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--conns", type=int, default=32)
    ap.add_argument("--max-health-ms", type=float, default=500.0)
    ap.add_argument("--max-created", type=int, default=20, help="registrations allowed to succeed in the flood (one address's allowance)")
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    rep = kit.Report(s)
    if not s.base_url:
        rep.add("dcr_flood", False, {}, "no RAIJU_BASE_URL")
        return rep.exit_code()
    gw = kit.Gateway(s.base_url, s)
    reg = {"client_name": "staging-dcr-check", "redirect_uris": [REDIRECT]}
    st, _, b = kit.request("POST", gw.base + "/oauth2/register", reg, timeout=15, ca_file=s.ca_file)
    if st == 404:
        rep.add("dcr_flood", None, {"status": st}, "MCP OAuth is off (client.mcp_server_auth_mode)")
        return rep.exit_code()
    cid = (kit.jload(b) or {}).get("client_id", "") if st == 201 else ""
    if not cid:
        rep.add("dcr_flood", False, {"status": st}, "the first registration failed: " + b[:200].decode("utf8", "replace"))
        return rep.exit_code()
    base_lat = []
    health_latencies(gw, 40, base_lat)
    stop = time.time() + a.seconds
    codes, forged, lock = collections.Counter(), collections.Counter(), threading.Lock()

    def flood(i):
        rng = random.Random(i)
        while time.time() < stop:
            h = {"x-forwarded-for": forged_xff(rng)} if i % 2 else {}
            st, _, _ = kit.request("POST", gw.base + "/oauth2/register", reg, headers=h, timeout=15, ca_file=s.ca_file)
            with lock:
                codes[st] += 1
                if i % 2:
                    forged[st] += 1

    ts = [threading.Thread(target=flood, args=(i,), daemon=True) for i in range(a.conns)]
    for t in ts:
        t.start()
    time.sleep(min(3.0, a.seconds / 3))
    during = []
    health_latencies(gw, 60, during)
    for t in ts:
        t.join(a.seconds + 30)
    # the client registered before the flood still reaches the consent page
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    q = urllib.parse.urlencode({"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "state": "staging",
                                "code_challenge": challenge, "code_challenge_method": "S256", "scope": "mcp"})
    ast, _, _ = kit.request("GET", gw.base + "/oauth2/authorize?" + q, timeout=15, ca_file=s.ca_file)
    ok, nums = verdict(codes, forged, during, a.max_health_ms, ast, a.max_created)
    nums["baseline_health_p99_ms"] = round(kit.percentile([v for v in base_lat if v is not None], 99), 1)
    rep.add("dcr_flood", ok, nums, "codes " + ", ".join(f"{k}x{v}" for k, v in sorted(codes.items())))
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
