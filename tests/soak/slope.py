#!/usr/bin/env python3
"""Slope soak: drives one gateway worker with small chats as fast as it answers and fails when its RSS keeps growing
per request.

Usage: tests/soak/slope.py [--seconds N] [--warmup N] [--max-slope B] [--server bun|http1|both] [--clients N]
       [--no-build] [--raiju PATH]

A leak of a few dozen bytes a request hides in a short soak's noise but grows without end: before re-audit 7 P0-1
was fixed, every inference request with a virtual key left one header string behind (the compiler's `continue` did
not release the loop body's locals, tov-patches/0023), about 50 bytes of RSS a request: 23 to 92 MB over 1.47M
small chats. This soak measures that slope directly.

For each server (bun and http1 by default, one after the other) it starts the gateway with a virtual key required on
inference, the request log on and the log store on with content logging (a small in-memory ring, which the warm-up
fills), then:

1. warm-up (--warmup seconds, 15 by default): the full mix, so allocator pools, caches and the log ring settle;
2. soak (--seconds, 75 by default): --clients keep-alive connections (12 by default, from 3 processes) loop small
   chats: plain and streamed, the key in x-bf-vk or in Authorization, some with an x-bf-eh- header to forward.

The RSS and the number of answered requests are sampled every 2 s; the least-squares slope of RSS against requests
over the soak, in bytes per request, fails above --max-slope (10 by default; a settled heap measures about 0 to 2,
the leak above about 50). About 200k to 300k requests per server on a CI runner.

It builds build/raiju and build/soak_mock (tests/soak/mock.tov) and starts them on SOAK_SLOPE_PORT and
SOAK_SLOPE_MOCK_PORT (18388 and 18389); run it under the e2e lock on a shared machine, as
`flock /tmp/raiju-e2e.lock python3 tests/soak/slope.py`. A summary line `slope: ok ...` or `slope: FAIL ...` ends the
output; the gateway's stderr is in build/soak-slope.<server>.gateway.log.
"""
import argparse, http.client, json, multiprocessing, os, shutil, signal, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402  (build, rss_kb, wait_up)

BUILD = soak.BUILD
PORT = int(os.environ.get("SOAK_SLOPE_PORT", "18388"))
MOCK_PORT = int(os.environ.get("SOAK_SLOPE_MOCK_PORT", "18389"))
KEY = "sk-bf-soak-" + "slope-0123456789"

