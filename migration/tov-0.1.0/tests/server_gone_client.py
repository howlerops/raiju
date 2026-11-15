"""Drives server_gone (patch 0015) over raw sockets. Usage: server_gone_client.py PORT
Prints an "ok" or "FAIL" line per check."""
import socket, sys, time

PORT = int(sys.argv[1])


def ask(path):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=6)
    s.sendall(b"GET " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
    out = b""
    while True:
        b = s.recv(4096)
        if not b:
            break
        out += b
    s.close()
    return out.split(b"\r\n\r\n", 1)[-1].decode()


def leave(path, how):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=6)
    s.sendall(b"GET " + path.encode() + b" HTTP/1.1\r\nHost: x\r\n\r\n")
    time.sleep(0.2)
    if how == "close":
        s.close()
    else:
        s.shutdown(socket.SHUT_WR)
        time.sleep(0.5)
        s.close()


def status():
    return dict(kv.split("=", 1) for kv in ask("/status").split(";"))


leave("/wait", "close")
time.sleep(0.3)
st = status()
print("ok a client that closes aborts the request's signal" if st["wait"] == "aborted AbortError" else f"FAIL wait saw {st['wait']!r}")

leave("/late", "close")
time.sleep(0.8)
st = status()
print("ok a signal first read after the client left is aborted" if st["late"] == "aborted" else f"FAIL late saw {st['late']!r}")

t0 = time.time()
body = ask("/normal")
st = status()
print("ok an answered request's signal stays quiet" if body == "normal\n" and st["normal"] == "not aborted" else f"FAIL normal {body!r} {st['normal']!r}")

leave("/wait", "shutdown")
time.sleep(0.3)
st = status()
print("ok a client that ends its side aborts the signal" if st["wait"] == "aborted AbortError" else f"FAIL half-close saw {st['wait']!r}")
