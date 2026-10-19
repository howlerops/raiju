"""HTTP/2 cleartext and gRPC checks for src/h2.tov, src/hpack.tov and src/grpcwire.tov.

tests/h2_echo.tov serves the test.Echo service on 127.0.0.1:18220 (and a second copy on
18221 with grpc-go's 4 MiB request limit). grpcio calls it with raw bytes; the h2 package and
raw sockets check the frames: PING, SETTINGS, RST_STREAM, the GOAWAY answers to a bad preface
and to protocol errors, and the status of a request with the wrong content type.

Needs build/h2_echo (make build/h2_echo). A class is skipped when its library is missing.
"""
import concurrent.futures
import os
import socket
import struct
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ECHO = os.environ.get("H2_ECHO", os.path.join(ROOT, "build", "h2_echo"))
PORT = 18220
SMALL_PORT = 18221
MIB = 1024 * 1024
PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

try:
    import grpc
    HAVE_GRPC = True
except ImportError:
    HAVE_GRPC = False

try:
    import h2.config
    import h2.connection
    import h2.errors
    import h2.events
    import h2.settings
    HAVE_H2 = True
except ImportError:
    HAVE_H2 = False

# the echo servers this file started; stop_all() kills only these
PROCS = []


def start(port, max_recv=None):
    env = dict(os.environ, H2_PORT=str(port))
    if max_recv is not None:
        env["H2_MAX_RECV"] = str(max_recv)
    p = subprocess.Popen([ECHO], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    PROCS.append(p)
    line = p.stdout.readline()
    if not line.startswith("h2 echo on"):
        raise RuntimeError("h2_echo did not start: %r" % line)
    return p


def stop_all():
    for p in PROCS:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
    PROCS.clear()


def setUpModule():
    if not (HAVE_GRPC or HAVE_H2):
        return
    if not os.path.exists(ECHO):
        raise RuntimeError("missing %s: run make build/h2_echo" % ECHO)
    start(PORT)
    if HAVE_GRPC:
        start(SMALL_PORT, max_recv=4 * MIB)


def tearDownModule():
    stop_all()


def status_of(n):
    return {s.value[0]: s for s in grpc.StatusCode}[n] if HAVE_GRPC else None


def grpc_frame(msg):
    return b"\x00" + struct.pack(">I", len(msg)) + msg


def frame(typ, flags, sid, payload):
    return struct.pack(">I", len(payload))[1:] + bytes([typ, flags]) + struct.pack(">I", sid & 0x7FFFFFFF) + payload


def read_frames(s, wait=5.0):
    """Every frame the peer sends until it closes or wait seconds pass."""
    s.settimeout(wait)
    buf = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    frames = []
    i = 0
    while len(buf) - i >= 9:
        n = int.from_bytes(buf[i:i + 3], "big")
        if len(buf) - i < 9 + n:
            break
        frames.append((buf[i + 3], buf[i + 4], int.from_bytes(buf[i + 5:i + 9], "big") & 0x7FFFFFFF, buf[i + 9:i + 9 + n]))
        i += 9 + n
    return frames


def goaway_code(frames):
    gs = [f for f in frames if f[0] == 7]
    if len(gs) != 1:
        return None
    return struct.unpack(">I", gs[0][3][4:8])[0]


def grpc_headers(path, extra=()):
    return [(":method", "POST"), (":scheme", "http"), (":path", path), (":authority", "127.0.0.1"),
            ("content-type", "application/grpc"), ("te", "trailers")] + list(extra)


class RawH2:
    """An h2 client on a plain socket, with the frames it reads kept per stream."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.conn = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=True, header_encoding="utf-8"))
        self.conn.initiate_connection()
        self.flush()
        self.events = []

    def flush(self):
        data = self.conn.data_to_send()
        if data:
            self.sock.sendall(data)

    def wait(self, done, timeout=5.0):
        """Reads until done(events) is true or the timeout passes; returns the events so far."""
        import time
        deadline = time.time() + timeout
        while not done(self.events) and time.time() < deadline:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            self.events.extend(self.conn.receive_data(data))
            self.flush()
        return self.events

    def collect(self, sid, timeout=5.0):
        """The response on stream sid: its headers, body, trailers, reset code and whether it ended."""
        def finished(evs):
            return any(isinstance(e, (h2.events.StreamEnded, h2.events.StreamReset)) and e.stream_id == sid for e in evs)
        self.wait(finished, timeout)
        out = {"headers": {}, "data": b"", "trailers": {}, "reset": None, "ended": False}
        for e in self.events:
            if getattr(e, "stream_id", None) != sid:
                continue
            if isinstance(e, h2.events.ResponseReceived):
                out["headers"].update(dict(e.headers))
            elif isinstance(e, h2.events.DataReceived):
                out["data"] += e.data
                self.conn.acknowledge_received_data(e.flow_controlled_length, sid)
            elif isinstance(e, h2.events.TrailersReceived):
                out["trailers"].update(dict(e.headers))
            elif isinstance(e, h2.events.StreamReset):
                out["reset"] = e.error_code
            elif isinstance(e, h2.events.StreamEnded):
                out["ended"] = True
        self.flush()
        return out


@unittest.skipUnless(HAVE_GRPC, "grpcio is not installed")
class GrpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.channel = grpc.insecure_channel("127.0.0.1:%d" % PORT, options=[("grpc.max_receive_message_length", 16 * MIB)])
        cls.unary = cls.channel.unary_unary("/test.Echo/Unary", request_serializer=None, response_deserializer=None)
        cls.server_stream = cls.channel.unary_stream("/test.Echo/ServerStream", request_serializer=None, response_deserializer=None)
        cls.client_stream = cls.channel.stream_unary("/test.Echo/ClientStream", request_serializer=None, response_deserializer=None)

    @classmethod
    def tearDownClass(cls):
        cls.channel.close()

    def test_unary_echoes_the_message(self):
        self.assertEqual(self.unary(b"hello", timeout=10), b"hello")

    def test_metadata_comes_back_as_headers(self):
        resp, call = self.unary.with_call(b"m", metadata=[("x-echo-a", "1"), ("x-echo-b", "two")], timeout=10)
        self.assertEqual(resp, b"m")
        md = dict(call.initial_metadata())
        self.assertEqual(md.get("x-echo-a"), "1")
        self.assertEqual(md.get("x-echo-b"), "two")

    def test_error_statuses(self):
        for code in range(1, 17):
            with self.subTest(code=code):
                with self.assertRaises(grpc.RpcError) as cm:
                    self.unary(b"x", metadata=[("x-status", str(code))], timeout=10)
                self.assertEqual(cm.exception.code(), status_of(code))
                self.assertEqual(cm.exception.details(), "requested by x-status")

    def test_unknown_method_is_unimplemented(self):
        stub = self.channel.unary_unary("/test.Echo/Nope", request_serializer=None, response_deserializer=None)
        with self.assertRaises(grpc.RpcError) as cm:
            stub(b"x", timeout=10)
        self.assertEqual(cm.exception.code(), grpc.StatusCode.UNIMPLEMENTED)

    def test_client_deadline(self):
        with self.assertRaises(grpc.RpcError) as cm:
            self.unary(b"x", metadata=[("x-sleep-ms", "1500")], timeout=0.2)
        self.assertEqual(cm.exception.code(), grpc.StatusCode.DEADLINE_EXCEEDED)

    def test_generous_deadline_is_met(self):
        self.assertEqual(self.unary(b"quick", metadata=[("x-sleep-ms", "10")], timeout=5), b"quick")

    def test_server_streaming(self):
        msgs = list(self.server_stream(b"3:5", timeout=10))
        self.assertEqual(msgs, [bytes([i]) + bytes(4) for i in range(3)])

    def test_server_streaming_with_metadata(self):
        call = self.server_stream(b"1:1", metadata=[("x-echo-s", "yes")], timeout=10)
        self.assertEqual(dict(call.initial_metadata()).get("x-echo-s"), "yes")
        self.assertEqual(list(call), [b"\x00"])

    def test_client_streaming(self):
        self.assertEqual(self.client_stream(iter([b"a", b"bb", b"ccc"]), timeout=10), b"3:6")

    def test_one_mebibyte_message_each_way(self):
        data = bytes(range(256)) * (MIB // 256)
        self.assertEqual(self.unary(data, timeout=60), data)

    def test_eight_mebibyte_message_each_way(self):
        data = bytes(range(256)) * (8 * MIB // 256)
        self.assertEqual(self.unary(data, timeout=120), data)

    def test_eight_mebibyte_server_stream(self):
        msgs = list(self.server_stream(b"1:%d" % (8 * MIB), timeout=120))
        self.assertEqual(len(msgs), 1)
        self.assertEqual(len(msgs[0]), 8 * MIB)

    def test_request_over_the_limit_is_refused(self):
        ch = grpc.insecure_channel("127.0.0.1:%d" % SMALL_PORT)
        try:
            stub = ch.unary_unary("/test.Echo/Unary", request_serializer=None, response_deserializer=None)
            with self.assertRaises(grpc.RpcError) as cm:
                stub(bytes(8 * MIB), timeout=60)
            self.assertEqual(cm.exception.code(), grpc.StatusCode.RESOURCE_EXHAUSTED)
            data = b"x" * MIB
            self.assertEqual(stub(data, timeout=60), data)
        finally:
            ch.close()

    def test_hundred_concurrent_calls(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as ex:
            futs = [ex.submit(self.unary, b"%d" % i, timeout=30) for i in range(100)]
            results = [f.result() for f in futs]
        self.assertEqual(results, [b"%d" % i for i in range(100)])


@unittest.skipUnless(HAVE_H2, "the h2 package is not installed")
class FrameTests(unittest.TestCase):
    def test_ping_is_acknowledged_with_its_data(self):
        c = RawH2(PORT)
        c.conn.ping(b"12345678")
        c.flush()
        evs = c.wait(lambda es: any(isinstance(e, h2.events.PingAckReceived) for e in es))
        acks = [e for e in evs if isinstance(e, h2.events.PingAckReceived)]
        self.assertTrue(any(a.ping_data == b"12345678" for a in acks), acks)
        c.sock.close()

    def test_settings_are_acknowledged_and_announced(self):
        c = RawH2(PORT)
        evs = c.wait(lambda es: any(isinstance(e, h2.events.SettingsAcknowledged) for e in es)
                     and any(isinstance(e, h2.events.RemoteSettingsChanged) for e in es))
        self.assertTrue(any(isinstance(e, h2.events.SettingsAcknowledged) for e in evs))
        self.assertEqual(c.conn.remote_settings.max_concurrent_streams, 100)
        c.sock.close()

    def test_unary_over_h2_frames(self):
        c = RawH2(PORT)
        c.conn.send_headers(1, grpc_headers("/test.Echo/Unary"), end_stream=False)
        c.conn.send_data(1, grpc_frame(b"raw"), end_stream=True)
        c.flush()
        r = c.collect(1)
        self.assertEqual(r["data"], grpc_frame(b"raw"))
        self.assertEqual(r["trailers"].get("grpc-status"), "0")
        c.sock.close()

    def test_rst_stream_drops_the_stream_and_keeps_the_connection(self):
        c = RawH2(PORT)
        c.conn.send_headers(1, grpc_headers("/test.Echo/Unary"), end_stream=False)
        c.conn.send_data(1, grpc_frame(b"partial"), end_stream=False)
        c.conn.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
        c.flush()
        c.conn.send_headers(3, grpc_headers("/test.Echo/Unary"), end_stream=False)
        c.conn.send_data(3, grpc_frame(b"after"), end_stream=True)
        c.flush()
        r = c.collect(3)
        self.assertEqual(r["data"], grpc_frame(b"after"))
        self.assertEqual(r["trailers"].get("grpc-status"), "0")
        self.assertFalse(any(getattr(e, "stream_id", None) == 1 and isinstance(e, h2.events.ResponseReceived) for e in c.events))
        c.sock.close()

    def test_big_header_block_is_split_into_continuations_both_ways(self):
        c = RawH2(PORT)
        big = "a" * 40000
        c.conn.send_headers(1, grpc_headers("/test.Echo/Unary", [("x-echo-big", big)]), end_stream=False)
        c.conn.send_data(1, grpc_frame(b"big"), end_stream=True)
        c.flush()
        r = c.collect(1)
        self.assertEqual(r["headers"].get("x-echo-big"), big)
        self.assertEqual(r["data"], grpc_frame(b"big"))
        c.sock.close()

    def test_padded_data_and_priority_headers(self):
        c = RawH2(PORT)
        c.conn.send_headers(1, grpc_headers("/test.Echo/Unary"), end_stream=False, priority_weight=10,
                            priority_depends_on=0, priority_exclusive=False)
        c.conn.send_data(1, grpc_frame(b"padded"), end_stream=True, pad_length=20)
        c.flush()
        r = c.collect(1)
        self.assertEqual(r["data"], grpc_frame(b"padded"))
        self.assertEqual(r["trailers"].get("grpc-status"), "0")
        c.sock.close()

    def test_streams_over_the_limit_are_refused(self):
        c = RawH2(PORT)
        # the h2 package would stop at the server's limit of 100 on its own, so lift it here
        c.conn.remote_settings[h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS] = 1000
        for i in range(101):
            c.conn.send_headers(1 + 2 * i, grpc_headers("/test.Echo/Unary"), end_stream=False)
        c.flush()
        r = c.collect(201)
        self.assertEqual(r["reset"], h2.errors.ErrorCodes.REFUSED_STREAM)
        c.sock.close()

    def test_server_honours_grpc_timeout(self):
        c = RawH2(PORT)
        c.conn.send_headers(1, grpc_headers("/test.Echo/Unary", [("grpc-timeout", "50m"), ("x-sleep-ms", "300")]), end_stream=False)
        c.conn.send_data(1, grpc_frame(b"late"), end_stream=True)
        c.flush()
        r = c.collect(1, timeout=10)
        status = r["trailers"].get("grpc-status") or r["headers"].get("grpc-status")
        message = r["trailers"].get("grpc-message") or r["headers"].get("grpc-message")
        self.assertEqual(status, "4")
        self.assertEqual(message, "past the deadline")
        c.sock.close()

    def test_wrong_content_type_is_415(self):
        c = RawH2(PORT)
        hs = [(":method", "POST"), (":scheme", "http"), (":path", "/test.Echo/Unary"), (":authority", "127.0.0.1"),
              ("content-type", "application/json")]
        c.conn.send_headers(1, hs, end_stream=True)
        c.flush()
        r = c.collect(1)
        self.assertEqual(r["headers"].get(":status"), "415")
        c.sock.close()

    def test_bad_preface_gets_goaway_and_close(self):
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        frames = read_frames(s)
        self.assertEqual(goaway_code(frames), 1)
        s.close()

    def test_data_on_stream_zero_is_a_protocol_error(self):
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        s.sendall(PREFACE + frame(4, 0, 0, b"") + frame(0, 0, 0, b"x"))
        self.assertEqual(goaway_code(read_frames(s)), 1)
        s.close()

    def test_oversize_frame_is_a_frame_size_error(self):
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        s.sendall(PREFACE + frame(4, 0, 0, b"") + frame(0, 0, 1, b"x" * 20000))
        self.assertEqual(goaway_code(read_frames(s)), 6)
        s.close()

    def test_settings_length_must_be_a_multiple_of_six(self):
        s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        s.sendall(PREFACE + frame(4, 0, 0, b"\x00\x03\x00"))
        self.assertEqual(goaway_code(read_frames(s)), 6)
        s.close()


if __name__ == "__main__":
    unittest.main()
