#!/usr/bin/env python3
"""A small origin for the fetch pool and HTTP/2 tests (patch 0007).

Usage: h2_server.py MODE CERT KEY
  MODE h2     TLS, ALPN h2 then http/1.1: HTTP/2 (50 streams per connection) when the client offers it, else HTTP/1.1
  MODE h1tls  TLS, ALPN http/1.1 only
  MODE h1     plain HTTP/1.1
Prints "listening PORT" and serves until killed. Needs the `h2` package (pip install h2).

Paths:
  /echo?...   200, body "hello <path>"
  /slow       200 after 0.4 s (so concurrent requests overlap)
  /big?n=N    200 with an N-byte body (default 300000)
  /post       200, body = the request body, back
  /gzip       200, Content-Encoding: gzip
  /redir      302 to /echo?redirected
  /bye        200, then the server sends GOAWAY and closes the connection
  /v1/chat/completions  200 JSON, a canned chat completion (after 0.4 s when the body says "slow"; for gateway tests);
              as server-sent events, a chunk every 50 ms, when the request says "stream": true (HTTP/2 only)
  /stats      200 JSON counters: connections, h2 connections, open now, most open at once,
              requests, most concurrent streams on one connection, PINGs received (a connection
              that only asks for /stats is not counted)
"""
import asyncio
import json
import ssl
import sys
import time

per_conn = []
stats = {"conns": 0, "h2_conns": 0, "open": 0, "max_open": 0, "reqs": 0, "max_streams": 0, "pings": 0, "paths": []}


def conn_opened():
    stats["conns"] += 1
    stats["open"] += 1
    stats["max_open"] = max(stats["max_open"], stats["open"])


def conn_closed():
    stats["open"] -= 1


