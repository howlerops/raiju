#!/usr/bin/env python3
"""Slow and silent clients against a gateway (production audit P1-4): opens N connections that send nothing,
N that send a request head one byte every few seconds and N that keep a body trickling, waits, and counts how many
the gateway still holds. Passes when at most --max-open of them are open after --wait seconds.

Usage: bench/slowloris.py [--bin build/raiju] [--server bun|http1] [--port 18323] [--conns 100] [--wait 15]
                          [--max-open 0]
Run it through the e2e lock on a shared machine: flock /tmp/raiju-e2e.lock python3 bench/slowloris.py
With the defaults (header_timeout_seconds 10, body_timeout_seconds 60) a silent or slow-head connection is closed
after about 10 s; the body tricklers send a byte every 2 s, so they are only cut by --body-timeout (set here to 5 s).
"""
import argparse, json, os, resource, socket, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=os.path.join(ROOT, "build", "raiju"))
    ap.add_argument("--server", default=os.environ.get("RAIJU_SERVER", "bun"))
    ap.add_argument("--port", type=int, default=18323)
    ap.add_argument("--conns", type=int, default=100, help="connections of each kind")
    ap.add_argument("--wait", type=float, default=15.0)
    ap.add_argument("--max-open", type=int, default=0)
    ap.add_argument("--body-timeout", type=float, default=5.0)
    a = ap.parse_args()
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, min(hard, 4096)), hard))
    d = tempfile.mkdtemp(prefix="raiju-slowloris-")
    cfg = os.path.join(d, "config.json")
    # the body timeout is shortened so a body that keeps trickling (a byte every 2 s) is still cut by the inactivity rule
    # only when it stalls; a head is bounded by the header timeout however it trickles
    json.dump({"client": {"enable_logging": False}, "alerts": {"enabled": False}, "pricing_sync": {"enabled": False},
               "server": {"body_timeout_seconds": a.body_timeout}, "providers": {}}, open(cfg, "w"))
    gw = subprocess.Popen([a.bin, "-port", str(a.port), "-host", "127.0.0.1", "-config", cfg, "-server", a.server],
                          stderr=open(os.path.join(d, "gateway.log"), "w"))
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", a.port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        silent, heads, bodies = [], [], []
        for _ in range(a.conns):
            silent.append(socket.create_connection(("127.0.0.1", a.port), timeout=5))
            h = socket.create_connection(("127.0.0.1", a.port), timeout=5)
            h.sendall(b"GET /health HTTP/1.1\r\n")
            heads.append(h)
            b = socket.create_connection(("127.0.0.1", a.port), timeout=5)
            b.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 100000\r\n\r\n{")
            bodies.append(b)
        t0 = time.time()
        while time.time() - t0 < a.wait:
            # the slow heads send one more header byte, the bodies stall after their first byte
            for h in heads:
                try:
                    h.sendall(b"X")
                except OSError:
                    pass
            time.sleep(2.0)

        def still_open(socks):
            n = 0
            for s in socks:
                s.setblocking(False)
                try:
                    got = s.recv(4096)
                    if got and not got.startswith(b"HTTP/1.1 408"):
                        n += 1   # an answer other than the timeout, and the connection still up
                except BlockingIOError:
                    n += 1       # nothing to read: still open
                except OSError:
                    pass
            return n

        o_silent, o_heads, o_bodies = still_open(silent), still_open(heads), still_open(bodies)
        total = o_silent + o_heads + o_bodies
        alive = gw.poll() is None
        try:
            socket.create_connection(("127.0.0.1", a.port), timeout=2).close()
            serving = True
        except OSError:
            serving = False
        print(f"after {a.wait:.0f} s: {o_silent}/{a.conns} silent, {o_heads}/{a.conns} slow-head, {o_bodies}/{a.conns} stalled-body connections still open ({total} in all); gateway {'up' if alive and serving else 'DOWN'}")
        ok = total <= a.max_open and alive and serving
        print("PASS" if ok else f"FAIL (more than {a.max_open} still open)")
        return 0 if ok else 1
    finally:
        gw.terminate()
        try:
            gw.wait(10)
        except subprocess.TimeoutExpired:
            gw.kill()


if __name__ == "__main__":
    sys.exit(main())
