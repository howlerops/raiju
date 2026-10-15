"""An OTLP gRPC collector for e2e, standard library only.

Serves HTTP/2 over plaintext with prior knowledge (h2c), the way OTLP insecure
on port 4317 does. With a certificate and key it serves TLS instead, and only to
clients that pick h2 in ALPN (the way a TLS collector on 4317 does). It answers unary
TraceService/Export and MetricsService/Export calls with grpc-status 0 and records each
export as one JSON line:
{rpc, path, content_type, timeout, service, spans, span_attrs, trace_id_lens, metrics,
 and for TLS: tls, alpn}.

It reads what raiju's gRPC client sends: literal header fields without Huffman
coding. Indexed fields and Huffman strings are refused, so a change to the client
that uses them fails loudly here.

Usage: otlp_grpc_collector.py PORT OUT.jsonl [CERT.pem KEY.pem]
"""
import json, socket, socketserver, ssl, struct, sys, threading

PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
T_DATA, T_HEADERS, T_RST, T_SETTINGS, T_PING, T_GOAWAY, T_WINDOW, T_CONT = 0, 1, 3, 4, 6, 7, 8, 9
F_ACK, F_END_STREAM, F_END_HEADERS, F_PADDED, F_PRIORITY = 1, 1, 4, 8, 0x20
TRACE_PATH = "/opentelemetry.proto.collector.trace.v1.TraceService/Export"
METRICS_PATH = "/opentelemetry.proto.collector.metrics.v1.MetricsService/Export"

OUT = None
OUT_LOCK = threading.Lock()


def frame(typ, flags, sid, payload=b""):
    return struct.pack(">I", len(payload))[1:] + bytes([typ, flags]) + struct.pack(">I", sid & 0x7FFFFFFF) + payload


def hpack_literals(pairs):
    """Literal header fields without indexing and without Huffman coding."""
    out = b""
    for name, value in pairs:
        raw_name, raw_value = name.encode(), value.encode()
        assert len(raw_name) < 127 and len(raw_value) < 127
        out += b"\x00" + bytes([len(raw_name)]) + raw_name + bytes([len(raw_value)]) + raw_value
    return out


def hpack_decode(block):
    """The header fields of a block of literal fields (see the module docstring)."""
    fields, i = {}, 0
    while i < len(block):
        b = block[i]
        if b & 0x80:
            raise ValueError("indexed header field from the client: not supported by this collector")
        if (b & 0xE0) == 0x20:
            i += 1  # dynamic table size update (a value under 32 is one byte here)
            continue
        prefix = 6 if (b & 0xC0) == 0x40 else 4
        if b & ((1 << prefix) - 1):
            raise ValueError("indexed name from the client: not supported by this collector")
        i += 1
        name, i = read_str(block, i)
        value, i = read_str(block, i)
        fields[name] = value
    return fields


def read_str(block, i):
    if block[i] & 0x80:
        raise ValueError("Huffman string from the client: not supported by this collector")
    n = block[i]
    raw = block[i + 1:i + 1 + n]
    return raw.decode(), i + 1 + n


def varint(buf, i):
    v, shift = 0, 0
    while True:
        b = buf[i]
        i += 1
        v |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return v, i


