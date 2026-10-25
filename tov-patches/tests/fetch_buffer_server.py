"""The upstream of fetch_buffer.tov (patch 0016): answers that need a fetch connection's input buffer to grow past its
first 16 KB (a 40 KB response head, one chunk of 100 KB, a chunk size line split across reads), and many small
events. Prints "listening <port>"."""
import socket, sys, threading, time


def answer(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        got = conn.recv(65536)
        if not got:
            return
        data += got
    path = data.split(b" ")[1]
    if path == b"/bighead":
        head = b"HTTP/1.1 200 OK\r\nx-filler: " + b"h" * 40000 + b"\r\ntransfer-encoding: chunked\r\n\r\n"
        conn.sendall(head)
        big = b"b" * 100000
        conn.sendall(b"%x\r\n" % len(big) + big + b"\r\n")
        # a chunk whose size line arrives in two pieces
        conn.sendall(b"1")
        time.sleep(0.05)
        conn.sendall(b"0\r\n" + b"c" * 16 + b"\r\n0\r\n\r\n")
    elif path == b"/events":
        conn.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n")
        for i in range(2000):
            ev = b"data: event %d\n\n" % i
            conn.sendall(b"%x\r\n" % len(ev) + ev + b"\r\n")
        conn.sendall(b"0\r\n\r\n")
    else:
        conn.sendall(b"HTTP/1.1 404 Not Found\r\ncontent-length: 0\r\n\r\n")
    conn.close()


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))
srv.listen(16)
print(f"listening {srv.getsockname()[1]}", flush=True)
while True:
    c, _ = srv.accept()
    threading.Thread(target=answer, args=(c,), daemon=True).start()
