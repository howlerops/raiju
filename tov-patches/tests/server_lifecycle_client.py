"""Drives server_lifecycle (patch 0012) over raw sockets. Usage: server_lifecycle_client.py BINARY OUTDIR
Prints an "ok" or "FAIL" line per check."""
import os, resource, signal, socket, subprocess, sys, time

BIN, OUT = sys.argv[1], sys.argv[2]


def start(name, workers="1", max_conns="3", nofile=None):
    out = open(os.path.join(OUT, name + ".out"), "w")
    pre = None
    if nofile is not None:
        def pre():
            resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
    p = subprocess.Popen([BIN], env={**os.environ, "W": workers, "MAX_CONNS": max_conns}, stdout=out, preexec_fn=pre)
    path = os.path.join(OUT, name + ".out")
    for _ in range(100):
        time.sleep(0.05)
        text = open(path).read()
        if "listening " in text:
            port = int(text.split("listening ")[1].split()[0])
            return p, port, path
    p.kill()
    raise SystemExit("FAIL the server did not start")


def conn(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=6)
    return s


def drain(s):
    out = b""
    try:
        while True:
            b = s.recv(4096)
            if not b:
                break
            out += b
    except OSError as e:
        out += f"<{e}>".encode()
    return out


def check(ok, what, detail=""):
    print(f"ok {what}" if ok else f"FAIL {what} {detail}")


def timed(port, data):
    s = conn(port)
    if data:
        s.sendall(data)
    t = time.time()
    r = drain(s)
    return r, time.time() - t


def stop_run(name, workers):
    p, port, path = start(name, workers=workers)
    s = conn(port)
    s.sendall(b"GET /slow HTTP/1.1\r\nHost: x\r\n\r\n")
    time.sleep(0.3)
    p.send_signal(signal.SIGTERM)
    time.sleep(0.3)
    try:
        conn(port).close()
        refused = False
    except OSError:
        refused = True
    r = drain(s)
    try:
        code = p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
        code = None
    check(r.endswith(b"slow done\n"), f"SIGTERM lets the request in hand finish ({workers} worker)", r[-80:])
    check(refused, f"SIGTERM closes the listener ({workers} worker)")
    check(code == 0, f"the stop exits cleanly ({workers} worker)", code)
    check("stop SIGTERM" in open(path).read(), f"onStopSignal was called ({workers} worker)")


p, port, path = start("limits")
try:
    r, dt = timed(port, b"")
    check(r == b"" and 0.7 < dt < 2.5, "a silent connection closes after the header timeout", (r, dt))
    r, dt = timed(port, b"GET / HTTP/1.1\r\nHost: x\r\n")
    check(r.startswith(b"HTTP/1.1 408") and 0.7 < dt < 2.5, "a slow request head is answered 408", (r[:40], dt))
    r, dt = timed(port, b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n\r\nab")
    check(r.startswith(b"HTTP/1.1 408") and 0.7 < dt < 2.5, "a stalled body is answered 408", (r[:40], dt))
    r, dt = timed(port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    check(r.startswith(b"HTTP/1.1 200") and 1.7 < dt < 3.5, "an idle keep-alive connection closes after the idle timeout", (r[:20], dt))
    r, dt = timed(port, b"GET /slow HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    check(r.endswith(b"slow done\n"), "a request being handled is not timed out", r[-40:])
    held = [conn(port) for _ in range(3)]
    for h in held:
        h.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        h.recv(200)
    r, _ = timed(port, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    check(r.startswith(b"HTTP/1.1 503"), "a connection over maxConnections is answered 503", r[:40])
    for h in held:
        h.close()
    time.sleep(0.3)
    r, _ = timed(port, b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    check(r.startswith(b"HTTP/1.1 200"), "below the cap again, requests are served", r[:40])
finally:
    p.kill()
    p.wait()
print(open(path).read().splitlines()[1])

stop_run("stop1", "1")
stop_run("stop2", "2")

# out of descriptors: connections past the limit are answered 503 (the spare descriptor), and the server
# serves again once they are gone
p, port, path = start("emfile", max_conns="0", nofile=48)
try:
    held = []
    busy = 0
    for _ in range(60):
        s = conn(port)
        s.settimeout(0.5)
        try:
            s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            got = s.recv(200)
        except OSError:
            got = b""
        if got.startswith(b"HTTP/1.1 503"):
            busy += 1
        held.append(s)
    check(busy > 0, "out of descriptors, a connection is answered 503", busy)
    for s in held:
        s.close()
    time.sleep(0.5)
    r, _ = timed(port, b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    check(r.startswith(b"HTTP/1.1 200"), "with descriptors back, requests are served", r[:40])
finally:
    p.kill()
    p.wait()
