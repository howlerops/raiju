"""An A2A gRPC agent that answers in grpc-encoding gzip, written on the h2 package so the bytes are its own, for
tests/e2e.py (L190). grpc-go's server answers in the encoding it was called with; this one always compresses
(the compressed flag set, grpc-encoding gzip on the head), so a client that cannot read gzip fails the call.

It serves lf.a2a.v1 SendMessage over h2c (prior knowledge) and, over HTTP/1.1 on a second port:
  GET /card    a v1 card whose one interface is GRPC at http://127.0.0.1:<h2c port>
  GET /seen    what each call sent: its grpc-encoding, grpc-accept-encoding and the request's text
A compressed request (grpc-encoding gzip) is read too.

Usage: grpc_gzip_agent.py; prints "ready <http port> <grpc port>". Ports are picked by the system.
"""
import gzip
import http.server
import json
import os
import socket
import sys
import threading

import h2.config
import h2.connection
import h2.events
import h2.exceptions

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from a2a_grpc_agent import fld, incoming, new_task, task_bytes, card  # noqa: E402

LOCK = threading.Lock()
SEEN = []


def answer(path, headers, body):
    """The trailers and the response message (or None) for one call."""
    hs = dict(headers)
    if len(body) < 5:
        return None, [("grpc-status", "13"), ("grpc-message", "no request message")]
    flag, n = body[0], int.from_bytes(body[1:5], "big")
    msg = body[5:5 + n]
    if flag == 1:
        msg = gzip.decompress(msg)
    text, _, ctx = incoming(msg)
    with LOCK:
        SEEN.append({"path": path, "encoding": hs.get("grpc-encoding", ""), "accept": hs.get("grpc-accept-encoding", ""), "text": text, "compressed_request": flag == 1})
    if not path.endswith("/SendMessage"):
        return None, [("grpc-status", "12"), ("grpc-message", "unknown method")]
    return fld(1, task_bytes(new_task(text, ctx))), [("grpc-status", "0")]


def serve_conn(sock):
    conn = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False, header_encoding="utf-8"))
    conn.initiate_connection()
    sock.sendall(conn.data_to_send())
    heads, bodies = {}, {}
    try:
        while True:
            data = sock.recv(65535)
            if not data:
                return
            for ev in conn.receive_data(data):
                if isinstance(ev, h2.events.RequestReceived):
                    heads[ev.stream_id] = ev.headers
                    bodies[ev.stream_id] = b""
                elif isinstance(ev, h2.events.DataReceived):
                    bodies[ev.stream_id] = bodies.get(ev.stream_id, b"") + ev.data
                    conn.acknowledge_received_data(ev.flow_controlled_length, ev.stream_id)
                elif isinstance(ev, h2.events.StreamEnded):
                    sid = ev.stream_id
                    hs = heads.pop(sid, [])
                    path = dict(hs).get(":path", "")
                    msg, trailers = answer(path, hs, bodies.pop(sid, b""))
                    if msg is None:
                        conn.send_headers(sid, [(":status", "200"), ("content-type", "application/grpc")] + trailers, end_stream=True)
                    else:
                        z = gzip.compress(msg)
                        conn.send_headers(sid, [(":status", "200"), ("content-type", "application/grpc"), ("grpc-encoding", "gzip")])
                        conn.send_data(sid, bytes([1]) + len(z).to_bytes(4, "big") + z)
                        conn.send_headers(sid, trailers, end_stream=True)
            out = conn.data_to_send()
            if out:
                sock.sendall(out)
    except (OSError, h2.exceptions.ProtocolError):
        pass
    finally:
        sock.close()


def main():
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", 0))
    ls.listen(16)
    gport = ls.getsockname()[1]

    def accept():
        while True:
            c, _ = ls.accept()
            threading.Thread(target=serve_conn, args=(c,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()

    class Cards(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/card":
                obj = card("http://127.0.0.1:%d" % gport)
            elif self.path == "/seen":
                with LOCK:
                    obj = list(SEEN)
            else:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Cards)
    print("ready %d %d" % (web.server_address[1], gport), flush=True)
    web.serve_forever()


if __name__ == "__main__":
    main()
