#!/usr/bin/env python3
"""WebSocket memory soak: opens and closes many WebSocket sessions on one gateway worker and fails when RSS grows.

Usage: tests/soak/websockets.py [--seconds N] [--max-bytes-per-session B] [--min-growth-mb M] [--server bun|http1|both] [--no-build]
       [--raiju PATH]

Before re-audit 7 P0-2 was fixed, every closed session stayed in memory: the pipe of a route's socket held the server
connection, whose data held the socket back (a cycle reference counting never frees), and an upstream socket's onopen
held the socket itself, with the relay, its hooks and its log state. A realtime session with a key left ~5 KB, a
/v1/responses open and close ~2.2 KB, a live session ~6 KB, on both servers; live sessions were also refused for good
once 10,000 had been recorded (P1-4). For each server (--server, both by default) this soak runs, each phase after a
warm-up, with 8 clients in a loop:

1. realtime: GET /v1/realtime with a virtual key, a session.created and one turn from the provider, then the client
   drops the connection;
2. responses: GET /v1/responses, one response.create answered from the provider, then a close;
3. responses-bare: GET /v1/responses opened and closed at once;
4. live: GET /v1/live/sessions, a session.start the provider names a new session id for (more sessions than the live
   registry's 10,000 records), then a drop.

The RSS of the worker is sampled every second; a phase fails when the least-squares slope of its RSS over the phase,
spread over the sessions it served, is more than --max-bytes-per-session (256 by default) and adds up to more than
--min-growth-mb over the phase (3 by default, so allocator noise on a slow machine does not fail it; before the fix a
phase grew 25 to 95 MB), or when it serves fewer than 99% of its sessions. It builds build/raiju and build/soak_mock (tests/soak/mock.tov) and starts them on SOAK_MOCK_PORT
and SOAK_PORT (18320 and 18321, as tests/soak/soak.py): run it under the e2e lock, as
`flock /tmp/raiju-e2e.lock python3 tests/soak/websockets.py`. A summary line `websockets: ok ...` or
`websockets: FAIL ...` ends the output; the gateway's stderr is in build/soak-websockets.gateway.log.
"""
import argparse, base64, json, os, shutil, signal, socket, struct, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402  (build, rss_kb, wait_up)

BUILD = soak.BUILD
MOCK_PORT = soak.MOCK_PORT
PORT = soak.PORT
KEY = "sk-bf-soak-" + "websockets-0123456789"
CLIENTS = 8


