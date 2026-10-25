"""An A2A agent that offers only the gRPC binding (lf.a2a.v1), for tests/e2e.py, written with grpcio.

It serves the A2A service on a plaintext port (h2c) and, with a certificate and key, on a TLS port, and its cards
over HTTP on a third port:
  GET /card       a v1 card whose one interface is GRPC at http://127.0.0.1:<plaintext port>
  GET /tls-card   the same agent with its one interface at 127.0.0.1:<TLS port> (a bare target: TLS)
  GET /mtls-card  with a client CA too: the agent on a TLS port that requires a client certificate the CA signed
  GET /seen       the calls it received: method, metadata and the request's text
  POST /reset     forgets the calls

Methods (messages hand-encoded, field numbers from a2a-go v2.5.0's a2a.proto):
  SendMessage            a completed task with an artifact "echo: <text>"; the text "fail" is INTERNAL with
                         details (a Struct and an ErrorInfo, as a2a-go sends them); the text "hang" waits up to 6 s,
                         noting in /seen whether the caller cancelled the call first ("hang-cancelled") or not
  SendStreamingMessage   the task submitted, working, its artifact, completed; "fail-stream" sends one event and
                         then fails with details
  GetTask                the task, or NOT_FOUND "task not found" with an ErrorInfo TASK_NOT_FOUND {taskId}
  CancelTask             FAILED_PRECONDITION with an ErrorInfo TASK_NOT_CANCELABLE (every task here is done)
  SubscribeToTask        the task, then its final status
Anything else is UNIMPLEMENTED (grpcio's answer for an unknown method).

Usage: a2a_grpc_agent.py [CERT.pem KEY.pem [CLIENT_CA.pem]]; prints "ready <http port> <grpc port> <tls port>" (tls
port 0 without a certificate), and " <mtls port>" with a client CA. Ports are picked by the system.
"""
import http.server
import json
import os
import sys
import threading
from concurrent import futures

import grpc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grpc_details import error_info, status_bytes, struct_any  # noqa: E402

SERVICE = "lf.a2a.v1.A2AService"
DOMAIN = "a2a-protocol.org"
SUBMITTED, WORKING, COMPLETED = 1, 2, 3
ROLE_AGENT = 2

LOCK = threading.Lock()
SEEN = []
TASKS = {}
SEQ = [0]


# ---- protobuf wire ----

def varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def fld(num, payload):
    if isinstance(payload, str):
        payload = payload.encode()
    return varint(num << 3 | 2) + varint(len(payload)) + payload


def fnum(num, n):
    return varint(num << 3) + varint(n)


def parse(b):
    """field number -> list of values (ints for varints, bytes for length-delimited)."""
    out, i = {}, 0
    while i < len(b):
        k, i = read_varint(b, i)
        num, wt = k >> 3, k & 7
        if wt == 0:
            v, i = read_varint(b, i)
        elif wt == 2:
            n, i = read_varint(b, i)
            v, i = b[i:i + n], i + n
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError("bad wire type")
        out.setdefault(num, []).append(v)
    return out


def read_varint(b, i):
    n = shift = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return n, i


def first(fields, num, default=b""):
    return fields.get(num, [default])[0]


# ---- A2A messages ----

def part_text(text):
    return fld(1, text)


def message(mid, ctx, task, role, text):
    return fld(1, mid) + fld(2, ctx) + fld(3, task) + fnum(4, role) + fld(5, part_text(text))


def status(state, note=""):
    return fnum(1, state) + (fld(2, message("s-" + note, "", "", ROLE_AGENT, note)) if note else b"")


def artifact(text):
    return fld(1, "a-1") + fld(2, "echo") + fld(4, part_text(text))


def task_bytes(t, state=None):
    return fld(1, t["id"]) + fld(2, t["ctx"]) + fld(3, status(state if state is not None else t["state"])) + fld(4, artifact("echo: " + t["text"]))


def status_update(t, state):
    return fld(1, t["id"]) + fld(2, t["ctx"]) + fld(3, status(state))


def artifact_update(t):
    return fld(1, t["id"]) + fld(2, t["ctx"]) + fld(3, artifact("echo: " + t["text"])) + fnum(5, 1)


def incoming(req):
    """The text, message id and context id of a SendMessageRequest."""
    m = parse(first(parse(req), 2))
    parts = m.get(5, [])
    text = first(parse(parts[0]), 1).decode() if parts else ""
    return text, first(m, 1).decode(), first(m, 2).decode()


def new_task(text, ctx):
    with LOCK:
        SEQ[0] += 1
        t = {"id": "gt-%d" % SEQ[0], "ctx": ctx or "gc-%d" % SEQ[0], "text": text, "state": COMPLETED}
        TASKS[t["id"]] = t
    return t


def fail(context, code, msg, reason, metadata, hint=None):
    details = ([struct_any(hint)] if hint else []) + [error_info(reason, DOMAIN, metadata)]
    context.set_trailing_metadata((("grpc-status-details-bin", status_bytes(code.value[0], msg, details)),))
    context.abort(code, msg)