PLAIN = json.dumps({"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hello there"}]}).encode()
STREAM = json.dumps({"model": "openai/gpt-4o-mini", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode()


def client(idx, until, count, errors):
    """One keep-alive connection looping the mix until `until` (wall clock); counts answered requests."""
    c = None
    n = 0
    local_ok = 0
    local_err = 0
    while time.time() < until:
        n += 1
        h = {"content-type": "application/json"}
        if (n + idx) % 3 == 0:
            h["authorization"] = "Bearer " + KEY
        else:
            h["x-bf-vk"] = KEY
        if n % 5 == 0:
            h["x-bf-eh-x-soak-trace"] = "t" + str(n)
        body = STREAM if n % 4 == 0 else PLAIN
        try:
            if c is None:
                c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=30)
            c.request("POST", "/v1/chat/completions", body=body, headers=h)
            r = c.getresponse()
            data = r.read()
            if r.status == 200 and (body is PLAIN or b"[DONE]" in data):
                local_ok += 1
            else:
                local_err += 1
            if (r.getheader("connection") or "").lower() == "close":
                c.close()
                c = None
        except Exception:
            local_err += 1
            if c is not None:
                c.close()
            c = None
            time.sleep(0.05)
        if local_ok + local_err >= 50:
            with count.get_lock():
                count.value += local_ok
            with errors.get_lock():
                errors.value += local_err
            local_ok = 0
            local_err = 0
    with count.get_lock():
        count.value += local_ok
    with errors.get_lock():
        errors.value += local_err
    if c is not None:
        c.close()


def worker(first, n, until, count, errors):
    ts = [threading.Thread(target=client, args=(first + i, until, count, errors), daemon=True) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


def drive(seconds, clients, count, errors):
    """Starts the clients (3 processes of threads) for `seconds`; returns the processes to join."""
    until = time.time() + seconds
    procs = []
    per = max(1, clients // 3)
    first = 0
    while first < clients:
        n = min(per, clients - first)
        p = multiprocessing.Process(target=worker, args=(first, n, until, count, errors), daemon=True)
        p.start()
        procs.append(p)
        first += n
    return procs


def slope_b_per_req(samples):
    """Least-squares slope of RSS (KB) against requests, in bytes per request."""
    n = len(samples)
    if n < 3:
        return 0.0
    mx = sum(s[0] for s in samples) / n
    my = sum(s[1] for s in samples) / n
    den = sum((s[0] - mx) ** 2 for s in samples)
    if den <= 0:
        return 0.0
    return sum((s[0] - mx) * (s[1] - my) for s in samples) / den * 1024


def run_server(a, server, tmp):
    cfg = {
        "client": {"enable_logging": True, "enforce_auth_on_inference": True},
        "governance": {"virtual_keys": [{"id": "vk-soak", "name": "soak", "value": KEY}]},
        # (a small ring, so the warm-up fills it: its entries are not growth)
        "logs_store": {"enabled": True, "dir": os.path.join(tmp, "logs-" + server), "max_memory_entries": 2000, "content_logging": True},
        "providers": {"openai": {"keys": [{"name": "k1", "value": "sk-soak-" + "0123456789", "models": [], "weight": 1.0}],
                                 "network_config": {"base_url": f"http://127.0.0.1:{MOCK_PORT}"}}},
    }
    path = os.path.join(tmp, f"config-{server}.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    log = open(os.path.join(BUILD, f"soak-slope.{server}.gateway.log"), "w")
    gw = subprocess.Popen([a.raiju or os.path.join(BUILD, "raiju"), "-port", str(PORT), "-host", "127.0.0.1", "-workers", "1",
                           "-config", path, "-server", server], stdout=subprocess.DEVNULL, stderr=log)
    failures = []
    try:
        soak.wait_up(PORT)
        time.sleep(0.5)
        count = multiprocessing.Value("q", 0)
        errors = multiprocessing.Value("q", 0)
        for p in drive(a.warmup, a.clients, count, errors):
            p.join(a.warmup + 60)
        warm_n = count.value
        start_kb = soak.rss_kb(gw.pid)
        print(f"slope[{server}]: after {a.warmup:.0f} s warm-up ({warm_n} requests) rss {start_kb / 1024:.1f} MB", flush=True)
        count.value = 0
        errors.value = 0
        samples = [(0, start_kb)]
        t0 = time.monotonic()
        procs = drive(a.seconds, a.clients, count, errors)
        while time.monotonic() - t0 < a.seconds:
            time.sleep(2)
            samples.append((count.value, soak.rss_kb(gw.pid)))
            if len(samples) % 10 == 0:
                print(f"slope[{server}]:   t={time.monotonic() - t0:4.0f}s {samples[-1][0]} requests rss {samples[-1][1] / 1024:.1f} MB", flush=True)
        for p in procs:
            p.join(60)
        took = time.monotonic() - t0
        total = count.value
        bad = errors.value
        s = slope_b_per_req(samples)
        end_kb = soak.rss_kb(gw.pid)
        print(f"slope[{server}]: {total} requests in {took:.0f} s ({total / max(1.0, took):.0f}/s), {bad} failed; rss {start_kb / 1024:.1f} -> "
              f"{end_kb / 1024:.1f} MB; slope {s:.1f} B/request (limit {a.max_slope:.0f})", flush=True)
        if s > a.max_slope:
            failures.append(f"{server}: RSS grew {s:.1f} B per request over {total} requests (limit {a.max_slope:.0f})")
        if total < 1000 or bad > (total + bad) * 0.01:
            failures.append(f"{server}: {bad} of {total + bad} requests failed")
        if gw.poll() is not None:
            failures.append(f"{server}: the gateway exited ({gw.returncode})")
    finally:
        if gw.poll() is None:
            gw.send_signal(signal.SIGTERM)
            try:
                gw.wait(10)
            except subprocess.TimeoutExpired:
                gw.kill()
                gw.wait()
        log.close()
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=float(os.environ.get("SOAK_SLOPE_SECONDS", "75")))
    ap.add_argument("--warmup", type=float, default=float(os.environ.get("SOAK_SLOPE_WARMUP", "15")))
    ap.add_argument("--max-slope", type=float, default=float(os.environ.get("SOAK_SLOPE_MAX_B", "10")))
    ap.add_argument("--clients", type=int, default=int(os.environ.get("SOAK_SLOPE_CLIENTS", "12")))
    ap.add_argument("--server", default=os.environ.get("SOAK_SLOPE_SERVER", "both"))
    ap.add_argument("--no-build", action="store_true")
    # another gateway binary (an older build, to compare); implies --no-build for the gateway
    ap.add_argument("--raiju", default="")
    a = ap.parse_args()
    if not a.no_build:
        soak.build()
    servers = ["bun", "http1"] if a.server == "both" else [a.server]
    tmp = tempfile.mkdtemp(prefix="raiju-slope-")
    mock = subprocess.Popen([os.path.join(BUILD, "soak_mock")], env={**os.environ, "MOCK_PORT": str(MOCK_PORT), "MOCK_WORKERS": "2"},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures = []
    try:
        soak.wait_up(MOCK_PORT)
        for server in servers:
            failures += run_server(a, server, tmp)
    finally:
        if mock.poll() is None:
            mock.send_signal(signal.SIGTERM)
            try:
                mock.wait(5)
            except subprocess.TimeoutExpired:
                mock.kill()
                mock.wait()
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print("slope: FAIL: " + "; ".join(failures))
        sys.exit(1)
    print("slope: ok")


if __name__ == "__main__":
    main()