def fields(buf):
    """(field number, wire type, value) for each field of a protobuf message."""
    i = 0
    while i < len(buf):
        key, i = varint(buf, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = varint(buf, i)
        elif w == 1:
            v, i = buf[i:i + 8], i + 8
        elif w == 2:
            n, i = varint(buf, i)
            v, i = buf[i:i + n], i + n
        elif w == 5:
            v, i = buf[i:i + 4], i + 4
        else:
            raise ValueError("unsupported wire type %d" % w)
        yield f, w, v


def any_string(v):
    for f, w, x in fields(v):
        if f == 1:
            return x.decode()
    return None


def key_values(buf):
    out = {}
    for f, w, kv in fields(buf):
        if f != 1:
            continue
        key, value = None, None
        for f2, w2, x in fields(kv):
            if f2 == 1:
                key = x.decode()
            elif f2 == 2:
                value = any_string(x)
        out[key] = value
    return out


def summarize_trace(body):
    out = {"service": None, "spans": [], "span_attrs": [], "trace_id_lens": []}
    for f, w, rs in fields(body):
        if f != 1:
            continue
        for f2, w2, v2 in fields(rs):
            if f2 == 1:
                out["service"] = key_values(v2).get("service.name")
            elif f2 == 2:
                for f3, w3, ss in fields(v2):  # ScopeSpans: scope = 1, spans = 2
                    if f3 != 2:
                        continue
                    name, attrs = None, []
                    for f5, w5, x in fields(ss):  # Span
                        if f5 == 1:
                            out["trace_id_lens"].append(len(x))
                        elif f5 == 5:
                            name = x.decode()
                        elif f5 == 9:
                            attrs.append(x)
                    out["spans"].append(name)
                    for kv in attrs:
                        for f6, w6, key in fields(kv):
                            if f6 == 1:
                                out["span_attrs"].append(key.decode())
    return out


def summarize_metrics(body):
    out = {"service": None, "metrics": []}
    for f, w, rm in fields(body):
        if f != 1:
            continue
        for f2, w2, v2 in fields(rm):
            if f2 == 1:
                out["service"] = key_values(v2).get("service.name")
            elif f2 == 2:
                for f3, w3, m in fields(v2):  # ScopeMetrics: scope = 1, metrics = 2
                    if f3 != 2:
                        continue
                    name = None
                    for f5, w5, x in fields(m):  # Metric: name = 1
                        if f5 == 1:
                            name = x.decode()
                    out["metrics"].append(name)
    return out


def record(entry):
    with OUT_LOCK:
        with open(OUT, "a") as fh:
            fh.write(json.dumps(entry) + "\n")
            fh.flush()


class Handler(socketserver.BaseRequestHandler):
    def recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.request.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    def send(self, data):
        self.request.sendall(data)

    def respond(self, sid, status, message, body):
        self.send(frame(T_HEADERS, F_END_HEADERS, sid, hpack_literals([(":status", "200"), ("content-type", "application/grpc")])))
        self.send(frame(T_DATA, 0, sid, b"\x00" + struct.pack(">I", len(body)) + body))
        trailers = [("grpc-status", str(status))]
        if message:
            trailers.append(("grpc-message", message))
        self.send(frame(T_HEADERS, F_END_HEADERS | F_END_STREAM, sid, hpack_literals(trailers)))

    def dispatch(self, sid, st):
        headers = st["headers"]
        path = headers.get(":path", "")
        raw = st["body"]
        if len(raw) < 5 or raw[0] != 0:
            self.respond(sid, 13, "bad message frame", b"")
            return
        n = struct.unpack(">I", raw[1:5])[0]
        msg = raw[5:5 + n]
        entry = {"path": path, "content_type": headers.get("content-type"), "te": headers.get("te"), "timeout": headers.get("grpc-timeout")}
        if self.server.ctx is not None:
            entry.update(tls=True, alpn=self.request.selected_alpn_protocol())
        if path == TRACE_PATH:
            entry.update(rpc="trace", **summarize_trace(msg))
        elif path == METRICS_PATH:
            entry.update(rpc="metrics", **summarize_metrics(msg))
        else:
            self.respond(sid, 12, "Method not found: " + path, b"")
            return
        record(entry)
        self.respond(sid, 0, "", b"")

    def handle(self):
        try:
            if self.server.ctx is not None:
                self.request = self.server.ctx.wrap_socket(self.request, server_side=True)
                if self.request.selected_alpn_protocol() != "h2":
                    return
            if self.recv_exact(len(PREFACE)) != PREFACE:
                return
            self.send(frame(T_SETTINGS, 0, 0))
            streams = {}
            while True:
                head = self.recv_exact(9)
                length = struct.unpack(">I", b"\x00" + head[0:3])[0]
                typ, flags = head[3], head[4]
                sid = struct.unpack(">I", head[5:9])[0] & 0x7FFFFFFF
                payload = self.recv_exact(length) if length else b""
                if typ == T_SETTINGS:
                    if not flags & F_ACK:
                        self.send(frame(T_SETTINGS, F_ACK, 0))
                elif typ == T_PING:
                    if not flags & F_ACK:
                        self.send(frame(T_PING, F_ACK, 0, payload))
                elif typ == T_HEADERS:
                    st = streams.setdefault(sid, {"block": b"", "body": b"", "headers": None, "end": False})
                    start, end = 0, len(payload)
                    if flags & F_PADDED:
                        start, end = 1, len(payload) - payload[0]
                    if flags & F_PRIORITY:
                        start += 5
                    st["block"] += payload[start:end]
                    st["end"] = bool(flags & F_END_STREAM)
                    if flags & F_END_HEADERS:
                        st["headers"] = hpack_decode(st["block"])
                        st["block"] = b""
                        if st["end"]:
                            self.dispatch(sid, streams.pop(sid))
                elif typ == T_CONT:
                    st = streams[sid]
                    st["block"] += payload
                    if flags & F_END_HEADERS:
                        st["headers"] = hpack_decode(st["block"])
                        st["block"] = b""
                        if st["end"]:
                            self.dispatch(sid, streams.pop(sid))
                elif typ == T_DATA:
                    start, end = 0, len(payload)
                    if flags & F_PADDED:
                        start, end = 1, len(payload) - payload[0]
                    st = streams.get(sid)
                    if st is not None:
                        st["body"] += payload[start:end]
                    if length:
                        # return the bytes to both windows, so the client keeps sending
                        self.send(frame(T_WINDOW, 0, 0, struct.pack(">I", length)))
                        self.send(frame(T_WINDOW, 0, sid, struct.pack(">I", length)))
                    if st is not None and flags & F_END_STREAM:
                        self.dispatch(sid, streams.pop(sid))
                elif typ == T_RST:
                    streams.pop(sid, None)
                elif typ == T_GOAWAY:
                    return
        except (EOFError, ConnectionError, OSError):
            return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    ctx = None  # an SSLContext that offers h2 in ALPN, for TLS


def main():
    global OUT
    port, OUT = int(sys.argv[1]), sys.argv[2]
    open(OUT, "w").close()
    ctx = None
    if len(sys.argv) > 4:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(sys.argv[3], sys.argv[4])
        ctx.set_alpn_protocols(["h2"])
    with Server(("127.0.0.1", port), Handler) as srv:
        srv.ctx = ctx
        print("ready", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
