#!/usr/bin/env python3
"""Drives request_body_server.tov (patch 0008): big request bodies read as a stream by Bun.serve.

Usage: request_body_client.py PORT PID
Prints "ok ..." and "FAIL ..." lines; exit status 1 if any failed. PID is the server process, whose
peak memory is checked.
"""
import socket
import sys
import time

port, pid = int(sys.argv[1]), int(sys.argv[2])
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("ok " + name) if ok else ("FAIL " + name + " " + str(detail)[:300]), flush=True)
    if not ok:
        fails += 1


def body_bytes(n, seed=1):
    out = bytearray(n)
    x = seed
    for i in range(n):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out[i] = (x >> 16) & 0xFF
    return bytes(out)


def checksum(data):
    v = 7
    for x in data:
        v = (v * 31 + x) % 1000000007
    return v


def conn():
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def read_response(s):
    """(status, body) of one response (Content-Length framed)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        c = s.recv(65536)
        if not c:
            break
        buf += c
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin1").split("\r\n")
    status = int(lines[0].split(" ")[1]) if lines and lines[0] else 0
    n = 0
    for l in lines[1:]:
        k, _, v = l.partition(":")
        if k.lower() == "content-length":
            n = int(v.strip())
    while len(rest) < n:
        c = s.recv(65536)
        if not c:
            break
        rest += c
    return status, rest[:n].decode("latin1")


def post(path, data, headers=""):
    s = conn()
    s.sendall(f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n{headers}\r\n".encode())
    s.sendall(data)
    r = read_response(s)
    s.close()
    return r


def rss_kb():
    for l in open(f"/proc/{pid}/status"):
        if l.startswith("VmHWM:"):
            return int(l.split()[1])
    return 0


def chunked(data, sizes, ext=False, trailer=False):
    out = b""
    i, k = 0, 0
    while i < len(data):
        n = min(sizes[k % len(sizes)], len(data) - i)
        out += (b"%x" % n) + (b";name=value" if ext else b"") + b"\r\n" + data[i:i + n] + b"\r\n"
        i += n
        k += 1
    out += b"0\r\n" + (b"X-Trailer: 1\r\n" if trailer else b"") + b"\r\n"
    return out


big = body_bytes(1 << 20)
want = f"{len(big)} {checksum(big)} chunks\n"

# a big body: the handler reads it chunk by chunk
st, txt = post("/sum", big)
check("a 1 MiB body arrives intact through req.body", st == 200 and txt == want, (st, txt))

# below the threshold: whole, one chunk
small = body_bytes(10000, 5)
st, txt = post("/sum", small)
check("a body under the threshold arrives whole through req.body", st == 200 and txt == f"{len(small)} {checksum(small)} one\n", (st, txt))

# text() on a streamed body reads it whole
st, txt = post("/text", big)
check("req.text() reads a streamed body whole", st == 200 and txt.split(" ")[0] == str(len(big)), (st, txt[:80]))

# chunked: extensions, odd sizes, a trailer
st = conn()
st.sendall(b"POST /sum HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
st.sendall(chunked(big, [1000, 65536, 7, 100000, 3], ext=True, trailer=True))
r = read_response(st)
check("a chunked body (extensions, trailer) arrives intact", r == (200, want), r)
# keep-alive after a streamed body: the next request on the same connection
st.sendall(f"POST /sum HTTP/1.1\r\nHost: x\r\nContent-Length: {len(small)}\r\n\r\n".encode() + small)
r = read_response(st)
check("the connection serves the next request after a streamed body", r == (200, f"{len(small)} {checksum(small)} one\n"), r)
st.close()

# the whole chunked body in one packet, and byte by byte for the framing
st = conn()
st.sendall(b"POST /sum HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
raw = chunked(big[:200000], [50000])
for i in range(0, 200, 1):
    st.sendall(raw[i:i + 1])
st.sendall(raw[200:])
r = read_response(st)
exp = body_bytes(1 << 20)[:200000]
check("a chunked body whose framing arrives byte by byte is read", r == (200, f"{len(exp)} {checksum(exp)} chunks\n"), r)
st.close()

# a body nobody reads is dropped; the connection stays usable
s = conn()
s.sendall(f"POST /ignore HTTP/1.1\r\nHost: x\r\nContent-Length: {len(big) * 3}\r\n\r\n".encode())
s.sendall(big * 3)
r = read_response(s)
check("a body the handler ignores is dropped", r == (200, "ignored\n"), r)
s.sendall(f"POST /sum HTTP/1.1\r\nHost: x\r\nContent-Length: {len(small)}\r\n\r\n".encode() + small)
r = read_response(s)
check("the connection is usable after an ignored body", r == (200, f"{len(small)} {checksum(small)} one\n"), r)
s.close()

# answered before the body is in
s = conn()
s.sendall(f"POST /early HTTP/1.1\r\nHost: x\r\nContent-Length: {len(big) * 2}\r\n\r\n".encode())
s.sendall(big[:1000])
r = read_response(s)
check("a handler may answer before the body is in", r[0] == 413 and r[1] == "too big\n", r)
s.close()

# Expect: 100-continue with a big body
s = conn()
s.sendall(f"POST /sum HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nContent-Length: {len(big)}\r\n\r\n".encode())
got = s.recv(100)
s.sendall(big)
r = read_response(s)
check("Expect: 100-continue is answered for a streamed body", got.startswith(b"HTTP/1.1 100") and r == (200, want), (got, r))
s.close()

# over maxRequestBodySize (32 MiB in this server): declared, then chunked
s = conn()
s.sendall(f"POST /sum HTTP/1.1\r\nHost: x\r\nContent-Length: {100 << 20}\r\n\r\n".encode())
r = read_response(s)
check("a declared length over maxRequestBodySize is answered 413", r[0] == 413, r)
s.close()
s = conn()
s.sendall(b"POST /sum HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n")
blk = body_bytes(1 << 20, 9)
try:
    for i in range(40):
        s.sendall(b"%x\r\n" % len(blk) + blk + b"\r\n")
    s.sendall(b"0\r\n\r\n")
except OSError:
    pass
try:
    r = read_response(s)
except OSError:
    r = (0, "")
check("a chunked body over maxRequestBodySize fails its stream", r[0] == 400 and "too large" in r[1], r)
s.close()

# a client that goes away partway: the server carries on
s = conn()
s.sendall(f"POST /sum HTTP/1.1\r\nHost: x\r\nContent-Length: {len(big) * 4}\r\n\r\n".encode())
s.sendall(big[:300000])
s.close()
time.sleep(0.2)
st, txt = post("/sum", big)
check("the server serves on after a client leaves mid-body", st == 200 and txt == want, (st, txt))

# a body cut short by a half-close
s = conn()
s.sendall(f"POST /sum HTTP/1.1\r\nHost: x\r\nContent-Length: {len(big)}\r\n\r\n".encode())
s.sendall(big[:300000])
s.shutdown(socket.SHUT_WR)
try:
    r = read_response(s)
except OSError:
    r = (0, "")
check("a body cut short by the client ends the stream with an error", r[0] in (0, 400), r)
s.close()

# backpressure: the handler waits 600 ms before reading, so a sender with much more than the
# buffers can hold must wait for it, and the server never holds the body
before = rss_kb()
data = body_bytes(1 << 20, 3) * 24
s = conn()
s.sendall(f"POST /slow HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n\r\n".encode())
t0 = time.time()
s.sendall(data)
sent = time.time() - t0
r = read_response(s)
total = time.time() - t0
s.close()
check("a sender is held back while the handler is not reading", sent > 0.4 and r[0] == 200 and r[1].startswith(str(len(data))), (sent, r))
grew = rss_kb() - before
check("the server did not hold a 24 MiB body (peak memory grew %d MiB)" % (grew // 1024), grew < 16 * 1024, grew)

# a body passed straight into fetch()
big2 = body_bytes(1 << 20, 11) * 10
st, txt = post("/relay", big2)
check("req.body can be the body of a fetch() (10 MiB relayed)", st == 200 and txt == f"{len(big2)} {checksum(big2)} chunks\n", (st, txt))

sys.exit(1 if fails else 0)
