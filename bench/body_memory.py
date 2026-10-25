#!/usr/bin/env python3
"""Request bodies and a worker's memory (production re-audit P0-2): sends big bodies at once and reads the gateway's
peak RSS (VmHWM).

1. Unauthenticated: --conns POSTs of --size-mb each to /v1/chat/completions with auth enforced and no virtual key.
   Each must be refused with 401 from its headers, unread, and the peak RSS must stay under --max-rss-mb.
2. Authenticated: --auth-conns chat requests of --auth-size-mb each with the key, against a slow upstream (it holds
   each answer --hold seconds). The bodies past server.max_buffered_body_mb (default 48) must be refused with 503, the
   rest served, and the peak RSS must stay under --max-auth-rss-mb (sized for the chart's 512Mi pod).

Usage: bench/body_memory.py [--bin build/raiju] [--server bun|http1] [--port 18349] [--upstream-port 18348]
                            [--conns 6] [--size-mb 90] [--max-rss-mb 128]
                            [--auth-conns 12] [--auth-size-mb 16] [--max-auth-rss-mb 448] [--cap-mb 0]
Run it through the e2e lock on a shared machine: flock /tmp/raiju-e2e.lock python3 bench/body_memory.py
Build the gateway with TOV_CFLAGS=-DTV_PLAIN_ALLOC (make build does).
"""
import argparse, http.client, http.server, json, os, socket, subprocess, sys, tempfile, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "sk-bf-" + "bench-body-memory"


def vm(pid, key):
    for line in open(f"/proc/{pid}/status"):
        if line.startswith(key + ":"):
            return int(line.split()[1]) // 1024
    return 0


def post(port, body, headers, out, i):
    """One POST; its status, or 0 when the connection was cut before an answer could be read."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    try:
        conn.putrequest("POST", "/v1/chat/completions")
        conn.putheader("content-type", "application/json")
        conn.putheader("content-length", str(len(body)))
        for k, v in headers.items():
            conn.putheader(k, v)
        conn.endheaders()
        view = memoryview(body)
        try:
            for off in range(0, len(body), 1 << 20):
                conn.send(view[off:off + (1 << 20)])
        except OSError:
            pass  # a server that refuses a body unread may close before it is all out
        out[i] = conn.getresponse().status
    except Exception:
        out[i] = 0
    finally:
        conn.close()


def burst(port, n, body, headers):
    out = [0] * n
    ts = [threading.Thread(target=post, args=(port, body, headers, out, i)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return out


def chat_body(size):
    pre = b'{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"'
    post_ = b'"}]}'
    return pre + b"a" * (size - len(pre) - len(post_)) + post_


class SlowUpstream(http.server.BaseHTTPRequestHandler):
    """An OpenAI-shaped upstream that reads the body and answers after a while (so bodies stay in hand)."""
    hold = 1.0

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        while n > 0:
            c = self.rfile.read(min(n, 1 << 20))
            if not c:
                break
            n -= len(c)
        time.sleep(self.hold)
        body = json.dumps({"id": "c1", "object": "chat.completion", "created": 1, "model": "gpt-4o-mini",
                           "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=os.path.join(ROOT, "build", "raiju"))
    ap.add_argument("--server", default=os.environ.get("RAIJU_SERVER", "bun"))
    ap.add_argument("--port", type=int, default=18349)
    ap.add_argument("--upstream-port", type=int, default=18348)
    ap.add_argument("--conns", type=int, default=6)
    ap.add_argument("--size-mb", type=int, default=90)
    ap.add_argument("--max-rss-mb", type=int, default=128)
    ap.add_argument("--auth-conns", type=int, default=12)
    ap.add_argument("--auth-size-mb", type=int, default=16)
    ap.add_argument("--max-auth-rss-mb", type=int, default=448)
    ap.add_argument("--cap-mb", type=int, default=0, help="server.max_buffered_body_mb (0: the default)")
    ap.add_argument("--hold", type=float, default=1.0)
    a = ap.parse_args()
    SlowUpstream.hold = a.hold
    up = http.server.ThreadingHTTPServer(("127.0.0.1", a.upstream_port), SlowUpstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    d = tempfile.mkdtemp(prefix="raiju-body-memory-")
    cfg = os.path.join(d, "config.json")
    server = {"max_buffered_body_mb": a.cap_mb} if a.cap_mb != 0 else {}
    json.dump({"client": {"enable_logging": False, "enforce_auth_on_inference": True}, "alerts": {"enabled": False},
               "pricing_sync": {"enabled": False}, "server": server,
               "governance": {"virtual_keys": [{"id": "bench", "name": "bench", "value": KEY}]},
               "providers": {"openai": {"keys": [{"name": "k", "value": "sk-bench", "models": []}],
                                        "network_config": {"base_url": f"http://127.0.0.1:{a.upstream_port}", "max_retries": 0}}}},
              open(cfg, "w"))
    gw = subprocess.Popen([a.bin, "-port", str(a.port), "-host", "127.0.0.1", "-config", cfg, "-server", a.server],
                          stderr=open(os.path.join(d, "gateway.log"), "w"))
    ok = True
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", a.port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        idle = vm(gw.pid, "VmRSS")
        big = chat_body(a.size_mb * 1048576)
        codes = burst(a.port, a.conns, big, {})
        peak1 = vm(gw.pid, "VmHWM")
        refused = codes.count(401)
        print(f"{a.server}: unauthenticated {a.conns} x {a.size_mb} MB: codes {sorted(codes)}, RSS idle {idle} MB, peak {peak1} MB (limit {a.max_rss_mb})")
        if refused != a.conns or peak1 > a.max_rss_mb:
            ok = False
        del big
        body = chat_body(a.auth_size_mb * 1048576)
        codes = burst(a.port, a.auth_conns, body, {"x-bf-vk": KEY})
        peak2 = vm(gw.pid, "VmHWM")
        print(f"{a.server}: authenticated {a.auth_conns} x {a.auth_size_mb} MB: codes {sorted(codes)}, peak {peak2} MB (limit {a.max_auth_rss_mb})")
        served, busy = codes.count(200), codes.count(503)
        if served < 1 or served + busy != a.auth_conns or peak2 > a.max_auth_rss_mb:
            ok = False
        if a.cap_mb >= 0 and a.auth_conns * a.auth_size_mb > (a.cap_mb or 48) and busy == 0:
            ok = False
    finally:
        gw.terminate()
        gw.wait()
        up.shutdown()
    print("ok" if ok else "FAIL")
    sys.exit(0 if ok else 1)


main()
