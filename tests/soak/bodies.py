#!/usr/bin/env python3
"""Body memory soak: sends many big request bodies to one gateway worker and to a broker, and fails when RSS grows.

Usage: tests/soak/bodies.py [--seconds N] [--broker-seconds N] [--max-growth-mb M] [--server bun|http1]
       [--no-build] [--raiju PATH]

Every body over 64 KB reaches the gateway unread and is read by the body budget (src/bodybudget.tov readCharged).
Before re-audit 6 P0-A was fixed, each read raced a promise that never settled, which kept every chunk of every big
body alive: a 1 MB + 4 MB loop took a fresh worker from 20 to 836 MB in 100 s, and 200 KB chats from 20 to 557 MB in
30 s. This soak runs, after a warm-up:

1. gateway (--seconds, 60 by default): two loops of 1 MB and 4 MB chats and one loop of 200 KB chats, with a virtual
   key (checked bodies: the rate rules are on, as by default), plus one loop of 200 KB chats to an unauthenticated
   route with a body deadline (an unchecked body);
2. broker (--broker-seconds, 20 by default): signed 4 MB peer bodies to `raiju -mode broker` (read the same way, then
   refused for their body HMAC).

The RSS of each process is sampled every 2 s; its growth from the end of the warm-up to the end fails above
--max-growth-mb (40 by default). It builds build/raiju and build/soak_mock (tests/soak/mock.tov) and starts them on
SOAK_MOCK_PORT and SOAK_PORT (18320 and 18321, as tests/soak/soak.py) and the broker on SOAK_BROKER_PORT (18377): run
it under the e2e lock, as `flock /tmp/raiju-e2e.lock python3 tests/soak/bodies.py`. A summary line `bodies: ok ...` or
`bodies: FAIL ...` ends the output; the gateway's stderr is in build/soak-bodies.gateway.log.
"""
import argparse, hashlib, hmac, http.client, json, os, shutil, signal, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402  (build, rss_kb, wait_up)

ROOT = soak.ROOT
BUILD = soak.BUILD
MOCK_PORT = soak.MOCK_PORT
PORT = soak.PORT
BROKER_PORT = int(os.environ.get("SOAK_BROKER_PORT", "18377"))
KEY = "sk-bf-soak-" + "bodies-0123456789"
SECRET = "soak-bodies-" + "cluster-secret-0123456789abcdef"


def chat(total: int) -> bytes:
    """A chat request of exactly total bytes."""
    pre = b'{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"soak '
    post = b'"}]}'
    return pre + b"x" * (total - len(pre) - len(post)) + post


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.codes = {}
        self.errors = 0
        self.last_error = ""

    def add(self, code):
        with self.lock:
            self.codes[code] = self.codes.get(code, 0) + 1


def loop(port, path, bodies, headers, until, stats, want):
    """POSTs the bodies in turn on one keep-alive connection until `until`."""
    c = None
    i = 0
    while time.monotonic() < until:
        body = bodies[i % len(bodies)]
        i += 1
        try:
            if c is None:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            h = dict(headers(body) if callable(headers) else headers)
            h["content-type"] = "application/json"
            c.request("POST", path, body=body, headers=h)
            r = c.getresponse()
            r.read()
            stats.add(r.status)
            if r.status not in want:
                stats.last_error = "status %d on %s" % (r.status, path)
            if r.getheader("connection", "").lower() == "close":
                c.close()
                c = None
        except Exception as e:
            stats.errors += 1
            stats.last_error = repr(e)
            if c is not None:
                c.close()
            c = None
            time.sleep(0.05)
    if c is not None:
        c.close()


def peer_headers(body: bytes) -> dict:
    """A signed broker POST whose body HMAC is wrong: the broker reads the whole body, then refuses it (401)."""
    t = str(int(time.time() * 1000))
    head = hmac.new(SECRET.encode(), ("POST /api/cluster/broker %s %d" % (t, len(body))).encode(), hashlib.sha256).hexdigest()
    return {"x-raiju-cluster-sig": "0" * 64, "x-raiju-cluster-ts": t, "x-raiju-cluster-head": head}


