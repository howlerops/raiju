#!/usr/bin/env python3
"""Metric label cardinality under unauthenticated junk (the production audit's P0-4).

Starts a gateway with no admin and inference open, sends N requests with made-up paths (plain, under /api and under a
provider route) and made-up model names to a provider whose upstream refuses connections, then measures /metrics and
the gateway's RSS. Fails when /metrics or the RSS growth passes the thresholds.

Usage: bench/metrics_cardinality.py [binary]   (default build/raiju; run it through flock /tmp/raiju-e2e.lock)
Env: N (requests, default 10000), PORT (default 18324), MAX_METRICS_MB (default 2), MAX_RSS_GROWTH_MB (default 40).
"""
import json, os, random, string, subprocess, sys, tempfile, threading, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "raiju")
N = int(os.environ.get("N", "10000"))
PORT = int(os.environ.get("PORT", "18324"))
MAX_METRICS_MB = float(os.environ.get("MAX_METRICS_MB", "2"))
MAX_RSS_GROWTH_MB = float(os.environ.get("MAX_RSS_GROWTH_MB", "40"))
GW = f"http://127.0.0.1:{PORT}"


def junk(n=10):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def send(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(GW + path, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return 0, b""


def rss_mb(pid):
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    return 0.0


def worker(count):
    for _ in range(count):
        kind = random.randrange(4)
        if kind == 0:
            send("GET", "/" + junk())
        elif kind == 1:
            send("GET", "/api/" + junk())
        elif kind == 2:
            send("POST", "/genai/v1beta/models/" + junk() + ":generateContent", {"contents": [{"parts": [{"text": "x"}]}]})
        else:
            send("POST", "/v1/chat/completions", {"model": "openai/" + junk(), "messages": [{"role": "user", "content": "x"}]})


def main():
    d = tempfile.mkdtemp(prefix="raiju-cardinality-")
    cfg = os.path.join(d, "config.json")
    # the upstream is a closed local port, so every request fails at once with its model in the labels
    json.dump({"client": {"enable_logging": False, "enforce_auth_on_inference": False},
               "pricing_sync": {"url": "http://127.0.0.1:9/none", "enabled": False},
               "providers": {"openai": {"keys": [{"name": "k", "value": "sk-cardinality", "models": [], "weight": 1.0}],
                                        "network_config": {"base_url": "http://127.0.0.1:9", "max_retries": 0}},
                             "gemini": {"keys": [{"name": "g", "value": "g-cardinality", "models": [], "weight": 1.0}],
                                        "network_config": {"base_url": "http://127.0.0.1:9", "max_retries": 0}}}}, open(cfg, "w"))
    env = {k: v for k, v in os.environ.items() if k != "BIFROST_SETUP_TOKEN"}
    gw = subprocess.Popen([BIN, "-port", str(PORT), "-host", "127.0.0.1", "-config", cfg], env=env, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if send("GET", "/health")[0] == 200:
                break
            time.sleep(0.05)
        before = rss_mb(gw.pid)
        t0 = time.time()
        threads = [threading.Thread(target=worker, args=(N // 8,)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        took = time.time() - t0
        _, body = send("GET", "/metrics")
        after = rss_mb(gw.pid)
    finally:
        gw.terminate()
        gw.wait()
    metrics_mb = len(body) / 1048576.0
    lines = body.count(b"\n")
    growth = after - before
    print(f"requests: {N // 8 * 8} in {took:.1f} s")
    print(f"/metrics: {metrics_mb:.2f} MB, {lines} lines (limit {MAX_METRICS_MB} MB)")
    print(f"RSS: {before:.1f} MB -> {after:.1f} MB, growth {growth:.1f} MB (limit {MAX_RSS_GROWTH_MB} MB)")
    ok = metrics_mb <= MAX_METRICS_MB and growth <= MAX_RSS_GROWTH_MB
    print("metrics-cardinality: " + ("ok" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