def ws_open(path, headers):
    """Opens a WebSocket to the gateway: the socket and the handshake's status."""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    extra = "".join("%s: %s\r\n" % kv for kv in headers.items())
    s.sendall(("GET %s HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n%s\r\n" % (path, key, extra)).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        d = s.recv(1)
        if not d:
            break
        head += d
    parts = head.split(b" ")
    return s, int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0


def ws_send(s, text, opcode=1):
    p = text.encode() if isinstance(text, str) else text
    m = os.urandom(4)
    n = len(p)
    if n < 126:
        h = bytes([0x80 | opcode, 0x80 | n])
    elif n < 65536:
        h = bytes([0x80 | opcode, 0x80 | 126]) + struct.pack(">H", n)
    else:
        h = bytes([0x80 | opcode, 0x80 | 127]) + struct.pack(">Q", n)
    s.sendall(h + m + bytes(b ^ m[i % 4] for i, b in enumerate(p)))


def ws_recv(s):
    """One frame: (opcode, payload)."""
    def rd(k):
        b = b""
        while len(b) < k:
            d = s.recv(k - len(b))
            if not d:
                raise EOFError("closed")
            b += d
        return b
    h = rd(2)
    n = h[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", rd(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rd(8))[0]
    return h[0] & 0x0F, rd(n)


def until(s, needle, limit=50):
    """Reads frames until one contains needle; False on a close frame or after limit frames."""
    for _ in range(limit):
        op, d = ws_recv(s)
        if op == 8:
            return False
        if needle in d:
            return True
    return False


def close_frame(s):
    """Sends a close frame and waits briefly for the gateway's."""
    try:
        ws_send(s, struct.pack(">H", 1000), opcode=8)
        s.settimeout(5)
        while True:
            op, _ = ws_recv(s)
            if op == 8:
                break
    except Exception:
        pass


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.ok = 0
        self.bad = 0
        self.errors = 0
        self.last = ""
        self.n = 0

    def add(self, good, why=""):
        with self.lock:
            if good:
                self.ok += 1
            else:
                self.bad += 1
                self.last = why


def session(kind, idx, stats):
    """One session of a phase."""
    hdr = {"x-bf-vk": KEY}
    with stats.lock:
        stats.n += 1
        n = stats.n
    s = None
    try:
        if kind == "realtime":
            s, code = ws_open("/v1/realtime?model=openai/gpt-realtime", hdr)
            if code != 101:
                return stats.add(False, "status %d" % code)
            ws_send(s, json.dumps({"type": "test.rt.start", "id": "sess_soak_%d_%d" % (idx, n)}))
            ok = until(s, b"session.created")
            ws_send(s, json.dumps({"type": "test.rt.turn", "id": "resp_soak_%d_%d" % (idx, n), "input": 10, "output": 5}))
            ok = ok and until(s, b"response.done")
            stats.add(ok, "no response.done")
        elif kind == "responses":
            s, code = ws_open("/v1/responses", hdr)
            if code != 101:
                return stats.add(False, "status %d" % code)
            ws_send(s, json.dumps({"type": "response.create", "model": "openai/gpt-4o-mini", "input": "hi"}))
            stats.add(until(s, b"response.completed"), "no response.completed")
            close_frame(s)
        elif kind == "responses-bare":
            s, code = ws_open("/v1/responses", hdr)
            stats.add(code == 101, "status %d" % code)
            if code == 101:
                close_frame(s)
        elif kind == "live":
            s, code = ws_open("/v1/live/sessions", hdr)
            if code != 101:
                return stats.add(False, "status %d" % code)
            sid = "sess_soak_live_%d_%d_%d" % (os.getpid(), idx, n)
            ws_send(s, json.dumps({"type": "session.start", "session": {"model": "openai/gpt-live", "mock_id": sid}}))
            stats.add(until(s, b"session.started"), "no session.started")
    except Exception as e:
        with stats.lock:
            stats.errors += 1
            stats.last = repr(e)
        time.sleep(0.05)
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def drive(kind, stop, stats):
    def loop(i):
        while time.monotonic() < stop:
            session(kind, i, stats)
    ts = [threading.Thread(target=loop, args=(i,)) for i in range(CLIENTS)]
    for t in ts:
        t.start()
    return ts


def slope(samples):
    """The least-squares slope of (seconds, KB) samples, in KB per second."""
    n = len(samples)
    if n < 2:
        return 0.0
    mx = sum(x for x, _ in samples) / n
    my = sum(y for _, y in samples) / n
    den = sum((x - mx) ** 2 for x, _ in samples)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in samples) / den


def phase(pid, kind, seconds, server):
    """Runs a phase after a warm-up: (sessions served, sessions, errors, last error, RSS before and after in KB,
    slope in KB/s, bytes per session)."""
    warm = Stats()
    for t in drive(kind, time.monotonic() + max(4.0, seconds / 5), warm):
        t.join()
    time.sleep(1)
    st = Stats()
    start = time.monotonic()
    before = soak.rss_kb(pid)
    samples = [(0.0, before)]
    ts = drive(kind, start + seconds, st)
    while any(t.is_alive() for t in ts):
        time.sleep(1)
        samples.append((time.monotonic() - start, soak.rss_kb(pid)))
        if len(samples) % 10 == 0:
            print("websockets:   %s %s t=%3.0fs rss %.1f MB, %d sessions" % (server, kind, samples[-1][0], samples[-1][1] / 1024, st.ok), flush=True)
    for t in ts:
        t.join()
    took = time.monotonic() - start
    time.sleep(1)
    after = soak.rss_kb(pid)
    k = slope(samples)
    per = k * 1024 * took / st.ok if st.ok > 0 else 0.0
    return st, before, after, k, per


def run_server(raiju, cfgpath, server, seconds, max_per, min_growth):
    log = open(os.path.join(BUILD, "soak-websockets.gateway.log"), "a")
    gw = subprocess.Popen([raiju, "-port", str(PORT), "-host", "127.0.0.1", "-config", cfgpath, "-server", server, "-workers", "1"],
                          stdout=subprocess.DEVNULL, stderr=log)
    failures = []
    report = []
    try:
        soak.wait_up(PORT)
        time.sleep(0.5)
        print("websockets: %s start %.1f MB" % (server, soak.rss_kb(gw.pid) / 1024), flush=True)
        for kind in ("realtime", "responses", "responses-bare", "live"):
            st, before, after, k, per = phase(gw.pid, kind, seconds, server)
            total = st.ok + st.bad + st.errors
            line = "%s %s: %d of %d sessions, rss %.1f -> %.1f MB, slope %+.1f KB/s, %+.0f B/session" % (
                server, kind, st.ok, total, before / 1024, after / 1024, k, per)
            print("websockets: " + line + ((" (last: %s)" % st.last) if st.last else ""), flush=True)
            report.append(line)
            if per > max_per and per * st.ok / 1048576 > min_growth:
                failures.append("%s %s: %.0f bytes per session (limit %.0f)" % (server, kind, per, max_per))
            if total == 0 or st.ok < total * 0.99:
                failures.append("%s %s: served %d of %d sessions%s" % (server, kind, st.ok, total, (" (last: %s)" % st.last) if st.last else ""))
            if gw.poll() is not None:
                failures.append("%s: the gateway exited (%s)" % (server, gw.returncode))
                break
    finally:
        if gw.poll() is None:
            gw.send_signal(signal.SIGTERM)
            try:
                gw.wait(10)
            except subprocess.TimeoutExpired:
                gw.kill()
                gw.wait()
        log.close()
    return failures, report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=float(os.environ.get("SOAK_WS_SECONDS", "20")))
    ap.add_argument("--max-bytes-per-session", type=float, default=float(os.environ.get("SOAK_WS_MAX_BYTES", "256")))
    ap.add_argument("--min-growth-mb", type=float, default=float(os.environ.get("SOAK_WS_MIN_GROWTH_MB", "3")))
    ap.add_argument("--server", default=os.environ.get("SOAK_WS_SERVER", "both"))
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--raiju", default="")
    a = ap.parse_args()
    if not a.no_build:
        soak.build()
    raiju = a.raiju or os.path.join(BUILD, "raiju")
    tmp = tempfile.mkdtemp(prefix="raiju-soak-ws-")
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
    open(os.path.join(BUILD, "soak-websockets.gateway.log"), "w").close()
    mock = subprocess.Popen([os.path.join(BUILD, "soak_mock")], env={**os.environ, "MOCK_PORT": str(MOCK_PORT), "MOCK_WORKERS": "2"},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failures = []
    report = []
    try:
        soak.wait_up(MOCK_PORT)
        servers = ["bun", "http1"] if a.server == "both" else [a.server]
        for server in servers:
            f, r = run_server(raiju, path, server, a.seconds, a.max_bytes_per_session, a.min_growth_mb)
            failures += f
            report += r
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
        print("websockets: FAIL: " + "; ".join(failures))
        sys.exit(1)
    print("websockets: ok (%s)" % "; ".join(report))


if __name__ == "__main__":
    main()