def note(method, context, text):
    md = {}
    for k, v in context.invocation_metadata():
        md[k] = v if isinstance(v, str) else "<binary>"
    with LOCK:
        SEEN.append({"method": method, "metadata": md, "text": text})


# ---- methods ----

def send_message(req, context):
    text, _, ctx = incoming(req)
    note("SendMessage", context, text)
    if text == "fail":
        fail(context, grpc.StatusCode.INTERNAL, "agent failed on request", "INTERNAL_ERROR", {"agent": "grpc-only"}, {"hint": "try again"})
    if text == "hang":
        import time
        t0 = time.time()
        while context.is_active() and time.time() - t0 < 6:
            time.sleep(0.05)
        note("SendMessage", context, "hang-cancelled" if not context.is_active() else "hang-finished")
    return fld(1, task_bytes(new_task(text, ctx)))


def send_streaming(req, context):
    text, _, ctx = incoming(req)
    note("SendStreamingMessage", context, text)
    t = new_task(text, ctx)
    yield fld(1, task_bytes(t, SUBMITTED))
    if text == "fail-stream":
        fail(context, grpc.StatusCode.INTERNAL, "the stream broke", "INTERNAL_ERROR", {"agent": "grpc-only"}, {"hint": "stream again"})
    yield fld(3, status_update(t, WORKING))
    yield fld(4, artifact_update(t))
    yield fld(3, status_update(t, COMPLETED))


def task_of(req, context, method):
    tid = first(parse(req), 2).decode()
    note(method, context, tid)
    t = TASKS.get(tid)
    if t is None:
        fail(context, grpc.StatusCode.NOT_FOUND, "task not found", "TASK_NOT_FOUND", {"taskId": tid})
    return t


def get_task(req, context):
    return task_bytes(task_of(req, context, "GetTask"))


def cancel_task(req, context):
    t = task_of(req, context, "CancelTask")
    fail(context, grpc.StatusCode.FAILED_PRECONDITION, "task %s is already done" % t["id"], "TASK_NOT_CANCELABLE", {"taskId": t["id"]})


def subscribe(req, context):
    t = task_of(req, context, "SubscribeToTask")
    yield fld(1, task_bytes(t))
    yield fld(3, status_update(t, COMPLETED))


class Handler(grpc.GenericRpcHandler):
    def service(self, details):
        name = details.method
        if not name.startswith("/" + SERVICE + "/"):
            return None
        m = name.split("/")[-1]
        if m == "SendMessage":
            return grpc.unary_unary_rpc_method_handler(send_message)
        if m == "SendStreamingMessage":
            return grpc.unary_stream_rpc_method_handler(send_streaming)
        if m == "GetTask":
            return grpc.unary_unary_rpc_method_handler(get_task)
        if m == "CancelTask":
            return grpc.unary_unary_rpc_method_handler(cancel_task)
        if m == "SubscribeToTask":
            return grpc.unary_stream_rpc_method_handler(subscribe)
        return None


# ---- cards ----

def card(url):
    return {
        "name": "grpc-only-agent",
        "description": "Echoes the text it is sent, over gRPC only",
        "version": "1.0.0",
        "supportedInterfaces": [{"url": url, "protocolBinding": "GRPC", "protocolVersion": "1.0"}],
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{"id": "echo", "name": "echo", "description": "Echoes the text", "tags": ["test"]}],
    }


def main():
    cert = key = client_ca = None
    if len(sys.argv) >= 3:
        cert, key = open(sys.argv[1], "rb").read(), open(sys.argv[2], "rb").read()
    if len(sys.argv) >= 4:
        client_ca = open(sys.argv[3], "rb").read()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16), handlers=[Handler()])
    gport = server.add_insecure_port("127.0.0.1:0")
    tport = server.add_secure_port("127.0.0.1:0", grpc.ssl_server_credentials([(key, cert)])) if cert else 0
    mport = server.add_secure_port("127.0.0.1:0", grpc.ssl_server_credentials([(key, cert)], root_certificates=client_ca, require_client_auth=True)) if client_ca else 0
    server.start()

    class Cards(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def answer(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/card":
                self.answer(200, card("http://127.0.0.1:%d" % gport))
            elif self.path == "/tls-card":
                self.answer(200, card("127.0.0.1:%d" % tport))
            elif self.path == "/mtls-card" and mport:
                self.answer(200, card("127.0.0.1:%d" % mport))
            elif self.path == "/seen":
                with LOCK:
                    self.answer(200, list(SEEN))
            else:
                self.answer(404, {"error": "no such path"})

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0") or 0))
            if self.path == "/reset":
                with LOCK:
                    SEEN.clear()
                self.answer(200, {})
            else:
                self.answer(404, {"error": "no such path"})

    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Cards)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    print("ready %d %d %d" % (web.server_address[1], gport, tport) + (" %d" % mport if client_ca else ""), flush=True)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