def run(pid, jobs, seconds, label):
    """Runs the jobs (functions of `until`) for a warm-up, then for `seconds` while sampling the RSS of pid; the RSS
    after the warm-up, at the end and at its peak (KB)."""
    warm = max(5.0, seconds / 6)
    until = time.monotonic() + warm
    ts = [threading.Thread(target=j, args=(until,)) for j in jobs]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    time.sleep(1)
    before = soak.rss_kb(pid)
    print("bodies: %s after a %.0f s warm-up %.1f MB" % (label, warm, before / 1024), flush=True)
    until = time.monotonic() + seconds
    ts = [threading.Thread(target=j, args=(until,)) for j in jobs]
    for t in ts:
        t.start()
    samples = []
    start = time.monotonic()
    while any(t.is_alive() for t in ts):
        time.sleep(2)
        samples.append(soak.rss_kb(pid))
        if len(samples) % 5 == 0:
            print("bodies:   %s t=%3.0fs rss %.1f MB" % (label, time.monotonic() - start, samples[-1] / 1024), flush=True)
    for t in ts:
        t.join()
    time.sleep(1)
    after = soak.rss_kb(pid)
    return before, after, max(samples + [after])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=float(os.environ.get("SOAK_BODY_SECONDS", "60")))
    ap.add_argument("--broker-seconds", type=float, default=float(os.environ.get("SOAK_BROKER_SECONDS", "20")))
    ap.add_argument("--max-growth-mb", type=float, default=float(os.environ.get("SOAK_BODY_MAX_GROWTH_MB", "40")))
    ap.add_argument("--server", default=os.environ.get("RAIJU_SERVER", "bun"))
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--raiju", default="")
    a = ap.parse_args()
    if not a.no_build:
        soak.build()
    raiju = a.raiju or os.path.join(BUILD, "raiju")
    tmp = tempfile.mkdtemp(prefix="raiju-soak-bodies-")
    cfg = {
        "client": {"enable_logging": False, "enforce_auth_on_inference": True},
        "alerts": {"enabled": False},
        "governance": {"virtual_keys": [{"id": "vk-soak", "name": "vk-soak", "value": KEY}]},
        "providers": {"openai": {"keys": [{"name": "k1", "value": "sk-soak-" + "0123456789", "models": [], "weight": 1.0}],
                                 "network_config": {"base_url": "http://127.0.0.1:%d" % MOCK_PORT}}},
    }
    path = os.path.join(tmp, "config.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    bcfg = os.path.join(tmp, "broker.json")
    with open(bcfg, "w") as f:
        json.dump({"client": {"enable_logging": False}, "cluster": {"enabled": True, "secret": SECRET, "peers": [], "type": "broker",
                   "broker": {"address": "127.0.0.1:%d" % BROKER_PORT, "listen_port": BROKER_PORT}}}, f)
    mock = subprocess.Popen([os.path.join(BUILD, "soak_mock")], env={**os.environ, "MOCK_PORT": str(MOCK_PORT), "MOCK_WORKERS": "2"},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = open(os.path.join(BUILD, "soak-bodies.gateway.log"), "w")
    gw = subprocess.Popen([raiju, "-port", str(PORT), "-host", "127.0.0.1", "-config", path, "-server", a.server, "-workers", "1"],
                          stdout=subprocess.DEVNULL, stderr=log)
    broker = None
    failures = []
    try:
        soak.wait_up(MOCK_PORT)
        soak.wait_up(PORT)
        time.sleep(0.5)
        print("bodies: gateway start %.1f MB" % (soak.rss_kb(gw.pid) / 1024), flush=True)
        st = Stats()
        key = {"x-bf-vk": KEY}
        big = [chat(1048576), chat(4 * 1048576)]
        mid = [chat(200000)]
        jobs = [
            lambda until: loop(PORT, "/v1/chat/completions", big, key, until, st, (200,)),
            lambda until: loop(PORT, "/v1/chat/completions", big[::-1], key, until, st, (200,)),
            lambda until: loop(PORT, "/v1/chat/completions", mid, key, until, st, (200,)),
            # an unchecked body (no credential checked from the headers: the MCP route with no server here) with its deadline
            lambda until: loop(PORT, "/v1/mcp/soak/tools/call", mid, {}, until, st, (401, 403, 404)),
        ]
        t0 = time.monotonic()
        before, after, peak = run(gw.pid, jobs, a.seconds, "gateway")
        took = time.monotonic() - t0
        total = sum(st.codes.values())
        growth = (after - before) / 1024
        print("bodies: gateway %d requests in %.0f s: %s, %d errors%s" % (total, took, st.codes, st.errors, (" (last: %s)" % st.last_error) if st.last_error else ""))
        print("bodies: gateway rss %.1f MB -> %.1f MB (growth %+.1f MB, peak %.1f MB)" % (before / 1024, after / 1024, growth, peak / 1024))
        if growth > a.max_growth_mb:
            failures.append("the gateway's RSS grew %.1f MB (limit %.0f MB)" % (growth, a.max_growth_mb))
        if st.codes.get(200, 0) == 0 or st.errors > total * 0.01:
            failures.append("the gateway served %d of %d requests (%d errors)" % (st.codes.get(200, 0), total, st.errors))
        if gw.poll() is not None:
            failures.append("the gateway exited (%s)" % gw.returncode)

        broker = subprocess.Popen([raiju, "-mode", "broker", "-host", "127.0.0.1", "-config", bcfg], stdout=subprocess.DEVNULL, stderr=log)
        soak.wait_up(BROKER_PORT)
        time.sleep(0.5)
        print("bodies: broker start %.1f MB" % (soak.rss_kb(broker.pid) / 1024), flush=True)
        bs = Stats()
        payload = [b"a" * (4 * 1048576)]
        jobs = [lambda until: loop(BROKER_PORT, "/api/cluster/broker", payload, peer_headers, until, bs, (401,)) for _ in range(2)]
        before, after, peak = run(broker.pid, jobs, a.broker_seconds, "broker")
        total = sum(bs.codes.values())
        growth = (after - before) / 1024
        print("bodies: broker %d requests: %s, %d errors%s" % (total, bs.codes, bs.errors, (" (last: %s)" % bs.last_error) if bs.last_error else ""))
        print("bodies: broker rss %.1f MB -> %.1f MB (growth %+.1f MB, peak %.1f MB)" % (before / 1024, after / 1024, growth, peak / 1024))
        if growth > a.max_growth_mb:
            failures.append("the broker's RSS grew %.1f MB (limit %.0f MB)" % (growth, a.max_growth_mb))
        if bs.codes.get(401, 0) == 0 or bs.errors > total * 0.01:
            failures.append("the broker read %d of %d bodies (%d errors)" % (bs.codes.get(401, 0), total, bs.errors))
    finally:
        for p in (gw, broker, mock):
            if p is not None and p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print("bodies: FAIL: " + "; ".join(failures))
        sys.exit(1)
    print("bodies: ok")


if __name__ == "__main__":
    main()
