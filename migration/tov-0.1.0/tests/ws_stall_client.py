"""Drives ws_stall (patch 0022) over raw sockets. Usage: ws_stall_client.py BINARY OUTDIR
Prints an "ok" or "FAIL" line per check. The server's idleTimeout is 1 s; each WebSocket is sent 8 MB at once."""
import base64, os, socket, subprocess, sys, time

BIN, OUT = sys.argv[1], sys.argv[2]


def check(ok, what, detail=""):
    print(f"ok {what}" if ok else f"FAIL {what} {detail}")


def upgrade(port, name):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # a small receive buffer, so the kernel holds little of what the server sends
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    s.settimeout(6)
    s.connect(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(f"GET /?name={name} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
              f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        b = s.recv(1)
        if not b:
            break
        head += b
    return s, head.startswith(b"HTTP/1.1 101")


def closed_line(path, name):
    for line in open(path).read().splitlines():
        if line.startswith(f"closed {name} "):
            return line
    return ""


def main():
    path = os.path.join(OUT, "ws_stall.out")
    out = open(path, "w")
    p = subprocess.Popen([BIN], stdout=out)
    port = 0
    for _ in range(100):
        time.sleep(0.05)
        text = open(path).read()
        if "listening " in text:
            port = int(text.split("listening ")[1].split()[0])
            break
    if not port:
        p.kill()
        print("FAIL the server did not start")
        return
    try:
        stalled, ok1 = upgrade(port, "stalled")
        reader, ok2 = upgrade(port, "reader")
        check(ok1 and ok2, "both WebSockets are upgraded")
        # the reader takes 32 KB every 100 ms (well under 8 MB in 3 s), the stalled one reads nothing
        t0 = time.time()
        got = 0
        stalled_at = None
        reader_line = ""
        while time.time() - t0 < 3.5:
            try:
                got += len(reader.recv(32768))
            except OSError:
                break
            time.sleep(0.1)
            if stalled_at is None and closed_line(path, "stalled"):
                stalled_at = time.time() - t0
            reader_line = reader_line or closed_line(path, "reader")
        line = closed_line(path, "stalled")
        check(line != "" and " 1006 " in line, "a WebSocket whose client stops reading is closed (1006)", line or open(path).read())
        check(stalled_at is not None and stalled_at < 3.4, "within a few sweeps past the idle timeout", f"{stalled_at}")
        check(reader_line == "" and got > 0, "a client that keeps reading is not dropped", f"{reader_line} got {got}")
        # the stalled socket's connection is gone: reading reaches the end (after what the kernel held)
        stalled.settimeout(3)
        end = False
        try:
            while True:
                b = stalled.recv(65536)
                if not b:
                    end = True
                    break
        except socket.timeout:
            end = False
        except OSError:
            end = True
        check(end, "the stalled connection is closed")
        reader.close()
        stalled.close()
    finally:
        p.kill()
        p.wait()


main()