def answer(method, path, body):
    """(status, content-type, bytes, delay seconds, after) for a request."""
    bare = path.split("?")[0]
    stats["reqs"] += 1
    stats["paths"].append(bare)
    if bare == "/stats":
        return 200, "application/json", json.dumps(stats).encode(), 0, None
    if bare == "/slow":
        return 200, "text/plain", b"slow", 0.4, None
    if bare == "/big":
        n = 300_000
        if "n=" in path:
            n = int(path.split("n=")[1].split("&")[0])
        return 200, "application/octet-stream", bytes(65 + (i * 7) % 26 for i in range(n)), 0, None
    if bare == "/post":
        return 200, "application/octet-stream", body, 0, None
    if bare == "/gzip":
        import gzip
        return 200, "text/plain", gzip.compress(b"gzipped over the wire"), 0, "gzip"
    if bare == "/redir":
        return 302, "text/plain", b"", 0, "redir"
    if bare == "/bye":
        return 200, "text/plain", b"bye", 0, "bye"
    if bare == "/v1/chat/completions":
        out = {
            "id": "chatcmpl-h2test", "object": "chat.completion", "created": 1700000000, "model": "gpt-h2",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello over h2"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }
        return 200, "application/json", json.dumps(out).encode(), 0.4 if b"slow" in body else 0, None
    return 200, "text/plain", ("hello " + path).encode(), 0, None


class H1(asyncio.Protocol):
    def connection_made(self, transport):
        self.t = transport
        self.buf = b""
        self.counted = False   # (a connection that only asks for /stats is not counted)

    def connection_lost(self, exc):
        if self.counted:
            conn_closed()

    def data_received(self, data):
        self.buf += data
        while True:
            end = self.buf.find(b"\r\n\r\n")
            if end < 0:
                return
            head = self.buf[:end].decode("latin1").split("\r\n")
            method, path, _ = head[0].split(" ", 2)
            n = 0
            for line in head[1:]:
                k, _, v = line.partition(":")
                if k.strip().lower() == "content-length":
                    n = int(v.strip())
            if len(self.buf) < end + 4 + n:
                return
            if not self.counted and path.split("?")[0] != "/stats":
                self.counted = True
                conn_opened()
            body = self.buf[end + 4:end + 4 + n]
            self.buf = self.buf[end + 4 + n:]
            asyncio.ensure_future(self.reply(method, path, body))

    async def reply(self, method, path, body):
        status, ctype, payload, delay, after = answer(method, path, body)
        if delay:
            await asyncio.sleep(delay)
        extra = "Content-Encoding: gzip\r\n" if after == "gzip" else "Location: /echo?redirected\r\n" if after == "redir" else ""
        head = f"HTTP/1.1 {status} OK\r\nContent-Type: {ctype}\r\n{extra}Content-Length: {len(payload)}\r\nConnection: keep-alive\r\n\r\n"
        self.t.write(head.encode() + payload)
        if after == "bye":
            self.t.close()


class H2(asyncio.Protocol):
    def connection_made(self, transport):
        import h2.config
        import h2.connection
        import h2.settings
        self.t = transport
        self.conn = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False, header_encoding="utf-8"))
        self.conn.initiate_connection()
        self.conn.update_settings({h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: 50})
        self.t.write(self.conn.data_to_send())
        self.reqs = {}
        self.out = {}      # stream id -> bytes still to send
        self.active = 0
        self.counted = False

    def connection_lost(self, exc):
        if self.counted:
            conn_closed()

    def flush(self):
        data = self.conn.data_to_send()
        if data:
            self.t.write(data)

    def data_received(self, data):
        import h2.events
        try:
            events = self.conn.receive_data(data)
        except Exception:
            self.t.close()
            return
        for ev in events:
            if isinstance(ev, h2.events.RequestReceived):
                hd = dict(ev.headers)
                if not self.counted and hd.get(":path", "/").split("?")[0] != "/stats":
                    self.counted = True
                    conn_opened()
                    stats["h2_conns"] += 1
                    per_conn.append(0)
                    self.cid = len(per_conn) - 1
                self.reqs[ev.stream_id] = {"method": hd.get(":method", "GET"), "path": hd.get(":path", "/"), "body": b""}
                self.active += 1
                if self.counted:
                    stats["max_streams"] = max(stats["max_streams"], self.active)
                    per_conn[self.cid] = max(per_conn[self.cid], self.active)
                    stats["per_conn"] = list(per_conn)
            elif isinstance(ev, h2.events.DataReceived):
                self.reqs[ev.stream_id]["body"] += ev.data
                self.conn.acknowledge_received_data(ev.flow_controlled_length, ev.stream_id)
            elif isinstance(ev, h2.events.StreamEnded):
                rq = self.reqs.pop(ev.stream_id, None)
                if rq:
                    asyncio.ensure_future(self.reply(ev.stream_id, rq))
            elif isinstance(ev, h2.events.PingReceived):
                stats["pings"] += 1
            elif isinstance(ev, h2.events.WindowUpdated):
                self.push(ev.stream_id)
                if ev.stream_id == 0:
                    for sid in list(self.out):
                        self.push(sid)
            elif isinstance(ev, h2.events.StreamReset):
                self.out.pop(ev.stream_id, None)
                self.reqs.pop(ev.stream_id, None)
                self.active = max(0, self.active - 1)
        self.flush()

    async def stream_reply(self, sid):
        """A chat completion as server-sent events, a chunk at a time."""
        chunk = lambda delta, finish=None, extra=None: "data: " + json.dumps({"id": "chatcmpl-h2sse", "object": "chat.completion.chunk", "created": 1700000000, "model": "gpt-h2", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **(extra or {})}) + "\n\n"
        events = [chunk({"role": "assistant", "content": "hello "}), chunk({"content": "over h2"}), chunk({}, "stop", {"usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}), "data: [DONE]\n\n"]
        try:
            self.conn.send_headers(sid, [(":status", "200"), ("content-type", "text/event-stream")])
            self.flush()
            for ev in events:
                await asyncio.sleep(0.05)
                self.conn.send_data(sid, ev.encode())
                self.flush()
            self.conn.end_stream(sid)
            self.flush()
            self.active = max(0, self.active - 1)
        except Exception:
            pass

    async def reply(self, sid, rq):
        status, ctype, payload, delay, after = answer(rq["method"], rq["path"], rq["body"])
        if rq["path"].split("?")[0] == "/v1/chat/completions":
            try:
                if json.loads(rq["body"]).get("stream"):
                    await self.stream_reply(sid)
                    return
            except Exception:
                pass
        if delay:
            await asyncio.sleep(delay)
        try:
            hs = [(":status", str(status)), ("content-type", ctype), ("content-length", str(len(payload)))]
            if after == "gzip":
                hs.append(("content-encoding", "gzip"))
            if after == "redir":
                hs.append(("location", "/echo?redirected"))
            head_only = rq["method"] == "HEAD"
            self.conn.send_headers(sid, hs, end_stream=not payload or head_only)
            if not payload or head_only:
                self.flush()
                self.active = max(0, self.active - 1)
                return
            self.out[sid] = payload
            self.push(sid)
            if after == "bye":
                self.conn.close_connection(error_code=0)
            self.flush()
            if after == "bye":
                await asyncio.sleep(0.05)
                self.t.close()
        except Exception:
            pass

    def push(self, sid):
        data = self.out.get(sid)
        if data is None:
            return
        try:
            while data:
                n = min(self.conn.local_flow_control_window(sid), self.conn.max_outbound_frame_size, len(data))
                if n <= 0:
                    break
                self.conn.send_data(sid, data[:n])
                data = data[n:]
            if data:
                self.out[sid] = data
            else:
                del self.out[sid]
                self.conn.end_stream(sid)
                self.active = max(0, self.active - 1)
        except Exception:
            self.out.pop(sid, None)
        self.flush()


async def main():
    mode, cert, key = sys.argv[1], sys.argv[2], sys.argv[3]
    loop = asyncio.get_running_loop()
    ctx = None
    if mode != "h1":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        ctx.set_alpn_protocols(["h2", "http/1.1"] if mode == "h2" else ["http/1.1"])

    class Router(asyncio.Protocol):
        """Picks HTTP/2 or HTTP/1.1 from the ALPN result."""

        def __init__(self):
            self.inner = None

        def connection_made(self, transport):
            sslobj = transport.get_extra_info("ssl_object")
            proto = sslobj.selected_alpn_protocol() if sslobj else None
            self.inner = H2() if proto == "h2" else H1()
            self.inner.connection_made(transport)

        def data_received(self, data):
            self.inner.data_received(data)

        def connection_lost(self, exc):
            self.inner.connection_lost(exc)

    server = await loop.create_server(Router, "127.0.0.1", 0, ssl=ctx)
    print("listening", server.sockets[0].getsockname()[1], flush=True)
    async with server:
        await server.serve_forever()


asyncio.run(main())
