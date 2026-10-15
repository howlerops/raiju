#!/usr/bin/env python3
"""End-to-end tests: runs the gateway against the mock upstream.

Usage: tests/e2e.py  (builds both binaries into ./build first)
"""
import base64, json, os, struct, subprocess, sys, time, urllib.request, urllib.error, urllib.parse, zlib

B64 = base64  # main() imports base64 locally, which would shadow this module

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
GW = "http://127.0.0.1:18098"
MOCK = "http://127.0.0.1:18099"
GW_B = "http://127.0.0.1:18097"
GW_D = "http://127.0.0.1:18092"

def build():
    os.makedirs(BUILD, exist_ok=True)
    for src, out in [("src/main.tov", "raiju"), ("tests/mock_upstream.tov", "mock_upstream")]:
        env = {**os.environ, "TOV_CFLAGS": os.environ.get("TOV_CFLAGS", "-DTV_PLAIN_ALLOC")}
        subprocess.run([os.environ.get("TOV", "tov"), "build", os.path.join(ROOT, src), "-o", os.path.join(BUILD, out)], check=True, capture_output=True, env=env)

ADMIN = {"authorization": "Bearer admin-secret"}

def call(method, path, body=None, headers=None, base=GW, auth=True):
    data = None if body is None else (body if isinstance(body, str) else json.dumps(body)).encode()
    extra = ADMIN if auth and base == GW and path.startswith("/api/") else {}
    req = urllib.request.Request(base + path, data=data, method=method, headers={"content-type": "application/json", **extra, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()

def wait(url):
    for _ in range(100):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.05)
    raise SystemExit(f"{url} never came up")

def ws_roundtrip(path, message, headers=None):
    """Minimal RFC 6455 client: handshake, one masked text frame, one reply."""
    import base64, os as _os, socket, struct
    sock = socket.create_connection(("127.0.0.1", 18098), timeout=5)
    key = base64.b64encode(_os.urandom(16)).decode()
    extra = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    sock.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n{extra}\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(1)
    status = int(head.split(b" ")[1])
    if status != 101:
        sock.close()
        return status, None
    payload = message.encode()
    mask = _os.urandom(4)
    n = len(payload)
    hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
    sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
    def read(k):
        buf = b""
        while len(buf) < k:
            buf += sock.recv(k - len(buf))
        return buf
    b0, b1 = read(2)
    ln = b1 & 0x7F
    if ln == 126:
        ln = struct.unpack(">H", read(2))[0]
    elif ln == 127:
        ln = struct.unpack(">Q", read(8))[0]
    data = read(ln).decode()
    sock.close()
    return 101, data

def call_bytes(method, path, body=None, headers=None, base=GW):
    """Like call(), but returns the body as bytes (for binary streams); the headers are a Message."""
    data = None if body is None else (body if isinstance(body, str) else json.dumps(body)).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()

def multipart(path, filename, data: bytes, fields=None, headers=None):
    """POSTs a multipart form: the file part plus text fields. Returns (status, body)."""
    boundary = "raiju-e2e-boundary"
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in (fields or {}).items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(GW + path, data=b"".join(parts), method="POST", headers={"content-type": f"multipart/form-data; boundary={boundary}", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def eventstream(data: bytes):
    """Decodes AWS event-stream frames, checking the prelude and message CRCs. Returns [(headers, payload)]."""
    out = []
    i = 0
    while i < len(data):
        if len(data) - i < 16:
            raise ValueError("truncated frame")
        total, hlen = struct.unpack(">II", data[i:i + 8])
        if zlib.crc32(data[i:i + 8]) != struct.unpack(">I", data[i + 8:i + 12])[0]:
            raise ValueError("bad prelude CRC")
        msg = data[i:i + total]
        if len(msg) != total or zlib.crc32(msg[:-4]) != struct.unpack(">I", msg[-4:])[0]:
            raise ValueError("bad message CRC")
        headers = {}
        j = i + 12
        while j < i + 12 + hlen:
            nl = data[j]
            name = data[j + 1:j + 1 + nl].decode()
            j += 1 + nl
            if data[j] != 7:
                raise ValueError("header type is not a string")
            vl = struct.unpack(">H", data[j + 1:j + 3])[0]
            headers[name] = data[j + 3:j + 3 + vl].decode()
            j += 3 + vl
        out.append((headers, msg[12 + hlen:-4]))
        i += total
    return out

def seen(traces=False):
    """What the mock received; trace exports arrive asynchronously, so they're left out unless asked for."""
    got = json.loads(call("GET", "/_seen", base=MOCK)[2])
    return [x for x in got if traces or x["path"] != "/v1/traces"]

FAILS = []

def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"\n     {detail}"))
    if not cond:
        FAILS.append(name)

def chat(model, extra=None, headers=None, **kw):
    body = {"model": model, "messages": [{"role": "user", "content": "hello"}], **kw}
    return call("POST", "/v1/chat/completions", body, headers)

def write_config():
    """The e2e config plus a Vertex provider whose service account uses the
    throwaway test key from src/jwt.tov's tests and a token URI on the mock."""
    import re
    cfg = json.load(open(os.path.join(ROOT, "tests/e2e.config.json")))
    src = open(os.path.join(ROOT, "src/jwt.tov")).read()
    pem = re.search(r"const TEST_PKCS8 = `(.*?)`", src, re.S).group(1)
    sa = {"type": "service_account", "client_email": "e2e@test.iam.gserviceaccount.com", "private_key": pem, "token_uri": MOCK + "/token"}
    # an HTTPS upstream with its own CA: trusted through ca_cert_pem, skipped with insecure_skip_verify, refused otherwise
    pem = make_tls()
    for name, nc in [("tls-ca", {"ca_cert_pem": pem}), ("tls-skip", {"insecure_skip_verify": True}), ("tls-none", {})]:
        cfg["providers"][name] = {"keys": [], "custom_provider_config": {"base_provider_type": "openai", "is_key_less": True}, "network_config": {"base_url": "https://127.0.0.1:18087", "max_retries": 0, **nc}}
    cfg["mcp"]["client_configs"].append({"name": "local", "connection_type": "stdio", "stdio_config": {"command": "python3", "args": [os.path.join(ROOT, "tests/mcp_stdio.py")], "env": {"MCP_GREETING": "hello"}}})
    # Azure's passthrough reaches the mock through the endpoint; the price sync is off, with a URL that 404s
    cfg["providers"]["azure"] = {"keys": [{"name": "az", "value": "az-key", "models": [], "weight": 1.0, "azure_key_config": {"endpoint": MOCK}}]}
    cfg["pricing_sync"] = {"url": MOCK + "/nodatasheet", "enabled": False}
    cfg["providers"]["vertex"] = {
        "keys": [{"name": "vx", "models": [], "weight": 1.0, "vertex_key_config": {"project_id": "proj", "region": "us-central1", "auth_credentials": json.dumps(sa)}}],
        "network_config": {"base_url": MOCK},
    }
    # Bedrock keys with an inference-profile ARN and with use_openai_endpoints, and a Mantle key, all on the mock
    cfg["providers"]["bedrock_arn"] = {"custom_provider_config": {"base_provider_type": "bedrock"}, "keys": [{"name": "bk-arn", "models": [], "weight": 1.0, "bedrock_key_config": {"access_key": "AKIDEXAMPLE", "secret_key": "secret", "region": "us-east-1", "arn": "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/abc123"}}], "network_config": {"base_url": MOCK}}
    cfg["providers"]["bedrock_oai"] = {"custom_provider_config": {"base_provider_type": "bedrock"}, "keys": [{"name": "bk-oai", "value": "bedrock-api-key", "models": [], "weight": 1.0, "bedrock_key_config": {"region": "us-east-1", "use_openai_endpoints": True}}], "network_config": {"base_url": MOCK}}
    cfg["providers"]["bedrock_mantle"] = {"keys": [{"name": "mk", "value": "mantle-key", "models": [], "weight": 1.0}], "network_config": {"base_url": MOCK}}
    # Bedrock files and batches: S3 and the job API on the mock, with a batch role and a default batch bucket
    cfg["providers"]["bedrock_batch"] = {"custom_provider_config": {"base_provider_type": "bedrock"}, "keys": [{"name": "bk-batch", "models": [], "weight": 1.0, "bedrock_key_config": {"access_key": "AKIDEXAMPLE", "secret_key": "secret", "region": "us-east-1", "batch_role_arn": "arn:aws:iam::123456789012:role/batch", "batch_s3_config": {"buckets": [{"bucket_name": "e2e-files", "prefix": "jobs", "is_default": True}]}}}], "network_config": {"base_url": MOCK}}
    path = os.path.join(BUILD, "e2e.config.json")
    json.dump(cfg, open(path, "w"))
    # a second node of the same cluster, without the file-writing features
    b = {k: v for k, v in cfg.items() if k not in ("audit", "logs_store", "alerts", "log_exports", "otel", "oidc")}
    b["cluster"] = {**cfg["cluster"], "node_id": "b", "peers": [GW]}
    json.dump(b, open(os.path.join(BUILD, "e2e.node-b.json"), "w"))
    # a single node with three workers: a 3-request limit and the response cache are shared between them
    w = {"client": {"enable_logging": False, "enforce_auth_on_inference": False}, "providers": {"openai": cfg["providers"]["openai"]}, "cache": {"enabled": True, "ttl_seconds": 60},
         "logs_store": {"enabled": True, "dir": os.path.join(BUILD, "e2e-wlogs")},
         "governance": {"rate_limits": [{"id": "w-rl", "request_max_limit": 3, "request_reset_duration": "1h"}], "virtual_keys": [{"id": "vk-w", "value": "sk-bf-workers", "rate_limit_id": "w-rl"}]}}
    json.dump(w, open(os.path.join(BUILD, "e2e.workers.json"), "w"))
    # a config in Bifrost's own dialect: inference auth on by default, top-level auth_config,
    # guardrails_config, pricing_overrides, and a section Raiju doesn't know
    bf = {"client": {"enable_logging": False}, "providers": {"openai": cfg["providers"]["openai"]},
          "auth_config": {"admin_username": "admin", "admin_password": "pw", "is_enabled": True},
          "governance": {"budgets": [{"id": "bb", "max_limit": 0.5, "reset_duration": "1d"}],
                         "virtual_keys": [{"id": "vk-bf", "value": "sk-bf-dialect", "budget_id": "bb"}],
                         "pricing_overrides": [{"id": "po1", "name": "custom", "scope_kind": "global", "match_type": "exact", "pattern": "custom-model", "request_types": ["chat_completion"], "pricing_patch": json.dumps({"input_cost_per_token": 0.1, "output_cost_per_token": 0.1})}]},
          "guardrails_config": {"guardrail_rules": [{"id": 1, "name": "r", "enabled": True, "cel_expression": "true", "apply_to": "input", "provider_config_ids": [1]}],
                                "guardrail_providers": [{"id": 1, "provider_name": "webhook", "policy_name": "hook", "enabled": True, "config": {"url": MOCK + "/guard-hook"}}]},
          "plugins": [{"name": "semantic_cache", "enabled": True, "config": {"provider": "openai", "embedding_model": "text-embedding-3-small", "threshold": 0.95, "ttl": "5m", "vector_store_namespace": "e2e-ns"}}],
          "vector_store": {"enabled": True, "type": "qdrant", "config": {"host": "127.0.0.1", "rest_port": 18089}},
          "server": {"port": 1}}
    json.dump(bf, open(os.path.join(BUILD, "e2e.bifrost.json"), "w"))
    # direct keys, per-request raw echo and prometheus_labels are switched on here only; the
    # provider keys are pool keys the callers' own keys must replace
    d = {"client": {"enable_logging": False, "enforce_auth_on_inference": True, "allow_direct_keys": True, "allow_per_request_raw_override": True,
                    "drop_excess_requests": True, "prometheus_labels": ["env", "team"]},
         "providers": {
             "openai": {"keys": [{"name": "pool", "value": "sk-pool", "models": [], "weight": 1.0}], "network_config": {"base_url": MOCK, "max_retries": 0}, "send_back_raw_response": True},
             "anthropic": {"keys": [{"name": "apool", "value": "sk-ant-pool", "models": [], "weight": 1.0}], "network_config": {"base_url": MOCK, "max_retries": 0}}},
         "governance": {"virtual_keys": [{"id": "vk-d", "value": "sk-bf-direct-vk"}]}}
    json.dump(d, open(os.path.join(BUILD, "e2e.direct.json"), "w"))
    # the semantic cache on Weaviate, Pinecone and chromem, in Bifrost's dialect, with two virtual keys
    vbase = {"client": {"enable_logging": False}, "providers": {"openai": cfg["providers"]["openai"]},
             "governance": {"virtual_keys": [{"id": "vk-a", "value": "sk-bf-a"}, {"id": "vk-b", "value": "sk-bf-b"}]}}
    for name, ns, vs, plugin in [
        ("weaviate", "E2eSemWeaviate", {"enabled": True, "type": "weaviate", "config": {"scheme": "http", "host": "127.0.0.1:18114", "api_key": "wv-key"}}, {}),
        ("pinecone", "e2e-sem-pinecone", {"enabled": True, "type": "pinecone", "config": {"api_key": "pc-key", "index_host": "127.0.0.1:18115"}}, {}),
        ("chromem", "E2eSemChromem", {"enabled": True, "type": "chromem", "config": {"path": os.path.join(BUILD, "e2e-chromem")}}, {"disable_identity_scoping": True}),
    ]:
        sc = {"provider": "openai", "embedding_model": "text-embedding-3-small", "threshold": 0.95, "ttl": "5m", "vector_store_namespace": ns, **plugin}
        json.dump({**vbase, "plugins": [{"name": "semanticcache", "enabled": True, "config": sc}], "vector_store": vs}, open(os.path.join(BUILD, f"e2e.vs-{name}.json"), "w"))
    return path

def make_tls():
    """A throwaway CA and a server certificate for 127.0.0.1 it signed; returns the CA's PEM."""
    d = os.path.join(BUILD, "e2e-tls")
    os.makedirs(d, exist_ok=True)
    run = lambda *a: subprocess.run(list(a), check=True, capture_output=True, cwd=d)
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem", "-days", "2", "-subj", "/CN=raiju-e2e-ca")
    run("openssl", "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "srv.key", "-out", "srv.csr", "-subj", "/CN=127.0.0.1")
    open(os.path.join(d, "ext.cnf"), "w").write("subjectAltName=IP:127.0.0.1\n")
    run("openssl", "x509", "-req", "-in", "srv.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-out", "srv.pem", "-days", "2", "-extfile", "ext.cnf")
    return open(os.path.join(d, "ca.pem")).read()

def start_tls_upstream():
    """An HTTPS chat upstream on 18087, with the certificate from make_tls."""
    import http.server, ssl, threading
    class T(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            body = json.dumps({"id": "t1", "object": "chat.completion", "created": 1, "model": "m", "choices": [{"index": 0, "message": {"role": "assistant", "content": "over tls"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})
            self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body.encode())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18087), T)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    d = os.path.join(BUILD, "e2e-tls")
    ctx.load_cert_chain(os.path.join(d, "srv.pem"), os.path.join(d, "srv.key"))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

def start_proxy():
    """An HTTP forward proxy stand-in on 18095 that records what it is asked for and answers itself."""
    import http.server, threading
    got = []
    class P(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", "0")))
            got.append({"target": self.path, "auth": self.headers.get("proxy-authorization", "")})
            body = json.dumps({"id": "p1", "object": "chat.completion", "created": 1, "model": "m", "choices": [{"index": 0, "message": {"role": "assistant", "content": "via proxy"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})
            self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body.encode())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18095), P)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, got

def start_idp():
    """A tiny OpenID provider on 18096: discovery, JWKS and a token endpoint that
    signs ID tokens with a throwaway RSA key (openssl)."""
    import base64, hashlib, http.server, threading, urllib.parse
    key = os.path.join(BUILD, "idp.key")
    subprocess.run(["openssl", "genrsa", "-out", key, "2048"], check=True, capture_output=True)
    mod = subprocess.run(["openssl", "rsa", "-in", key, "-noout", "-modulus"], check=True, capture_output=True, text=True).stdout.strip().split("=")[1]
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    jwks = json.dumps({"keys": [{"kty": "RSA", "kid": "k1", "use": "sig", "alg": "RS256", "n": b64(bytes.fromhex(mod)), "e": "AQAB"}]})
    iss = "http://127.0.0.1:18096"
    state = {"nonce": "", "verifier": "", "challenge": ""}
    def sign(claims):
        head = b64(json.dumps({"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode()) + "." + b64(json.dumps(claims).encode())
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key, "-binary"], input=head.encode(), check=True, capture_output=True).stdout
        return head + "." + b64(sig)
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def send(self, body, ctype="application/json"):
            self.send_response(200); self.send_header("content-type", ctype); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body.encode())
        def do_GET(self):
            if self.path == "/.well-known/openid-configuration":
                self.send(json.dumps({"issuer": iss, "authorization_endpoint": iss + "/authorize", "token_endpoint": iss + "/token", "jwks_uri": iss + "/jwks"}))
            elif self.path == "/jwks":
                self.send(jwks)
            else:
                self.send_response(404); self.end_headers()
        def do_POST(self):
            form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["content-length"])).decode())
            state["verifier"] = form.get("code_verifier", [""])[0]
            now = int(time.time())
            self.send(json.dumps({"token_type": "Bearer", "access_token": "at", "id_token": sign({"iss": iss, "aud": "raiju", "sub": "alice", "email": "alice@example.com", "iat": now, "exp": now + 300, "nonce": state["nonce"], "groups": ["staff", "raiju-editors"]})}))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 18096), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state

def serve(port, routes, tls=False):
    """A tiny HTTP(S) server on 127.0.0.1. routes(method, path, headers, body) -> (status, text, content type)."""
    import http.server, threading, ssl
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def handle_any(self):
            n = int(self.headers.get("content-length", "0") or 0)
            body = self.rfile.read(n).decode() if n else ""
            status, text, ctype = routes(self.command, self.path, self.headers, body)
            data = text.encode()
            self.send_response(status); self.send_header("content-type", ctype); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
        do_GET = do_POST = do_PUT = handle_any
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        d = os.path.join(BUILD, "e2e-tls")
        ctx.load_cert_chain(os.path.join(d, "srv.pem"), os.path.join(d, "srv.key"))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def der_ints(der):
    """r and s from a DER ECDSA signature (SEQUENCE of two INTEGERs)."""
    i = 2 + (der[1] & 0x7f if der[1] & 0x80 else 0)
    out = []
    for _ in range(2):
        ln = der[i + 1]
        out.append(int.from_bytes(der[i + 2:i + 2 + ln], "big"))
        i += 2 + ln
    return out

def jwt_es256(key, kid, claims):
    head = b64u(json.dumps({"alg": "ES256", "kid": kid, "typ": "JWT"}).encode()) + "." + b64u(json.dumps(claims).encode())
    der = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key], input=head.encode(), check=True, capture_output=True).stdout
    r, s = der_ints(der)
    return head + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

def jwt_rs256(key, kid, claims):
    head = b64u(json.dumps({"alg": "RS256", "kid": kid, "typ": "JWT"}).encode()) + "." + b64u(json.dumps(claims).encode())
    sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key, "-binary"], input=head.encode(), check=True, capture_output=True).stdout
    return head + "." + b64u(sig)

def discovery_and_proxy():
    """Cluster discovery (Consul, DNS, Kubernetes, etcd) against mock backends, and the identity-aware
    proxies (AWS ALB with ES256, Cloudflare Access with RS256 in full mode) with throwaway keys."""
    d = os.path.join(BUILD, "e2e-disc")
    os.makedirs(d, exist_ok=True)
    ca_pem = open(os.path.join(BUILD, "e2e-tls", "ca.pem")).read()
    now = int(time.time())
    # keys: P-256 for ALB, RSA for Cloudflare; the k8s service account token
    ec_key, ec_pub, rsa_key = os.path.join(d, "ec.key"), os.path.join(d, "ec.pub"), os.path.join(d, "rsa.key")
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", ec_key], check=True, capture_output=True)
    subprocess.run(["openssl", "ec", "-in", ec_key, "-pubout", "-out", ec_pub], check=True, capture_output=True)
    subprocess.run(["openssl", "genrsa", "-out", rsa_key, "2048"], check=True, capture_output=True)
    mod = subprocess.run(["openssl", "rsa", "-in", rsa_key, "-noout", "-modulus"], check=True, capture_output=True, text=True).stdout.strip().split("=")[1]
    jwks = json.dumps({"keys": [{"kty": "RSA", "kid": "e2e-rsa", "alg": "RS256", "use": "sig", "n": b64u(bytes.fromhex(mod)), "e": "AQAB"}]})
    ec_pem = open(ec_pub).read()
    token_file = os.path.join(d, "token")
    open(token_file, "w").write("e2e-sa-token\n")
    ALB_ARN = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/e2e-alb/50dc6c495c0c9188"
    KEYS = "https://127.0.0.1:18083"

    peer_nodes = []
    def peer(method, path, headers, body):
        if path == "/api/cluster/sync" and body:
            peer_nodes.append(json.loads(body).get("node", "?"))
        return 200, json.dumps({"node": "peer", "ts": 1, "counters": []}), "application/json"
    consul_regs = []
    def consul(method, path, headers, body):
        if method == "PUT" and path == "/v1/agent/service/register":
            consul_regs.append(json.loads(body))
            return 200, "{}", "application/json"
        if path.split("?")[0] == "/v1/health/service/bifrost":
            entries = [{"Service": {"ID": "bifrost-consul-a", "Address": "127.0.0.1", "Port": 18081}, "Node": {"Address": "127.0.0.1"}},
                       {"Service": {"ID": "bifrost-peer", "Address": "", "Port": 18084}, "Node": {"Address": "127.0.0.1"}}]
            return 200, json.dumps(entries), "application/json"
        return 404, "{}", "application/json"
    k8s_seen = []
    def k8s(method, path, headers, body):
        if path.startswith("/api/v1/namespaces/default/pods"):
            k8s_seen.append({"path": path, "auth": headers.get("authorization", "")})
            pods = {"items": [{"metadata": {"name": "a"}, "status": {"phase": "Running", "podIP": "127.0.0.1"}},
                              {"metadata": {"name": "b"}, "status": {"phase": "Pending", "podIP": "127.0.0.2"}}]}
            return 200, json.dumps(pods), "application/json"
        return 404, "{}", "application/json"
    kv = {}
    puts = []
    kv[base64.b64encode(b"/raiju/bifrost/etcd-peer").decode()] = base64.b64encode(json.dumps({"addr": "127.0.0.1", "port": 18084}).encode()).decode()
    def etcd(method, path, headers, body):
        req = json.loads(body) if body else {}
        j = lambda o: (200, json.dumps(o), "application/json")
        if path == "/v3/lease/grant":
            return j({"ID": "42", "TTL": "30"})
        if path == "/v3/lease/keepalive":
            return j({"result": {"ID": str(req.get("ID")), "TTL": "30" if req.get("ID") == "42" else "0"}})
        if path == "/v3/kv/put":
            kv[req["key"]] = req["value"]
            puts.append(base64.b64decode(req["key"]).decode())
            return j({})
        if path == "/v3/kv/range":
            lo = base64.b64decode(req["key"]).decode()
            hi = base64.b64decode(req["range_end"]).decode()
            hits = [{"key": k, "value": v} for k, v in kv.items() if lo <= base64.b64decode(k).decode() < hi]
            return j({"kvs": hits, "count": str(len(hits))} if hits else {"count": "0"})
        return 404, "{}", "application/json"
    def keys(method, path, headers, body):
        if path == "/e2e-ec":
            return 200, ec_pem, "application/x-pem-file"
        if path == "/cdn-cgi/access/certs":
            return 200, jwks, "application/json"
        return 404, "{}", "application/json"

    servers = [serve(18084, peer), serve(18085, consul), serve(18086, k8s), serve(18088, etcd), serve(18083, keys, tls=True)]
    cluster = lambda node, disc, port: {"client": {"enable_logging": False}, "cluster": {"enabled": True, "node_id": node, "secret": "e2e-disc", "interval_ms": 200, "peers": [], "discovery": disc}}
    cfgs = {
        "consul": (18081, cluster("consul-a", {"enabled": True, "type": "consul", "service_name": "bifrost", "consul_address": "127.0.0.1:18085", "bind_port": 18081, "advertise_address": "127.0.0.1"}, 18081)),
        "dns": (18080, cluster("dns-a", {"enabled": True, "type": "dns", "dns_names": ["localhost"], "bind_port": 18084}, 18080)),
        "k8s": (18082, cluster("k8s-a", {"enabled": True, "type": "kubernetes", "k8s_label_selector": "app=bifrost", "bind_port": 18084, "api_url": "http://127.0.0.1:18086", "token_file": token_file}, 18082)),
        "etcd": (18090, cluster("etcd-a", {"enabled": True, "type": "etcd", "service_name": "bifrost", "etcd_endpoints": ["http://127.0.0.1:18088"], "bind_port": 18090, "advertise_address": "127.0.0.1"}, 18090)),
        "alb": (18091, {"client": {"enable_logging": False}, "governance": {"users": [{"name": "alice@example.com", "role": "editor"}]},
                        "auth_proxy": {"enabled": True, "provider": "aws-alb", "mode": "login_only", "expected_signer": ALB_ARN, "region": "us-east-1", "public_key_base_url": KEYS, "ca_cert_pem": ca_pem}}),
        "cf": (18078, {"client": {"enable_logging": False}, "governance": {"users": [{"name": "ops@example.com", "role": "viewer"}]},
                       "oidc": {"enabled": False, "issuer": KEYS, "client_id": "raiju", "redirect_uri": "http://127.0.0.1:18078/cb", "role_claim": "groups", "role_map": {"raiju-editors": "editor"}},
                       "auth_proxy": {"enabled": True, "provider": "cloudflare-access", "mode": "full", "issuer_url": KEYS, "audience": "aud-e2e", "ca_cert_pem": ca_pem}}),
    }
    procs = []
    gws = {}
    try:
        for name, (port, cfg) in cfgs.items():
            path = os.path.join(d, name + ".json")
            json.dump(cfg, open(path, "w"))
            procs.append(subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", str(port), "-host", "127.0.0.1", "-config", path], env=os.environ.copy(), stderr=open(os.path.join(d, name + ".log"), "w")))
            gws[name] = f"http://127.0.0.1:{port}"
        for name in gws:
            wait(gws[name] + "/health")

        # discovery: each node's sync reaches the peer (which records the sender's node id)
        want = {"consul-a", "dns-a", "k8s-a", "etcd-a"}
        for _ in range(60):
            if want.issubset(set(peer_nodes)):
                break
            time.sleep(0.1)
        check("consul discovery finds the peer and syncs with it", "consul-a" in peer_nodes, sorted(set(peer_nodes)))
        check("dns discovery finds the peer and syncs with it", "dns-a" in peer_nodes, sorted(set(peer_nodes)))
        check("kubernetes discovery finds the running pod and syncs with it", "k8s-a" in peer_nodes, sorted(set(peer_nodes)))
        check("etcd discovery finds the registered peer and syncs with it", "etcd-a" in peer_nodes, sorted(set(peer_nodes)))
        reg = [r for r in consul_regs if r.get("ID") == "bifrost-consul-a"]
        check("consul: the node registers itself with a TCP check on its port", len(reg) > 0 and reg[0].get("Check", {}).get("TCP") == "127.0.0.1:18081" and reg[0].get("Port") == 18081, consul_regs[:1])
        check("kubernetes: lists pods by label with the service account token", any(x["path"] == "/api/v1/namespaces/default/pods?labelSelector=app%3Dbifrost" and x["auth"] == "Bearer e2e-sa-token" for x in k8s_seen), k8s_seen[:2])
        check("etcd: registers the node under a lease", base64.b64encode(b"/raiju/bifrost/etcd-a").decode() in kv and "/raiju/bifrost/etcd-a" in puts, puts[:3])

        # ALB: an ES256 token from the regional key endpoint (fetched on first use, so the first try can wait)
        alb = jwt_es256(ec_key, "e2e-ec", {"exp": now + 600, "iat": now, "signer": ALB_ARN, "iss": "https://oidc.example", "email": "alice@example.com", "sub": "a1"})
        hdr = {"x-amzn-oidc-data": alb}
        first = call("GET", "/api/config", headers=hdr, base=gws["alb"], auth=False)[0]
        s = first
        for _ in range(50):
            if s == 200:
                break
            time.sleep(0.1)
            s = call("GET", "/api/config", headers=hdr, base=gws["alb"], auth=False)[0]
        check("alb: the first request waits for the key, then the token opens the API", first == 401 and s == 200, (first, s))
        s = call("GET", "/api/users", headers=hdr, base=gws["alb"], auth=False)[0]
        check("alb: a provisioned editor may not manage users", s == 403, s)
        other = jwt_es256(ec_key, "e2e-ec", {"exp": now + 600, "iat": now, "signer": ALB_ARN.replace("e2e-alb", "other-alb"), "email": "alice@example.com"})
        s = call("GET", "/api/config", headers={"x-amzn-oidc-data": other}, base=gws["alb"], auth=False)[0]
        check("alb: a token signed for another load balancer is refused", s == 401, s)
        bob = jwt_es256(ec_key, "e2e-ec", {"exp": now + 600, "iat": now, "signer": ALB_ARN, "email": "bob@example.com"})
        s, _, b = call("GET", "/api/config", headers={"x-amzn-oidc-data": bob}, base=gws["alb"], auth=False)
        check("alb login only: an identity that is not provisioned gets 403", s == 403 and "not provisioned" in b, (s, b))
        s = call("GET", "/api/config", base=gws["alb"], auth=False)[0]
        check("alb: without the proxy header the normal sign-in applies", s == 401, s)

        # Cloudflare Access, full mode: the role comes from the groups claim through the SSO role map
        cf_ok = jwt_rs256(rsa_key, "e2e-rsa", {"exp": now + 600, "nbf": now - 10, "iss": KEYS, "aud": ["aud-e2e"], "email": "carol@example.com", "groups": ["raiju-editors"]})
        cf_hdr = {"Cf-Access-Jwt-Assertion": cf_ok}
        s = 0
        for _ in range(50):
            s = call("GET", "/api/config", headers=cf_hdr, base=gws["cf"], auth=False)[0]
            if s == 200:
                break
            time.sleep(0.1)
        check("cloudflare: an RS256 token from the team JWKS opens the API in full mode", s == 200, s)
        s = call("GET", "/api/users", headers=cf_hdr, base=gws["cf"], auth=False)[0]
        check("cloudflare full mode: the mapped editor may not manage users", s == 403, s)
        nobody = jwt_rs256(rsa_key, "e2e-rsa", {"exp": now + 600, "iss": KEYS, "aud": ["aud-e2e"], "email": "dan@example.com", "groups": ["strangers"]})
        s, _, b = call("GET", "/api/config", headers={"Cf-Access-Jwt-Assertion": nobody}, base=gws["cf"], auth=False)
        check("cloudflare full mode: a group with no role mapping is refused", s == 403 and "no role maps" in b, (s, b))
        wrong_aud = jwt_rs256(rsa_key, "e2e-rsa", {"exp": now + 600, "iss": KEYS, "aud": ["someone-else"], "email": "carol@example.com", "groups": ["raiju-editors"]})
        s = call("GET", "/api/config", headers={"Cf-Access-Jwt-Assertion": wrong_aud}, base=gws["cf"], auth=False)[0]
        check("cloudflare: a token for another audience is refused", s == 401, s)
    finally:
        for p in procs:
            p.terminate()
        for srv in servers:
            srv.shutdown()

def main():
    build()
    config = write_config()
    import shutil
    shutil.rmtree(os.path.join(ROOT, "build/e2e-logs"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build/e2e-audit"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build/e2e-wlogs"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build/e2e-chromem"), ignore_errors=True)
    env = {**os.environ, "E2E_OPENAI_KEY": "sk-from-env", "E2E_ADMIN_TOKEN": "admin-secret", "MOCK_PORT": "18099"}
    mock = subprocess.Popen([os.path.join(BUILD, "mock_upstream")], env=env, stdout=subprocess.DEVNULL)
    qdrant = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests/qdrant_mock.py"), "18089"])
    wait(MOCK + "/_seen")  # the gateway connects to the mock's MCP server at startup
    idp, idp_state = start_idp()
    proxy, proxied = start_proxy()
    tls_up = start_tls_upstream()
    gw = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18098", "-host", "127.0.0.1", "-config", config, "-server", os.environ.get("RAIJU_SERVER", "bun")], env=env, stderr=subprocess.DEVNULL)
    gw_bf = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18093", "-host", "127.0.0.1", "-config", os.path.join(BUILD, "e2e.bifrost.json")], env=env, stderr=open(os.path.join(BUILD, "e2e.bifrost.log"), "w"))
    gw_w = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18094", "-host", "127.0.0.1", "-config", os.path.join(BUILD, "e2e.workers.json"), "-workers", "3"], env=env, stderr=subprocess.DEVNULL)
    gw_b = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18097", "-host", "127.0.0.1", "-config", os.path.join(BUILD, "e2e.node-b.json")], env=env, stderr=subprocess.DEVNULL)
    gw_d = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18092", "-host", "127.0.0.1", "-config", os.path.join(BUILD, "e2e.direct.json")], env=env, stderr=open(os.path.join(BUILD, "e2e.direct.log"), "w"))
    weav = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests/weaviate_mock.py"), "18114"])
    pine = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests/pinecone_mock.py"), "18115"])
    def vs_gateway(name, port):
        return subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", str(port), "-host", "127.0.0.1", "-config", os.path.join(BUILD, f"e2e.vs-{name}.json")], env=env, stderr=open(os.path.join(BUILD, f"e2e.vs-{name}.log"), "w"))
    gw_vw = vs_gateway("weaviate", 18110)
    gw_vp = vs_gateway("pinecone", 18111)
    gw_vc = vs_gateway("chromem", 18112)
    try:
        wait(MOCK + "/_seen"); wait(GW + "/health"); wait(GW_B + "/health")

        s, h, b = chat("openai/gpt-4o-mini")
        r = json.loads(b)
        check("openai chat passes through", s == 200 and r["choices"][0]["message"]["content"] == "Hello from gpt-4o-mini", b)
        check("model reported as requested", r["model"] == "openai/gpt-4o-mini", b)
        check("env.VAR key used upstream", seen()[-1]["auth"] == "Bearer sk-from-env", seen()[-1])
        check("request id header", "x-bifrost-request-id" in {k.lower() for k in h}, h)
        check("upstream body has bare model and no gateway fields", json.loads(seen()[-1]["body"])["model"] == "gpt-4o-mini")

        s, h, b = chat("openai/gpt-4o-mini")
        check("second identical request is a cache hit", s == 200 and {k.lower(): v for k, v in h.items()}.get("x-bf-cache") == "hit", h)

        s, _, b = chat("anthropic/claude-sonnet-4", max_tokens=20)
        r = json.loads(b)
        check("anthropic translation", s == 200 and r["choices"][0]["message"]["content"] == "Hi from claude" and r["usage"]["prompt_tokens"] == 11, b)
        up = json.loads(seen()[-1]["body"])
        check("anthropic upstream body", up["model"] == "claude-sonnet-4" and up["max_tokens"] == 20 and seen()[-1]["auth"] == "sk-ant", up)

        s, _, b = chat("anthropic/claude-sonnet-4", max_tokens=4096, reasoning_effort="high", temperature=0.5, seed=91)
        up = json.loads(seen()[-1]["body"])
        check("reasoning_effort becomes an Anthropic thinking budget", s == 200 and up.get("thinking", {}).get("type") == "enabled" and 1024 <= up["thinking"]["budget_tokens"] < 4096 and "temperature" not in up, up)

        s, _, b = chat("gemini/gemini-2.5-flash", reasoning_effort="low", max_tokens=2000, seed=92)
        up = json.loads(seen()[-1]["body"])
        check("reasoning_effort becomes a Gemini thinking config", s == 200 and "thinkingBudget" in up.get("generationConfig", {}).get("thinkingConfig", {}), up)

        s, _, b = chat("gemini/gemini-2.5-flash")
        r = json.loads(b)
        check("gemini translation", s == 200 and r["choices"][0]["message"]["content"] == "Hi from gemini", b)
        check("gemini upstream path", seen()[-1]["path"] == "/v1beta/models/gemini-2.5-flash:generateContent", seen()[-1])

        s, _, b = chat("bedrock/claude")
        r = json.loads(b)
        check("bedrock translation", s == 200 and r["choices"][0]["message"]["content"] == "Hi from bedrock", b)
        last = seen()[-1]
        check("bedrock deployment + sigv4", last["path"] == "/model/anthropic.claude-3-haiku-20240307-v1:0/converse" and last["auth"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/") and "/us-west-2/bedrock/aws4_request" in last["auth"], last)

        s, _, b = chat("local/llama3")
        check("keyless custom provider", s == 200 and json.loads(b)["model"] == "local/llama3", b)

        s, _, b = chat("openai/flaky-1", temperature=0.1)
        check("retries a 503", s == 200, b)

        s, h, b = chat("openai/down-1", fallbacks=["anthropic/claude-fallback"])
        hl = {k.lower(): v for k, v in h.items()}
        check("falls back to the next model", s == 200 and json.loads(b)["choices"][0]["message"]["content"] == "Hi from claude" and hl.get("x-bf-fallback-used") == "anthropic/claude-fallback", (s, b, h))

        ok = all(chat("openai/rotate-me", seed=i)[0] == 200 for i in range(6))
        check("rotates off a key that gets 401", ok)

        s, h, b = call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "stream": True, "messages": [{"role": "user", "content": "s"}]})
        events = [e for e in b.split("\n\n") if e]
        check("openai streaming passthrough", s == 200 and events[-1] == "data: [DONE]" and '"content":"Hel"' in b, b)
        check("usage chunk hidden unless asked for", '"usage"' not in b, b)
        check("stream_options added upstream", json.loads(seen()[-1]["body"])["stream_options"] == {"include_usage": True})

        s, _, b = call("POST", "/v1/chat/completions", {"model": "anthropic/claude-sonnet-4", "stream": True, "stream_options": {"include_usage": True}, "messages": [{"role": "user", "content": "s"}]})
        # buffered servers replay the full answer as SSE; the http1 server converts Anthropic's own stream
        content = '"delta":{"content":"hi"}' if os.environ.get("RAIJU_SERVER", "http1") == "http1" else '"delta":{"content":"Hi from claude"}'
        check("non-openai streaming as SSE", s == 200 and content in b and '"usage":' in b and b.endswith("data: [DONE]\n\n"), b)

        s, _, b = call("POST", "/v1/embeddings", {"model": "openai/text-embedding-3-small", "input": "x"})
        check("embeddings", s == 200 and json.loads(b)["data"][0]["embedding"] == [0.1, 0.2], b)

        s, _, b = call("POST", "/anthropic/v1/messages", {"model": "claude-sonnet-4", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]})
        check("anthropic SDK route", s == 200 and json.loads(b)["content"][0]["text"] == "Hi from claude", b)

        s, _, b = call("POST", "/genai/v1beta/models/gemini-2.5-flash:generateContent", {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]})
        check("genai SDK route", s == 200 and "Hi from gemini" in b, b)

        s, _, b = call("POST", "/bedrock/model/claude/converse", {"messages": [{"role": "user", "content": [{"text": "hi"}]}]})
        check("bedrock SDK route", s == 200 and "Hi from bedrock" in b, b)

        # Cohere, GenAI and Bedrock SDK routes, with an OpenAI-format model behind them
        s, _, b = call("POST", "/cohere/v2/chat", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hello"}]})
        r = json.loads(b) if s == 200 else {}
        check("cohere chat answers in Cohere's shape", s == 200 and r.get("message", {}).get("role") == "assistant" and "Hello from gpt-4o-mini" in json.dumps(r.get("message", {}).get("content")), b)
        check("cohere chat sends an OpenAI chat body upstream", json.loads(seen()[-1]["body"])["model"] == "gpt-4o-mini" and seen()[-1]["path"] == "/v1/chat/completions", seen()[-1])
        s, _, b = call("POST", "/cohere/v2/chat", {"model": "openai/gpt-4o-mini", "stream": True, "messages": [{"role": "user", "content": "s"}]})
        names = [l[7:] for l in b.split("\n") if l.startswith("event: ")]
        check("cohere chat streams message-start to message-end", s == 200 and names[:1] == ["message-start"] and names[-1:] == ["message-end"] and "content-delta" in names and "Hel" in b, (s, names, b[:300]))
        s, _, b = call("POST", "/cohere/v2/embed", {"model": "openai/text-embedding-3-small", "texts": ["one", "two"], "input_type": "search_document", "embedding_types": ["float"]})
        vecs = json.loads(b).get("embeddings", {}).get("float", []) if s == 200 else []
        check("cohere embed returns one float vector per text", s == 200 and len(vecs) == 2 and all(len(v) == 64 for v in vecs), b[:300])
        check("cohere embed sends the texts as an OpenAI input list", json.loads(seen()[-1]["body"])["input"] == ["one", "two"] and seen()[-1]["path"] == "/v1/embeddings", seen()[-1])
        s, _, b = call("POST", "/cohere/v2/rerank", {"model": "raiju/lexical", "query": "capital of France", "documents": ["bananas are yellow", "Paris is the capital of France"]})
        results = json.loads(b).get("results", []) if s == 200 else []
        check("cohere rerank puts the best document first", s == 200 and len(results) == 2 and results[0].get("index") == 1, b[:300])
        s, _, b = call("POST", "/cohere/v1/tokenize", {"model": "command-r", "text": "hello world"})
        r = json.loads(b) if s == 200 else {}
        check("cohere tokenize returns tokens and their strings", s == 200 and len(r.get("tokens", [])) > 0 and len(r.get("tokens", [])) == len(r.get("token_strings", [])), b[:300])

        GEN = "/genai/v1beta/models/openai/gpt-4o-mini"
        s, _, b = call("POST", GEN + ":generateContent", {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]})
        r = json.loads(b) if s == 200 else {}
        cand = (r.get("candidates") or [{}])[0]
        check("genai generateContent to an OpenAI model", s == 200 and cand.get("content", {}).get("parts", [{}])[0].get("text") == "Hello from gpt-4o-mini" and cand.get("finishReason") == "STOP" and r.get("usageMetadata", {}).get("promptTokenCount") == 3, b[:400])
        check("genai sends an OpenAI chat body upstream", json.loads(seen()[-1]["body"])["model"] == "gpt-4o-mini" and seen()[-1]["path"] == "/v1/chat/completions", seen()[-1])
        s, _, b = call("POST", GEN + ":streamGenerateContent", {"contents": [{"role": "user", "parts": [{"text": "s"}]}]})
        chunks = [json.loads(l[6:]) for l in b.split("\n") if l.startswith("data: ")]
        text = "".join(p.get("text", "") for c in chunks for cand in c.get("candidates", []) for p in cand.get("content", {}).get("parts", []))
        check("genai streamGenerateContent streams the text and a STOP", s == 200 and text == "Hello" and any(cand.get("finishReason") == "STOP" for c in chunks for cand in c.get("candidates", [])), b[:400])
        s, _, b = call("POST", GEN + ":countTokens", {"contents": [{"role": "user", "parts": [{"text": "hello world, how are you today"}]}]})
        check("genai countTokens", s == 200 and json.loads(b).get("totalTokens", 0) > 0, b)
        s, _, b = call("GET", "/genai/v1beta/models")
        names = [m["name"] for m in json.loads(b).get("models", [])] if s == 200 else []
        check("genai models list", s == 200 and "models/openai/rotate-me" in names, b[:300])
        s, _, b = call("GET", "/genai/v1beta/models/openai/rotate-me")
        r = json.loads(b) if s == 200 else {}
        check("genai model info", s == 200 and r.get("name") == "models/openai/rotate-me" and "generateContent" in r.get("supportedGenerationMethods", []), b[:300])

        # GenAI SDK files, batches, cached contents, operations, :predict and rank
        def lower(h):
            return {k.lower(): v for k, v in h.items()}
        def jget(b):
            try:
                return json.loads(b)
            except ValueError:
                return {}
        UP = {"x-goog-upload-protocol": "resumable", "x-goog-upload-command": "start", "x-goog-upload-header-content-type": "application/jsonl"}
        OAI = {"x-model-provider": "openai"}
        # Gemini (the default): the resumable upload goes to Gemini with the key, and its URL is the gateway's
        s, h, b = call("POST", "/genai/upload/v1beta/files", {"file": {"displayName": "resumable"}}, {**UP, "x-goog-upload-header-content-length": "5"})
        up_url = lower(h).get("x-goog-upload-url", "")
        check("genai gemini upload start answers with the gateway's upload URL", s == 200 and "/genai/upload/v1beta/files?upload_id=" in up_url, (s, h, b))
        check("genai gemini upload start goes to Gemini with the key", seen()[-1]["path"] == "/upload/v1beta/files" and seen()[-1]["auth"] == "g-key" and seen()[-1]["body"] == "start", seen()[-1:])
        s, h, b = call("POST", "/genai/upload/v1beta/files?upload_id=" + up_url.split("upload_id=")[1], "hello", {"x-goog-upload-command": "upload, finalize", "x-goog-upload-offset": "0", "content-type": "application/jsonl"})
        gfile = jget(b).get("file", {})
        check("genai gemini upload finishes at Gemini's answer", s == 200 and gfile.get("name", "").startswith("files/g-") and gfile.get("state") == "ACTIVE", (s, b))
        check("genai gemini upload bytes go to the upload URL with the key", seen()[-1]["path"] == "/upload/v1beta/files" and seen()[-1]["auth"] == "g-key" and seen()[-1]["body"] == "finalize upload, finalize", seen()[-1:])
        gname = gfile.get("name", "files/none")[len("files/"):]
        s, _, b = call("GET", "/genai/v1beta/files")
        check("genai gemini files list passes through", s == 200 and seen()[-1]["path"] == "/v1beta/files" and seen()[-1]["auth"] == "g-key" and "files" in jget(b), (s, b))
        s, _, b = call("GET", "/genai/v1beta/files/" + gname)
        check("genai gemini file retrieve passes through", s == 200 and seen()[-1]["path"] == "/v1beta/files/" + gname and jget(b).get("name") == "files/" + gname, (s, b))
        s, _, b = call("DELETE", "/genai/v1beta/files/" + gname)
        check("genai gemini file delete passes through", s == 200 and seen()[-1]["path"] == "/v1beta/files/" + gname and seen()[-1]["auth"] == "g-key", (s, b))

        # OpenAI: the upload is one OpenAI file upload, answered as a Gemini File
        s, h, b = call("POST", "/genai/upload/v1beta/files", {"file": {"displayName": "in.jsonl"}}, {**UP, **OAI, "x-goog-upload-header-content-length": "5"})
        up_url = lower(h).get("x-goog-upload-url", "")
        check("genai openai upload start answers with the gateway's upload URL", s == 200 and "/genai/upload/v1beta/files?upload_id=" in up_url, (s, h, b))
        s, h, b = call("POST", "/genai/upload/v1beta/files?upload_id=" + up_url.split("upload_id=")[1], "hello", {"x-goog-upload-command": "upload, finalize", "content-type": "application/jsonl"})
        ofile = jget(b).get("file", {})
        check("genai openai upload answers a Gemini File with the final status", s == 200 and ofile.get("name", "").startswith("files/file-") and ofile.get("displayName") == "in.jsonl" and ofile.get("mimeType") == "application/jsonl" and ofile.get("sizeBytes") == "5" and lower(h).get("x-goog-upload-status") == "final", (s, h, b))
        check("genai openai upload is one OpenAI file upload with purpose batch", seen()[-1]["path"] == "/v1/files" and '"purpose"' not in seen()[-1]["body"], seen()[-1:])
        oname = ofile.get("name", "files/none")[len("files/"):]
        s, _, b = call("GET", "/genai/v1beta/files/" + oname, None, OAI)
        check("genai openai file retrieve is a Gemini File", s == 200 and jget(b).get("name") == "files/" + oname and jget(b).get("state") == "ACTIVE" and seen()[-1]["path"] == "/v1/files/" + oname, (s, b))
        s, _, b = call("GET", "/genai/v1beta/files", None, OAI)
        check("genai openai files list is Gemini's list", s == 200 and any(f.get("name") == "files/" + oname for f in jget(b).get("files", [])), (s, b[:300]))
        s, _, b = call("DELETE", "/genai/v1beta/files/" + oname, None, OAI)
        check("genai openai file delete answers an empty object", s == 200 and jget(b) == {} and seen()[-1]["path"] == "/v1/files/" + oname, (s, b))

        # OpenAI batches: inline requests become a batch input file; its custom ids are the keys
        inline = {"batch": {"displayName": "d", "inputConfig": {"requests": {"requests": [
            {"request": {"contents": [{"role": "user", "parts": [{"text": "one"}]}]}, "metadata": {"key": "k1"}},
            {"request": {"contents": [{"role": "user", "parts": [{"text": "two"}]}]}, "metadata": {"key": "k2"}}]}}}}
        s, _, b = call("POST", "/genai/v1beta/models/openai/gpt-4o-mini:batchGenerateContent", inline)
        op = jget(b)
        check("genai batch to an OpenAI model is a finished operation", s == 200 and op.get("name", "").startswith("batches/batch_") and op.get("done") is True and op.get("metadata", {}).get("state") == "BATCH_STATE_SUCCEEDED", (s, b))
        check("genai batch creates an OpenAI batch on the uploaded file", seen()[-1]["path"] == "/v1/batches" and json.loads(seen()[-1]["body"]).get("endpoint") == "/v1/chat/completions" and seen()[-2]["path"] == "/v1/files", seen()[-2:])
        bname = op.get("name", "batches/none")[len("batches/"):]
        outf = op.get("dest", {}).get("fileName", "")
        s, _, b = call("GET", "/v1/files/" + outf + "/content")
        outs = [json.loads(l) for l in b.split("\n") if l.strip()] if s == 200 else []
        check("genai batch input lines are chat requests keyed by the metadata keys", sorted(o["custom_id"] for o in outs) == ["k1", "k2"], (s, b[:300]))
        s, _, b = call("GET", "/genai/v1beta/batches/" + bname, None, OAI)
        check("genai batch retrieve is a Gemini operation", s == 200 and jget(b).get("done") is True and jget(b).get("name") == "batches/" + bname and seen()[-1]["path"] == "/v1/batches/" + bname, (s, b))
        s, _, b = call("GET", "/genai/v1beta/batches", None, OAI)
        check("genai batch list answers operations", s == 200 and any(o.get("name") == "batches/" + bname for o in jget(b).get("operations", [])), (s, b[:300]))
        # a batch that reads an uploaded file: the file's lines are the requests
        s, h, b = call("POST", "/genai/upload/v1beta/files", {"file": {"displayName": "reqs.jsonl"}}, {**UP, **OAI})
        fup = lower(h).get("x-goog-upload-url", "")
        s, _, b = call("POST", "/genai/upload/v1beta/files?upload_id=" + fup.split("upload_id=")[1], '{"key":"f1","request":{"contents":[{"role":"user","parts":[{"text":"x"}]}]}}\n', {"x-goog-upload-command": "upload, finalize"})
        fname = jget(b).get("file", {}).get("name", "files/none")
        s, _, b = call("POST", "/genai/v1beta/models/openai/gpt-4o-mini:batchGenerateContent", {"batch": {"inputConfig": {"fileName": fname}}})
        op2 = jget(b)
        check("genai batch reads an uploaded file's lines", s == 200 and op2.get("done") is True, (s, b))
        s, _, b = call("GET", "/v1/files/" + op2.get("dest", {}).get("fileName", "") + "/content")
        check("genai batch from a file keeps its key as custom id", s == 200 and '"custom_id":"f1"' in b, (s, b[:300]))
        s, _, b = call("POST", "/genai/v1beta/models/openai/gpt-4o-mini:batchGenerateContent", {"batch": {"inputConfig": {"fileName": "files/file-nope"}}})
        check("genai batch from an unknown file is a 404", s == 404, (s, b))
        s, _, b = call("POST", "/genai/v1beta/batches/" + bname + ":cancel", {}, OAI)
        check("genai batch cancel on OpenAI answers an empty object", s == 200 and jget(b) == {} and seen()[-1]["path"] == "/v1/batches/" + bname + "/cancel", (s, b))
        s, _, b = call("DELETE", "/genai/v1beta/batches/" + bname, None, OAI)
        check("genai batch delete is Bifrost's unsupported error on OpenAI", s == 400 and "batch_delete is not supported by openai provider" in b, (s, b))

        # Gemini batches pass through: create, poll, list, cancel and delete
        s, _, b = call("POST", "/genai/v1beta/models/gemini-2.5-flash:batchGenerateContent", inline)
        gop = jget(b)
        check("genai gemini batch create passes through", s == 200 and seen()[-1]["path"] == "/v1beta/models/gemini-2.5-flash:batchGenerateContent" and seen()[-1]["auth"] == "g-key" and gop.get("done") is True, (s, b))
        gb = gop.get("name", "batches/none")[len("batches/"):]
        s, _, b = call("GET", "/genai/v1beta/batches/" + gb)
        check("genai gemini batch retrieve passes through", s == 200 and seen()[-1]["path"] == "/v1beta/batches/" + gb and jget(b).get("done") is True, (s, b))
        s, _, b = call("GET", "/genai/v1beta/batches")
        check("genai gemini batch list passes through", s == 200 and seen()[-1]["path"] == "/v1beta/batches", (s, b))
        s, _, b = call("POST", "/genai/v1beta/batches/" + gb + ":cancel", {})
        check("genai gemini batch cancel passes through", s == 200 and seen()[-1]["path"] == "/v1beta/batches/" + gb + ":cancel", (s, b))
        s, _, b = call("DELETE", "/genai/v1beta/batches/" + gb)
        check("genai gemini batch delete passes through", s == 200 and seen()[-1]["path"] == "/v1beta/batches/" + gb and seen()[-1]["auth"] == "g-key", (s, b))

        # cached contents: Gemini's, through; other providers answer Bifrost's error
        cc = {"model": "models/gemini-2.5-flash", "contents": [{"role": "user", "parts": [{"text": "long context"}]}], "ttl": "600s"}
        s, _, b = call("POST", "/genai/v1beta/cachedContents", cc)
        check("genai cached content create passes through", s == 200 and seen()[-1]["path"] == "/v1beta/cachedContents" and json.loads(seen()[-1]["body"]).get("model") == "models/gemini-2.5-flash" and jget(b).get("name") == "cachedContents/c-1", (s, b))
        s, _, b = call("GET", "/genai/v1beta/cachedContents")
        check("genai cached content list passes through", s == 200 and seen()[-1]["path"] == "/v1beta/cachedContents", (s, b))
        s, _, b = call("GET", "/genai/v1beta/cachedContents/c-1")
        check("genai cached content retrieve passes through", s == 200 and seen()[-1]["path"] == "/v1beta/cachedContents/c-1", (s, b))
        s, _, b = call("PATCH", "/genai/v1beta/cachedContents/c-1", {"ttl": "900s"})
        check("genai cached content update passes through", s == 200 and seen()[-1]["path"] == "/v1beta/cachedContents/c-1" and json.loads(seen()[-1]["body"]).get("ttl") == "900s", (s, b))
        s, _, b = call("DELETE", "/genai/v1beta/cachedContents/c-1")
        check("genai cached content delete passes through", s == 200 and seen()[-1]["path"] == "/v1beta/cachedContents/c-1", (s, b))
        s, _, b = call("POST", "/genai/v1beta/cachedContents", cc, OAI)
        check("genai cached content on OpenAI is Bifrost's unsupported error", s == 400 and "cached_content_create is not supported by openai provider" in b, (s, b))

        # operations: Gemini's pass through; OpenAI has no video operations here
        s, _, b = call("GET", "/genai/v1beta/models/veo-3/operations/op-9")
        check("genai operation retrieve passes through", s == 200 and seen()[-1]["path"] == "/v1beta/models/veo-3/operations/op-9" and seen()[-1]["auth"] == "g-key", (s, b))
        s, _, b = call("GET", "/genai/v1beta/models/openai/veo-3/operations/op-9")
        check("genai operation retrieve on OpenAI is Bifrost's unsupported error", s == 400 and "video_retrieve is not supported by openai provider" in b, (s, b))

        # :predict: Gemini passes through; an embedding model embeds, an Imagen model makes images
        s, _, b = call("POST", "/genai/v1beta/models/text-embedding-004:predict", {"instances": [{"content": "alpha"}]})
        check("genai predict passes through to Gemini", s == 200 and seen()[-1]["path"] == "/v1beta/models/text-embedding-004:predict" and json.loads(seen()[-1]["body"])["instances"][0]["content"] == "alpha", (s, b))
        s, _, b = call("POST", "/genai/v1beta/models/openai/text-embedding-3-small:predict", {"instances": [{"content": "alpha"}, {"content": "beta"}]})
        preds = jget(b).get("predictions", []) if s == 200 else []
        check("genai predict embeds on an OpenAI model", s == 200 and len(preds) == 2 and len(preds[0].get("embeddings", {}).get("values", [])) == 64, (s, b[:300]))
        check("genai predict sends the texts as an embeddings input", seen()[-1]["path"] == "/v1/embeddings" and json.loads(seen()[-1]["body"])["input"] == ["alpha", "beta"], seen()[-1:])
        s, _, b = call("POST", "/genai/v1beta/models/openai/imagen-3:predict", {"instances": [{"prompt": "a red fox"}], "parameters": {"sampleCount": 1}})
        check("genai predict with an Imagen model makes images", s == 200 and jget(b).get("predictions", [{}])[0].get("bytesBase64Encoded") == "iVBORw0KGgo=" and seen()[-1]["path"] == "/v1/images/generations" and '"response_format":"b64_json"' in seen()[-1]["body"], (s, b[:300]))

        # /genai/v1/rank: the rerank of a lexical model, in Vertex's rank shape
        rk = {"model": "raiju/lexical", "query": "capital of France", "records": [{"id": "a", "content": "bananas are yellow"}, {"id": "b", "title": "Paris", "content": "Paris is the capital of France"}]}
        s, _, b = call("POST", "/genai/v1/rank", rk)
        recs = jget(b).get("records", []) if s == 200 else []
        check("genai rank puts the best record first with its id", s == 200 and [r.get("id") for r in recs] == ["b", "a"] and recs[0].get("title") == "Paris", (s, b))
        s, _, b = call("POST", "/genai/v1/rank", dict(rk, ignoreRecordDetailsInResponse=True))
        check("genai rank can leave out the record details", s == 200 and "content" not in jget(b).get("records", [{}])[0], (s, b))
        s, _, b = call("POST", "/genai/v1/rank", {"query": "q", "records": [{"id": "a", "content": "x"}]})
        check("genai rank needs a model", s == 400, (s, b))

        # the GenAI routes that stay with genai(): models and generateContent keep their answers
        s, _, b = call("GET", "/genai/v1beta/models/openai/rotate-me")
        check("genai model info still answers after the new routes", s == 200 and jget(b).get("name") == "models/openai/rotate-me", (s, b[:200]))

        BED = "/bedrock/model/openai%2Fgpt-4o-mini/"
        conv = {"messages": [{"role": "user", "content": [{"text": "hi"}]}]}
        s, _, b = call("POST", BED + "converse", conv)
        r = json.loads(b) if s == 200 else {}
        check("bedrock converse to an OpenAI model", s == 200 and r.get("output", {}).get("message", {}).get("content", [{}])[0].get("text") == "Hello from gpt-4o-mini" and r.get("stopReason") == "end_turn" and r.get("usage", {}).get("inputTokens") == 3, b[:400])
        check("bedrock converse sends an OpenAI chat body upstream", json.loads(seen()[-1]["body"])["model"] == "gpt-4o-mini" and seen()[-1]["path"] == "/v1/chat/completions", seen()[-1])
        s, h, raw = call_bytes("POST", BED + "converse-stream", conv)
        try:
            frames = eventstream(raw)
        except ValueError:
            frames = []
        names = [hd.get(":event-type") for hd, _ in frames]
        text = "".join(json.loads(p)["delta"]["text"] for hd, p in frames if hd.get(":event-type") == "contentBlockDelta")
        meta = [json.loads(p) for hd, p in frames if hd.get(":event-type") == "metadata"]
        check("bedrock converse-stream frames have valid CRCs and events", s == 200 and h.get("content-type") == "application/vnd.amazon.eventstream" and names == ["messageStart", "contentBlockDelta", "contentBlockDelta", "contentBlockStop", "messageStop", "metadata"] and text == "Hello" and all(hd.get(":message-type") == "event" for hd, _ in frames) and meta and meta[0]["usage"]["inputTokens"] == 3, (s, names, raw[:80]))
        check("bedrock converse-stream asks the upstream to stream", json.loads(seen()[-1]["body"]).get("stream") is True, seen()[-1])
        COUNT = {"input": {"converse": {"messages": [{"role": "user", "content": [{"text": "hello there, friend"}]}]}}}
        s, _, b = call("POST", BED + "count-tokens", COUNT)
        check("bedrock count-tokens (another provider: the estimate, inexact)", s == 200 and json.loads(b).get("inputTokens", 0) > 0 and json.loads(b).get("exact") is False, b)
        s, _, b = call("POST", "/bedrock/model/claude/count-tokens", COUNT)
        check("bedrock count-tokens is Bedrock's exact count", s == 200 and json.loads(b) == {"inputTokens": 17, "exact": True} and seen()[-1]["path"] == "/model/anthropic.claude-3-haiku-20240307-v1:0/count-tokens", (s, b, seen()[-1:]))
        s, _, b = call("POST", "/bedrock/model/unsupported-model/count-tokens", COUNT)
        check("bedrock count-tokens falls back to the estimate for a model Bedrock cannot count", s == 200 and json.loads(b).get("exact") is False and json.loads(b).get("inputTokens", 0) > 0, (s, b))
        s, h, raw = call_bytes("POST", BED + "invoke-with-response-stream", {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 20, "messages": [{"role": "user", "content": "hi"}]})
        try:
            frames = eventstream(raw)
        except ValueError:
            frames = []
        events = [json.loads(B64.b64decode(json.loads(p)["bytes"])) for hd, p in frames if hd.get(":event-type") == "chunk"]
        check("bedrock invoke-with-response-stream wraps Messages events", s == 200 and events[:1] and events[0]["type"] == "message_start" and events[-1]["type"] == "message_stop" and any(e.get("delta", {}).get("text") == "Hel" for e in events), (s, raw[:80]))

        # Bedrock rerank: /v1/rerank with a Bedrock model, in the caller's shape; and /bedrock/rerank in Bedrock's
        s, _, b = call("POST", "/v1/rerank", {"model": "bedrock/cohere.rerank-v3-5:0", "query": "q", "documents": ["a", "b"], "top_n": 1})
        r = json.loads(b) if s == 200 else {}
        check("rerank through a Bedrock model", s == 200 and r.get("results", [{}])[0].get("index") == 1 and r["results"][0].get("relevance_score") == 0.9 and r["results"][0].get("document") == {"text": "b"}, (s, b[:300]))
        check("rerank posts to agent-runtime with the model's ARN", seen()[-1]["path"] == "/rerank" and "arn:aws:bedrock:us-west-2::foundation-model/cohere.rerank-v3-5:0" in seen()[-1]["body"], seen()[-1])
        WIRE = {"queries": [{"type": "TEXT", "textQuery": {"text": "q"}}], "sources": [{"type": "INLINE", "inlineDocumentSource": {"type": "TEXT", "textDocument": {"text": t}}} for t in ["a", "b"]], "rerankingConfiguration": {"type": "BEDROCK_RERANKING_MODEL", "bedrockRerankingConfiguration": {"modelConfiguration": {"modelArn": "arn:aws:bedrock:us-west-2::foundation-model/cohere.rerank-v3-5:0"}, "numberOfResults": 1}}}
        s, _, b = call("POST", "/bedrock/rerank", WIRE)
        check("bedrock rerank route answers in Bedrock's shape", s == 200 and json.loads(b) == {"results": [{"index": 1, "relevanceScore": 0.9}, {"index": 0, "relevanceScore": 0.2}]}, (s, b[:300]))

        # an inference-profile ARN on the key: the ARN joins the model in the path
        s, _, b = chat("bedrock_arn/anthropic.claude-3-haiku-20240307-v1:0")
        check("bedrock key ARN reaches the converse path", s == 200 and "abc123" in seen()[-1]["path"] and seen()[-1]["path"].endswith("/converse") and "/us-east-1/bedrock/aws4_request" in seen()[-1]["auth"], (s, seen()[-1]))

        # use_openai_endpoints: OpenAI-family chat goes to the OpenAI route with the key's bearer; other families stay on Converse
        s, _, b = chat("bedrock_oai/openai.gpt-5.5")
        r = json.loads(b) if s == 200 else {}
        check("use_openai_endpoints sends an OpenAI model to the OpenAI route", s == 200 and r["choices"][0]["message"]["content"] == "Hello from openai.gpt-5.5" and seen()[-1]["path"] == "/openai/v1/chat/completions" and seen()[-1]["auth"] == "Bearer bedrock-api-key" and json.loads(seen()[-1]["body"])["model"] == "openai.gpt-5.5", (s, b[:200], seen()[-1:]))
        s, _, b = chat("bedrock_oai/anthropic.claude-3-haiku-20240307-v1:0")
        check("use_openai_endpoints leaves Claude on Converse", s == 200 and seen()[-1]["path"].endswith("/converse"), seen()[-1:])

        # Bedrock Mantle: OpenAI-family models on the OpenAI surface, Claude on the native Messages surface
        s, _, b = chat("bedrock_mantle/openai.gpt-5.5")
        r = json.loads(b) if s == 200 else {}
        check("mantle OpenAI-family chat", s == 200 and r["choices"][0]["message"]["content"] == "Hello from openai.gpt-5.5" and seen()[-1]["path"] == "/openai/v1/chat/completions" and seen()[-1]["auth"] == "Bearer mantle-key", (s, b[:200]))
        s, _, b = chat("bedrock_mantle/anthropic.claude-haiku-4-5", max_tokens=20)
        r = json.loads(b) if s == 200 else {}
        check("mantle Anthropic-family chat goes to the native Messages path", s == 200 and r["choices"][0]["message"]["content"] == "Hi from mantle claude" and r["usage"]["prompt_tokens"] == 6 and seen()[-1]["path"] == "/anthropic/v1/messages" and json.loads(seen()[-1]["body"])["model"] == "anthropic.claude-haiku-4-5", (s, b[:200], seen()[-1:]))

        s, _, b = call("GET", "/v1/models", headers={"x-bf-list-models-provider": "openai"})
        ids = [m["id"] for m in json.loads(b)["data"]]
        check("models list", s == 200 and "openai/rotate-me" in ids, b)

        # governance
        lim = {"x-bf-vk": "sk-bf-limited"}
        codes = [chat("openai/gpt-4o-mini", headers=lim, seed=100 + i)[0] for i in range(3)]
        check("rate limit", codes == [200, 200, 429], codes)
        s, _, b = chat("anthropic/claude-sonnet-4", headers={"authorization": "Bearer sk-bf-openai"})
        check("virtual key provider allowlist", s == 403, (s, b))
        bud = {"x-api-key": "sk-bf-budget"}
        first = chat("openai/gpt-4o-mini", headers=bud, seed=200)[0]
        second = chat("openai/gpt-4o-mini", headers=bud, seed=201)[0]
        check("budget exhausts", first == 200 and second == 402, (first, second))

        st, reply = ws_roundtrip("/v1/realtime?model=openai/gpt-realtime", '{"type":"session.update"}')
        r = json.loads(reply or "{}")
        check("realtime relays events with the provider key", st == 101 and r.get("event") == '{"type":"session.update"}' and r.get("auth", "").startswith("Bearer sk-from-env") and "model=gpt-realtime" in r.get("auth", ""), (st, reply))
        st, _ = ws_roundtrip("/v1/realtime?model=anthropic/claude", "{}")
        check("realtime refuses providers without a realtime API", st == 400, st)

        # Anthropic SDK route to a non-Anthropic provider
        s, _, b = call("POST", "/anthropic/v1/messages", {"model": "openai/gpt-4o-mini", "max_tokens": 20, "system": "be brief", "messages": [{"role": "user", "content": "hi"}]})
        r = json.loads(b)
        check("anthropic route reaches openai", s == 200 and r.get("type") == "message" and r["content"][0]["text"] == "Hello from gpt-4o-mini" and r["usage"]["input_tokens"] == 3, b)
        up = json.loads(seen()[-1]["body"])
        check("anthropic route sends an openai chat body", up["messages"][0] == {"role": "system", "content": "be brief"} and up["model"] == "gpt-4o-mini", up)
        s, _, b = call("POST", "/anthropic/v1/messages", {"model": "openai/gpt-4o-mini", "max_tokens": 20, "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        types = [l[7:] for l in b.split("\n") if l.startswith("event: ")]
        check("anthropic route streams anthropic events", s == 200 and types[0] == "message_start" and types[-1] == "message_stop" and '"text":"Hel"' in b, b[:600])

        # Responses API
        s, _, b = call("POST", "/v1/responses", {"model": "openai/gpt-4o-mini", "input": "hi"})
        check("responses passes through to openai", s == 200 and "native responses" in b and seen()[-1]["path"] == "/v1/responses" and json.loads(seen()[-1]["body"])["model"] == "gpt-4o-mini", b)
        s, _, b = call("POST", "/v1/responses", {"model": "anthropic/claude-sonnet-4", "instructions": "terse", "input": "hi", "max_output_tokens": 30})
        r = json.loads(b)
        check("responses translated for anthropic", s == 200 and r["object"] == "response" and r["output"][0]["content"][0]["text"] == "Hi from claude" and r["usage"]["input_tokens"] == 11, b)
        check("responses instructions become system", json.loads(seen()[-1]["body"])["system"] == "terse", seen()[-1]["body"])
        s, _, b = call("POST", "/v1/responses", {"model": "gemini/gemini-2.5-flash", "input": "hi", "stream": True})
        evs = [l[7:] for l in b.split("\n") if l.startswith("event: ")]
        check("responses streaming for gemini", s == 200 and evs[0] == "response.created" and "response.output_text.delta" in evs and evs[-1] == "response.completed", b[:500])

        # Vertex: service-account JWT exchanged for a token, then generateContent
        s, _, b = chat("vertex/gemini-2.5-flash")
        check("vertex gemini via service account", s == 200 and json.loads(b)["choices"][0]["message"]["content"] == "Hi from vertex", b)
        tok = [x for x in seen() if x["path"] == "/token"]
        last = seen()[-1]
        check("vertex token request is a jwt-bearer grant", len(tok) == 1 and "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=ey" in tok[0]["body"], tok)
        check("vertex call uses the token and project path", last["auth"] == "Bearer ya29.test-token" and last["path"] == "/v1/projects/proj/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent", last)
        chat("vertex/gemini-2.5-flash", seed=1)
        check("vertex token is cached", len([x for x in seen() if x["path"] == "/token"]) == 1)

        # Guardrails redact PII before it leaves the gateway
        s, _, b = call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "mail jane@example.com or call 415-555-2671"}]})
        sent = json.loads(seen()[-1]["body"])["messages"][0]["content"]
        check("guardrails redact the prompt", s == 200 and "jane@example.com" not in sent and "[REDACTED:EMAIL]" in sent, sent)

        # Routing rules
        s, h, b = chat("openai/gpt-4o-mini", headers={"x-tier": "premium"}, seed=300)
        hl = {k.lower(): v for k, v in h.items()}
        check("routing rule sends premium traffic to anthropic", s == 200 and json.loads(b)["choices"][0]["message"]["content"] == "Hi from claude" and hl.get("x-bf-routing-rule") == "premium-to-claude", (s, b, h))
        s, _, b = chat("openai/gpt-4o-mini", seed=301)
        check("other traffic is unaffected by the rule", json.loads(b)["choices"][0]["message"]["content"] == "Hello from gpt-4o-mini", b)

        s, _, b = call("GET", "/api/health")
        check("health status endpoint", s == 200 and "targets" in json.loads(b), b)

        # Request logs
        s, _, b = call("GET", "/api/logs?provider=anthropic&limit=5")
        r = json.loads(b)
        check("request logs are queryable", s == 200 and r["total"] >= 1 and all(e["provider"] == "anthropic" for e in r["entries"]), b[:400])
        s, _, b = call("GET", "/api/logs?status=error")
        check("failed requests are logged with their error", s == 200 and any(e.get("error") for e in json.loads(b)["entries"]), b[:400])
        chat("openai/gpt-4o-mini", seed=1801, headers={"x-bf-disable-content-logging": "true", "x-request-id": "req-nocontent"}, messages=[{"role": "user", "content": "private words"}])
        chat("openai/gpt-4o-mini", seed=1802, headers={"x-request-id": "req-content"}, messages=[{"role": "user", "content": "public words"}])
        _, _, lb = call("GET", "/api/logs?limit=20")
        check("x-bf-disable-content-logging keeps a request's bodies out of the log", "private words" not in lb and "public words" in lb and "req-nocontent" in lb, lb[:400])
        s, _, b = call("GET", "/api/logs/stats")
        st = json.loads(b)
        check("log stats", s == 200 and st["requests"] > 10 and st["tokens"] > 0, b[:300])
        files = os.listdir(os.path.join(ROOT, "build/e2e-logs"))
        check("logs persisted as daily JSONL", len(files) == 1 and files[0].startswith("requests-") and files[0].endswith(".jsonl"), files)

        # Traces: a server span per request and a client span per upstream attempt, honoring traceparent
        tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        chat("openai/gpt-4o-mini", headers={"traceparent": tp}, seed=400)
        time.sleep(0.3)
        upstream = [x for x in seen() if x["path"] == "/v1/chat/completions"][-1]
        traces = [x["body"] for x in seen(traces=True) if x["path"] == "/v1/traces"]
        joined = "".join(traces)
        check("spans exported over OTLP/HTTP", len(traces) > 0 and '"resourceSpans"' in joined and "raiju-e2e" in joined, traces[:1])
        check("inbound traceparent continues the trace", "0af7651916cd43dd8448eb211c80319c" in joined and '"parentSpanId":"b7ad6b7169203331"' in joined, joined[:300])
        check("gen_ai attributes on spans", '"gen_ai.request.model"' in joined and '"gen_ai.usage.input_tokens"' in joined, joined[:300])

        # MCP: tools from connected servers are injected into chat requests and can be executed
        s, _, b = call("GET", "/api/mcp")
        st = json.loads(b)["clients"]
        check("mcp server connected at startup", s == 200 and st and st[0]["connected"] and st[0]["tools"] == 1, b)
        chat("openai/gpt-4o-mini", seed=500)
        tools = json.loads(seen()[-1]["body"]).get("tools", [])
        check("mcp tools injected into chat", any(t["function"]["name"] == "weather-get_weather" and t["function"]["parameters"]["required"] == ["city"] for t in tools), tools)
        chat("openai/gpt-4o-mini", headers={"x-bf-mcp-include-clients": "none"}, seed=501)
        check("x-bf-mcp-include-clients none skips injection", "tools" not in json.loads(seen()[-1]["body"]), seen()[-1]["body"][:200])
        s, _, b = call("POST", "/v1/mcp/tool/execute", {"id": "call_1", "type": "function", "function": {"name": "weather-get_weather", "arguments": "{\"city\":\"Oslo\"}"}})
        r = json.loads(b)
        check("mcp tool execution", s == 200 and r == {"role": "tool", "tool_call_id": "call_1", "content": "Sunny in Oslo"}, b)
        mcp_calls = [x for x in seen() if x["path"] == "/mcp"]
        check("mcp tools/call sent upstream", '"method":"tools/call"' in mcp_calls[-1]["body"] and '"city":"Oslo"' in mcp_calls[-1]["body"], mcp_calls[-1])
        loc = [c for c in st if c["name"] == "local"]
        check("a stdio MCP server is started and connected", loc and loc[0]["connected"] and loc[0]["tools"] == 1, st)
        s, _, b = call("POST", "/v1/mcp/tool/execute", {"id": "call_3", "type": "function", "function": {"name": "local-echo", "arguments": "{\"text\":\"ping\"}"}})
        check("a stdio MCP tool runs in the child process with its environment", s == 200 and "hello: ping (pid " in b, b)
        sec = [c for c in st if c["name"] == "secure"]
        check("an OAuth-protected MCP server connects with a client-credentials token", sec and sec[0]["connected"] and sec[0]["tools"] == 1, st)
        s, _, b = call("POST", "/v1/mcp/tool/execute", {"id": "call_2", "type": "function", "function": {"name": "secure-get_weather", "arguments": "{\"city\":\"Oslo\"}"}})
        toks = [x for x in seen() if x["path"] == "/oauth/token"]
        # one token per node (the cluster test runs a second gateway), reused for every RPC
        check("OAuth MCP tool runs on the cached token", s == 200 and "Sunny in Oslo" in b and len(toks) <= 2 and all(t["auth"] == "Basic cmFpanU6czNjcmV0" for t in toks), (b, len(toks)))

        # Media pass-through keeps binary bodies and content types
        req = urllib.request.Request(GW + "/v1/audio/speech", data=json.dumps({"model": "openai/tts-1", "input": "hi", "voice": "alloy"}).encode(), method="POST", headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            audio = res.read(); ctype = res.headers.get("content-type")
        check("audio speech pass-through", audio == bytes([0x49, 0x44, 0x33, 0xff, 0xfb, 0x90, 0x00, 0x80, 0xc3, 0x28]) and ctype == "audio/mpeg" and json.loads(seen()[-1]["body"])["model"] == "tts-1", (audio, ctype))

        # --- Anthropic SDK batches, files and models; Gemini files, batches, images and speech ---
        def bline(cid, model):
            return json.dumps({"custom_id": cid, "method": "POST", "url": "/v1/chat/completions", "body": {"model": model, "messages": [{"role": "user", "content": "hi"}]}})
        msg = [{"role": "user", "content": "hi"}]
        oa = {"x-model-provider": "openai"}
        # create -> get -> results against an OpenAI-format provider (through media.tov's files and batches)
        s, _, b = call("POST", "/anthropic/v1/messages/batches", {"requests": [{"custom_id": "a", "params": {"model": "gpt-4o-mini", "max_tokens": 10, "messages": msg}}]}, oa)
        mb = json.loads(b) if s == 200 else {}
        bid = mb.get("id", "")
        sent = [x["path"] for x in seen()[-2:]]
        check("anthropic batch create goes through an OpenAI-format provider", s == 200 and mb.get("type") == "message_batch" and mb.get("processing_status") == "ended" and mb.get("request_counts", {}).get("succeeded") == 1 and mb.get("results_url", "").endswith(f"/anthropic/v1/messages/batches/{bid}/results") and sent == ["/v1/files", "/v1/batches"] and json.loads(seen()[-1]["body"])["endpoint"] == "/v1/chat/completions", (s, b, sent))
        s, _, b = call("GET", f"/anthropic/v1/messages/batches/{bid}", headers=oa)
        check("anthropic batch retrieve on an OpenAI-format provider", s == 200 and json.loads(b).get("id") == bid and json.loads(b).get("processing_status") == "ended", (s, b))
        s, _, b = call("GET", f"/anthropic/v1/messages/batches/{bid}/results", headers=oa)
        res = [json.loads(x) for x in b.split("\n") if x.strip()]
        check("anthropic batch results from an OpenAI-format provider", s == 200 and len(res) == 1 and res[0]["custom_id"] == "a" and res[0]["result"]["type"] == "succeeded" and res[0]["result"]["message"]["content"][0]["text"] == "Batch reply from gpt-4o-mini", (s, b))
        s, _, b = call("POST", "/anthropic/v1/messages/batches", {"requests": [{"custom_id": "x", "params": {"model": "gpt-4o", "messages": msg}}, {"custom_id": "y", "params": {"model": "gpt-4o-mini", "messages": msg}}]}, oa)
        check("a batch with two models is refused in Anthropic's error shape", s == 400 and json.loads(b)["error"]["type"] == "invalid_request_error", (s, b))
        # Anthropic target: the body goes upstream unchanged, results come back as Anthropic sends them
        s, _, b = call("POST", "/anthropic/v1/messages/batches", {"requests": [{"custom_id": "c1", "params": {"model": "claude-sonnet-4", "max_tokens": 10, "messages": msg}}]})
        ab = json.loads(b) if s == 200 else {}
        abid = ab.get("id", "")
        up = seen()[-1]
        check("anthropic batch create passes through unchanged", s == 200 and ab.get("processing_status") == "in_progress" and abid.startswith("msgbatch_") and up["path"] == "/v1/messages/batches" and up["auth"] == "sk-ant" and json.loads(up["body"])["requests"][0]["params"]["model"] == "claude-sonnet-4", (s, b, up))
        s, _, b = call("GET", f"/anthropic/v1/messages/batches/{abid}/results")
        res = [json.loads(x) for x in b.split("\n") if x.strip()]
        check("anthropic batch results pass through", s == 200 and len(res) == 1 and res[0]["custom_id"] == "c1" and res[0]["result"]["message"]["content"][0]["text"] == "Batch reply from claude-sonnet-4", (s, b))
        # Anthropic files: upload and list pass through
        s, b = multipart("/anthropic/v1/files", "batch.jsonl", b'{"custom_id":"f1"}\n', {"purpose": "batch"})
        af = json.loads(b) if s == 200 else {}
        check("anthropic file upload passes through", s == 200 and af.get("id", "").startswith("file_") and af.get("type") == "file" and seen()[-1]["auth"] == "sk-ant", (s, b))
        s, _, b = call("GET", "/anthropic/v1/files")
        check("anthropic file list includes the upload", s == 200 and af.get("id") in [x["id"] for x in json.loads(b)["data"]], (s, b[:300]))
        # models: Anthropic's own list, and an OpenAI-format provider's in Anthropic's shape
        s, _, b = call("GET", "/anthropic/v1/models")
        check("anthropic models pass through", s == 200 and "claude-sonnet-4" in [m["id"] for m in json.loads(b)["data"]], (s, b[:300]))
        s, _, b = call("GET", "/anthropic/v1/models", headers=oa)
        check("an OpenAI-format provider's models in Anthropic's shape", s == 200 and [m["id"] for m in json.loads(b)["data"]] == ["m-a", "m-b"] and json.loads(b)["data"][0]["type"] == "model", (s, b[:300]))
        s, _, b = call("GET", "/anthropic/v1/models/m-b", headers=oa)
        check("one model from an OpenAI-format provider", s == 200 and json.loads(b).get("id") == "m-b" and json.loads(b).get("type") == "model", (s, b))
        s, _, b = call("GET", "/anthropic/v1/models/nope", headers=oa)
        check("an unknown model is a 404 in Anthropic's shape", s == 404 and json.loads(b)["error"]["type"] == "not_found_error", (s, b))
        # Gemini through /v1/files and /v1/batches (x-bf-provider), to the batch's results
        gem = {"x-bf-provider": "gemini"}
        gin = bline("g1", "gemini-2.5-flash") + "\n"
        s, b = multipart("/v1/files", "gemini.jsonl", gin.encode(), {"purpose": "batch"}, gem)
        gf = json.loads(b) if s == 200 else {}
        gfid = gf.get("id", "")
        check("gemini file upload is OpenAI-shaped", s == 200 and gfid.startswith("g-") and gf.get("object") == "file" and gf.get("bytes") == len(gin), (s, b))
        s, _, b = call("POST", "/v1/batches", {"input_file_id": gfid, "endpoint": "/v1/chat/completions", "completion_window": "24h"}, gem)
        gb = json.loads(b) if s == 200 else {}
        gbid = gb.get("id", "")
        check("gemini batch created from an uploaded file", s == 200 and gbid.startswith("gb-") and gb.get("status") == "completed" and gb.get("output_file_id") == "raiju-batch-output-" + gbid, (s, b))
        s, _, b = call("GET", "/v1/batches/" + gbid, headers=gem)
        check("gemini batch retrieve", s == 200 and json.loads(b).get("status") == "completed", (s, b))
        s, _, b = call("GET", "/v1/files/raiju-batch-output-" + gbid + "/content", headers=gem)
        out = [json.loads(x) for x in b.split("\n") if x.strip()]
        check("gemini batch results are OpenAI's batch output", s == 200 and len(out) == 1 and out[0]["custom_id"] == "g1" and out[0]["response"]["body"]["choices"][0]["message"]["content"] == "Batch reply from gemini-2.5-flash", (s, b[:400]))
        gp = [x for x in seen() if x["path"].endswith(":batchGenerateContent")]
        check("gemini batch went to batchGenerateContent with the uploaded requests", gp and '"metadata":{"key":"g1"}' in gp[-1]["body"], gp[-1:] )
        s, _, b = call("GET", "/v1/files/" + gfid + "/content", headers=gem)
        check("gemini uploaded files are not served back", s == 400, (s, b))
        # Gemini images: Imagen's :predict, and a Gemini image model's generateContent
        s, _, b = call("POST", "/v1/images/generations", {"model": "gemini/imagen-3.0-generate-002", "prompt": "a red fox", "n": 1, "size": "1024x1024"})
        r = json.loads(b) if s == 200 else {}
        check("imagen returns base64 image data", s == 200 and r.get("data", [{}])[0].get("b64_json") == "iVBORw0KGgo=" and seen()[-1]["path"] == "/v1beta/models/imagen-3.0-generate-002:predict" and '"sampleCount":1' in seen()[-1]["body"], (s, b))
        s, _, b = call("POST", "/v1/images/generations", {"model": "gemini/gemini-2.5-flash-image", "prompt": "a red fox", "size": "1024x1024"})
        r = json.loads(b) if s == 200 else {}
        check("a gemini image model returns inline image data", s == 200 and r.get("data", [{}])[0].get("b64_json") == "iVBORw0KGgo=" and seen()[-1]["path"] == "/v1beta/models/gemini-2.5-flash-image:generateContent" and '"IMAGE"' in seen()[-1]["body"], (s, b))
        # Gemini speech: a WAV file (RIFF header, 4 bytes of PCM from the mock)
        s, h, audio = call_bytes("POST", "/v1/audio/speech", {"model": "gemini/gemini-2.5-flash-preview-tts", "input": "hi", "voice": "Kore"})
        check("gemini speech returns a WAV", s == 200 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE" and h.get("content-type") == "audio/wav" and struct.unpack("<I", audio[40:44])[0] == 4 and audio[44:] == bytes([0, 1, 2, 3]), (s, audio[:44]))
        # Gemini speech-to-text: the audio inline in generateContent, the transcript as OpenAI's JSON or text
        s, b = multipart("/v1/audio/transcriptions", "talk.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ", {"model": "gemini/gemini-2.5-flash", "prompt": "Transcribe."})
        check("gemini transcription returns OpenAI's JSON", s == 200 and json.loads(b) == {"text": "Hi from gemini"}, (s, b))
        stt = seen()[-1]
        check("gemini transcription sends the audio inline", stt["path"] == "/v1beta/models/gemini-2.5-flash:generateContent" and '"inlineData":{"mimeType":"audio/wav","data":"UklGRgAAAABXQVZFZm10IA=="}' in stt["body"] and '"text":"Transcribe."' in stt["body"], stt)
        s, b = multipart("/v1/audio/transcriptions", "talk.mp3", b"ID3", {"model": "gemini/gemini-2.5-flash", "response_format": "text"})
        check("gemini transcription as plain text", s == 200 and b == "Hi from gemini", (s, b))
        s, b = multipart("/v1/audio/transcriptions", "talk.wav", b"RIFF", {"model": "gemini/gemini-2.5-flash", "response_format": "srt"})
        check("gemini transcription refuses srt in OpenAI's error shape", s == 400 and json.loads(b)["error"]["type"] == "invalid_request_error", (s, b))
        # Vertex images: Imagen's :predict with the service account's bearer token
        s, _, b = call("POST", "/v1/images/generations", {"model": "vertex/imagen-3.0-generate-002", "prompt": "a red fox", "n": 1})
        r = json.loads(b) if s == 200 else {}
        vx = seen()[-1]
        check("vertex imagen returns base64 image data", s == 200 and r.get("data", [{}])[0].get("b64_json") == "iVBORw0KGgo=" and vx["path"] == "/v1/projects/proj/locations/us-central1/publishers/google/models/imagen-3.0-generate-002:predict" and vx["auth"] == "Bearer ya29.test-token", (s, b, vx))
        s, _, b = call("POST", "/v1/images/generations", {"model": "vertex/gemini-2.5-flash-image", "prompt": "a red fox"})
        check("vertex gemini image model returns inline image data", s == 200 and json.loads(b)["data"][0]["b64_json"] == "iVBORw0KGgo=" and seen()[-1]["path"].endswith("/models/gemini-2.5-flash-image:generateContent"), (s, b))
        s, _, b = call("POST", "/v1/images/generations", {"model": "vertex/imagen-3.0-generate-002"})
        check("vertex images need a prompt", s == 400, (s, b))
        # Bedrock images: Titan's TEXT_IMAGE body, signed with the key's credentials
        s, _, b = call("POST", "/v1/images/generations", {"model": "bedrock/amazon.titan-image-generator-v2:0", "prompt": "a red fox", "size": "512x512", "quality": "high"})
        r = json.loads(b) if s == 200 else {}
        bx = seen()[-1]
        check("bedrock titan returns base64 image data, signed", s == 200 and r.get("data", [{}])[0].get("b64_json") == "iVBORw0KGgo=" and bx["path"] == "/model/amazon.titan-image-generator-v2:0/invoke" and bx["auth"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/") and '"taskType":"TEXT_IMAGE"' in bx["body"] and '"quality":"premium"' in bx["body"], (s, b, bx))
        # Batch results, as Bifrost's body: the output lines of an OpenAI-format batch, a Gemini batch and an Anthropic batch
        s, b = multipart("/v1/files", "results.jsonl", (bline("o1", "gpt-4o-mini") + "\n").encode(), {"purpose": "batch"})
        ofid = json.loads(b).get("id", "") if s == 200 else ""
        s, _, b = call("POST", "/v1/batches", {"input_file_id": ofid, "endpoint": "/v1/chat/completions", "completion_window": "24h"})
        obid = json.loads(b).get("id", "") if s == 200 else ""
        s, _, b = call("GET", f"/v1/batches/{obid}/results")
        ores = json.loads(b) if s == 200 else {}
        check("openai batch results as Bifrost's results body", s == 200 and ores.get("batch_id") == obid and [x["custom_id"] for x in ores.get("results", [])] == ["o1"] and ores["results"][0]["response"]["body"]["choices"][0]["message"]["content"] == "Batch reply from gpt-4o-mini", (s, b[:300]))
        s, _, b = call("GET", "/v1/batches/" + gbid + "/results", headers=gem)
        gres = json.loads(b) if s == 200 else {}
        check("gemini batch results as Bifrost's results body", s == 200 and gres.get("batch_id") == gbid and gres.get("results", [{}])[0].get("custom_id") == "g1", (s, b[:300]))
        s, _, b = call("GET", "/v1/batches/" + abid + "/results", headers={"x-bf-provider": "anthropic"})
        ares = json.loads(b) if s == 200 else {}
        check("anthropic batch results as Bifrost's results body", s == 200 and ares.get("batch_id") == abid and [x["custom_id"] for x in ares.get("results", [])] == ["c1"] and ares["results"][0]["response"]["status_code"] == 200 and ares["results"][0]["response"]["body"]["choices"][0]["message"]["content"] == "Batch reply from claude-sonnet-4", (s, b[:300]))

        # Vertex files on Cloud Storage, and a Batch Prediction job that reads and writes the bucket
        vg = {"x-bf-provider": "vertex"}
        vin = bline("v1", "gemini-2.5-flash") + "\n" + bline("v2", "gemini-2.5-flash") + "\n"
        s, b = multipart("/v1/files", "vertex.jsonl", vin.encode(), {"purpose": "batch", "gcs_bucket": "e2e-gcs", "gcs_prefix": "in"}, vg)
        vf = jget(b) if s == 200 else {}
        vfid = vf.get("id", "")
        check("vertex file upload goes to Cloud Storage as a gs:// file", s == 200 and vfid.startswith("gs://e2e-gcs/in/vertex-files/") and vf.get("bytes") == len(vin.encode()) and vf.get("object") == "file", (s, b))
        check("vertex files are uploaded as media with the service account's token", seen()[-1]["path"].startswith("/upload/storage/v1/b/e2e-gcs/o?uploadType=media&name=in%2Fvertex-files%2F") and seen()[-1]["auth"] == "Bearer ya29.test-token", seen()[-1])
        vfq = urllib.parse.quote(vfid, safe="")
        s, _, b = call("GET", "/v1/files/" + vfq, headers=vg)
        check("vertex file retrieve reads the object's metadata", s == 200 and jget(b).get("id") == vfid and jget(b).get("filename") == "vertex.jsonl", (s, b))
        s, _, b = call("GET", "/v1/files/" + vfq + "/content", headers=vg)
        check("vertex file content is the uploaded bytes", s == 200 and b == vin, (s, b[:200]))
        s, _, b = call("GET", "/v1/files?gcs_bucket=e2e-gcs&gcs_prefix=in", headers=vg)
        check("vertex files list the bucket and prefix", s == 200 and any(x.get("id") == vfid for x in jget(b).get("data", [])), (s, b[:300]))
        s, _, b = call("POST", "/v1/batches", {"input_file_id": vfid, "endpoint": "/v1/chat/completions", "completion_window": "24h", "output_folder": {"url": "gs://e2e-gcs-out/d"}, "display_name": "nightly"}, vg)
        vb = jget(b) if s == 200 else {}
        vbid = vb.get("id", "")
        check("vertex batch creates a job on the uploaded file", s == 200 and vbid != "" and vb.get("status") == "validating" and vb.get("output_file_id") == "raiju-batch-output-" + vbid, (s, b))
        ups = [x for x in seen() if x["path"].startswith("/upload/storage/v1/b/e2e-gcs/o?uploadType=media&name=vertex-batch-input%2F")]
        check("vertex batch input is written to the bucket in Vertex's instance shape", ups and '"labels":{"bifrost_custom_id":"v1"}' in ups[-1]["body"] and '"bifrost_custom_id":"v2"' in ups[-1]["body"], ups[-1:])
        jobs = [x for x in seen() if x["path"] == "/v1/projects/proj/locations/us-central1/batchPredictionJobs" and x["body"].startswith('{"displayName":"nightly"')]
        check("vertex job reads the converted input and writes to output_folder", jobs and '"uris":["gs://e2e-gcs/vertex-batch-input/' in jobs[-1]["body"] and '"outputUriPrefix":"gs://e2e-gcs-out/d"' in jobs[-1]["body"] and '"model":"publishers/google/models/gemini-2.5-flash"' in jobs[-1]["body"], jobs[-1:])
        s, _, b = call("GET", "/v1/batches/" + vbid, headers=vg)
        check("vertex batch retrieve is completed with its counts", s == 200 and jget(b).get("status") == "completed" and jget(b).get("request_counts", {}).get("completed") == 2, (s, b))
        s, _, b = call("GET", "/v1/files/raiju-batch-output-" + vbid + "/content", headers=vg)
        vout = [json.loads(x) for x in b.split("\n") if x.strip()]
        check("vertex batch output is OpenAI's batch output", s == 200 and [x["custom_id"] for x in vout] == ["v1", "v2"] and vout[0]["response"]["body"]["choices"][0]["message"]["content"] == "Batch reply from gemini", (s, b[:400]))
        s, _, b = call("GET", "/v1/batches/" + vbid + "/results", headers=vg)
        check("vertex batch results as Bifrost's results body", s == 200 and jget(b).get("batch_id") == vbid and len(jget(b).get("results", [])) == 2, (s, b[:300]))
        s, _, b = call("GET", "/v1/batches?limit=5", headers=vg)
        check("vertex batches list", s == 200 and any(x.get("id") == vbid for x in jget(b).get("data", [])), (s, b[:300]))
        s, _, b = call("POST", "/v1/batches/" + vbid + "/cancel", headers=vg)
        check("vertex batch cancel answers the job's new state", s == 200 and jget(b).get("status") == "cancelled", (s, b))
        # Bedrock files on S3 under the key's default batch bucket, and a model invocation job
        bg = {"x-bf-provider": "bedrock_batch"}
        bin_ = bline("b1", "anthropic.claude-3-haiku-20240307-v1:0") + "\n"
        s, b = multipart("/v1/files", "bedrock.jsonl", bin_.encode(), {"purpose": "batch"}, bg)
        bf = jget(b) if s == 200 else {}
        bfid = bf.get("id", "")
        check("bedrock file upload goes to S3 under the batch bucket's prefix", s == 200 and bfid.startswith("s3://e2e-files/jobs/") and bf.get("bytes") == len(bin_.encode()), (s, b))
        check("bedrock file upload is signed for S3", seen()[-1]["path"].startswith("/e2e-files/jobs/") and seen()[-1]["auth"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/") and "/us-east-1/s3/aws4_request" in seen()[-1]["auth"], seen()[-1])
        bfq = urllib.parse.quote(bfid, safe="")
        s, _, b = call("GET", "/v1/files/" + bfq, headers=bg)
        check("bedrock file retrieve is the S3 object's metadata", s == 200 and jget(b).get("id") == bfid and jget(b).get("bytes") == len(bin_.encode()), (s, b))
        s, _, b = call("GET", "/v1/files/" + bfq + "/content", headers=bg)
        check("bedrock file content is the S3 object", s == 200 and b == bin_, (s, b[:200]))
        s, _, b = call("GET", "/v1/files?s3_bucket=e2e-files&s3_prefix=jobs/", headers=bg)
        check("bedrock files list the bucket's prefix", s == 200 and any(x.get("id") == bfid for x in jget(b).get("data", [])), (s, b[:300]))
        s, _, b = call("POST", "/v1/batches", {"input_file_id": bfid, "endpoint": "/v1/chat/completions", "completion_window": "24h", "metadata": {"job_name": "e2e-job"}}, bg)
        bb = jget(b) if s == 200 else {}
        bbid = bb.get("id", "")
        check("bedrock batch writes records to S3 and creates the job", s == 200 and bbid != "" and bb.get("status") == "completed" and bb.get("output_file_id") == "raiju-batch-output-" + bbid, (s, b))
        jobs = [x for x in seen() if x["path"] == "/model-invocation-job" and '"jobName":"e2e-job"' in x["body"]]
        check("bedrock job runs as the batch role, reads the records and writes under the default batch prefix", jobs and '"roleArn":"arn:aws:iam::123456789012:role/batch"' in jobs[-1]["body"] and '"s3Uri":"s3://e2e-files/jobs/"' in jobs[-1]["body"] and '"s3InputFormat":"JSONL"' in jobs[-1]["body"] and '"modelId":"anthropic.claude-3-haiku-20240307-v1:0"' in jobs[-1]["body"], jobs[-1:])
        recs = [x for x in seen() if x["path"].startswith("/e2e-files/bedrock-batch-input/")]
        check("bedrock records are Bedrock's shape with Claude's version, and no model", recs and '"recordId":"b1"' in recs[-1]["body"] and '"anthropic_version":"bedrock-2023-05-31"' in recs[-1]["body"] and '"model":' not in recs[-1]["body"], recs[-1:])
        s, _, b = call("GET", "/v1/files/raiju-batch-output-" + bbid + "/content", headers=bg)
        bout = [json.loads(x) for x in b.split("\n") if x.strip()]
        check("bedrock batch output is OpenAI's batch output", s == 200 and [x["custom_id"] for x in bout] == ["b1"] and bout[0]["response"]["body"]["choices"][0]["message"]["content"] == "Batch reply from anthropic.claude-3-haiku-20240307-v1:0", (s, b[:400]))
        s, _, b = call("GET", "/v1/batches/" + bbid, headers=bg)
        check("bedrock batch retrieve", s == 200 and jget(b).get("id") == bbid and jget(b).get("status") == "completed", (s, b))
        s, _, b = call("GET", "/v1/batches/" + bbid + "/results", headers=bg)
        check("bedrock batch results as Bifrost's results body", s == 200 and jget(b).get("results", [{}])[0].get("custom_id") == "b1", (s, b[:300]))
        s, _, b = call("GET", "/v1/batches", headers=bg)
        check("bedrock batches list", s == 200 and any(x.get("id") == bbid for x in jget(b).get("data", [])), (s, b[:300]))
        s, _, b = call("POST", "/v1/batches/" + bbid + "/cancel", headers=bg)
        check("bedrock batch cancel stops the job", s == 200 and jget(b).get("status") == "cancelled", (s, b))
        s, _, b = call("DELETE", "/v1/files/" + bfq, headers=bg)
        check("bedrock file delete answers OpenAI's delete object", s == 200 and jget(b) == {"id": bfid, "object": "file", "deleted": True}, (s, b))

        # Management API: admin auth, CRUD, hot reload, secrets kept out of the file
        s, _, _ = call("GET", "/api/config", auth=False)
        check("management API requires admin credentials", s == 401, s)
        s, _, b = call("GET", "/api/config")
        check("config is redacted", s == 200 and "sk-spare" not in b and "bad-key" not in b and "env.E2E_OPENAI_KEY" in b, b[:300])
        s, _, b = call("POST", "/api/governance/virtual-keys", {"name": "ci", "provider_configs": [{"provider": "openai", "allowed_models": ["gpt-4o-mini"]}]})
        vk = json.loads(b)
        value = vk.get("value", "")
        check("virtual key created with a generated secret", s == 201 and value.startswith("sk-bf-") and len(value) == 38, b)
        s, _, b = chat("openai/gpt-4o-mini", headers={"x-bf-vk": value}, seed=600)
        check("new virtual key works without a restart", s == 200, b)
        s, _, b = chat("anthropic/claude-sonnet-4", headers={"x-bf-vk": value}, seed=601)
        check("new virtual key's allowlist is enforced", s == 403, b)
        s, _, b = call("GET", "/api/governance/virtual-keys")
        check("virtual key values are masked on read", value not in b and '"ci"' in b, b[:300])
        s, _, b = call("PUT", "/api/providers/extra", {"keys": [{"name": "x", "value": "sk-extra-secret", "models": [], "weight": 1}], "custom_provider_config": {"base_provider_type": "openai"}, "network_config": {"base_url": MOCK}})
        check("provider added", s in (200, 201), b)
        s, _, b = chat("extra/some-model", seed=602)
        check("traffic routes to the new provider", s == 200 and seen()[-1]["auth"] == "Bearer sk-extra-secret", (s, b))
        # provider refresh-models: the mock's /v1/models answers for the provider's key
        s, _, b = call("POST", "/api/providers/extra/refresh-models")
        check("refresh-models lists the provider's models live", s == 200 and "m-a" in b and "m-b" in b, (s, b[:300]))
        kid = json.loads(call("GET", "/api/providers/extra")[2])["keys"][0]["id"]
        s, _, b = call("POST", f"/api/providers/extra/keys/{kid}/refresh-models")
        check("refresh-models for one key", s == 200 and "m-a" in b, (s, b[:300]))
        s, _, b = call("POST", "/api/providers/nope/refresh-models")
        check("refresh-models refuses an unknown provider", s == 404, (s, b[:200]))
        s, _, b = call("GET", "/api/models/base?limit=5")
        bj = json.loads(b) if s == 200 else {"models": [], "total": 0}
        check("models/base lists distinct base models, paged", s == 200 and 0 < len(bj["models"]) <= 5 and bj["total"] >= len(bj["models"]), (s, b[:200]))
        s, _, b = call("GET", "/api/models/details?provider=openai&limit=3")
        dj = json.loads(b) if s == 200 else {"models": []}
        check("models/details lists priced rows of one provider", s == 200 and 0 < len(dj["models"]) <= 3 and all(m["provider"] == "openai" for m in dj["models"]), (s, b[:200]))
        s, _, b = call("GET", "/api/circuit-breaker/state")
        check("circuit-breaker state is Bifrost's circuits map", s == 200 and b.startswith('{"circuits":{'), (s, b[:200]))
        s, _, b = call("GET", "/api/logs/histogram")
        hj = json.loads(b) if s == 200 else {"buckets": [], "bucket_size_seconds": 0}
        check("log histogram counts the requests just made", s == 200 and sum(x["count"] for x in hj["buckets"]) > 0 and hj["bucket_size_seconds"] == 3600, (s, b[:200]))
        saved = open(config).read()
        check("saved config keeps env references and new keys", "env.E2E_OPENAI_KEY" in saved and "sk-from-env" not in saved and "sk-extra-secret" in saved, saved[:200])
        s, _, b = call("POST", "/api/governance/budgets", {"id": "b-bad", "max_limit": -1, "reset_duration": "1d"})
        check("invalid budget rejected", s == 400, b)

        # TLS options per provider
        res = [chat(p + "/m", seed=1900 + i) for i, p in enumerate(["tls-ca", "tls-skip", "tls-none"])]
        check("ca_cert_pem trusts a private CA, insecure_skip_verify skips checks, and neither refuses", res[0][0] == 200 and "over tls" in res[0][2] and res[1][0] == 200 and res[2][0] >= 500, [(r[0], r[2][:120]) for r in res])

        # the Responses lifecycle and realtime REST pass through to OpenAI (Bifrost's default provider)
        got = []
        for m, path in [("GET", "/v1/responses/resp_1"), ("DELETE", "/v1/responses/resp_1"), ("POST", "/v1/responses/resp_1/cancel"), ("GET", "/v1/responses/resp_1/input_items"), ("GET", "/openai/v1/responses/resp_2?provider=openai")]:
            s, _, b = call(m, path)
            got.append((s, json.loads(b).get("path") if s == 200 else b))
        check("responses retrieve, delete, cancel and input_items pass through", got == [(200, "/v1/responses/resp_1"), (200, "/v1/responses/resp_1"), (200, "/v1/responses/resp_1/cancel"), (200, "/v1/responses/resp_1/input_items"), (200, "/v1/responses/resp_2")], got)
        s, _, b = call("POST", "/v1/responses/input_tokens", {"model": "openai/gpt-4o", "input": "hi"})
        up = seen()[-1]
        check("responses input_tokens goes to the model's provider with a bare model", s == 200 and up["path"] == "/v1/responses/input_tokens" and '"model":"gpt-4o"' in up["body"].replace(" ", ""), (s, b, up))
        s, _, b = call("POST", "/v1/realtime/client_secrets", {"session": {"type": "realtime", "model": "gpt-realtime"}})
        s2, _, b2 = call("POST", "/v1/realtime/sessions", {"model": "openai/gpt-realtime"})
        check("realtime client_secrets and sessions pass through", s == 200 and s2 == 200 and seen()[-1]["path"] == "/v1/realtime/sessions", (s, b, s2, b2))

        # Rerank: a provider without a rerank API is an error, as in Bifrost
        s, _, b = call("POST", "/v1/rerank", {"model": "openai/any", "query": "q", "documents": ["a"]})
        check("rerank on a provider without a rerank API is an error", s == 400 and "not supported" in b, (s, b))
        # ... and raiju/lexical asks for the local lexical ranking
        s, _, b = call("POST", "/v1/rerank", {"model": "raiju/lexical", "query": "solar panels on roofs", "documents": ["a recipe for soup", "installing solar panels on your roof", "train timetables"], "top_n": 2})
        r = json.loads(b)
        check("rerank ranks the relevant document first", s == 200 and r["results"][0]["index"] == 1 and len(r["results"]) == 2, b)

        # Token counting: exact from Anthropic, estimated elsewhere
        s, _, b = call("POST", "/anthropic/v1/messages/count_tokens", {"model": "claude-sonnet-4", "messages": [{"role": "user", "content": "hello"}]})
        check("anthropic count_tokens is exact", s == 200 and json.loads(b)["input_tokens"] == 42 and seen()[-1]["path"] == "/v1/messages/count_tokens", b)
        s, _, b = call("POST", "/v1/count_tokens", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hello there, how are you today?"}]})
        r = json.loads(b)
        check("count_tokens estimates for other providers", s == 200 and r["exact"] is False and 5 < r["input_tokens"] < 40, b)

        # Async jobs, polled at Bifrost's /v1/async/<op>/{id} with Bifrost's status names
        s, _, b = call("POST", "/v1/async/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "later"}]})
        job = json.loads(b)
        check("async job accepted", s == 202 and job["status"] in ("pending", "processing") and job["id"].startswith("job_") and job["created_at"].endswith("Z"), b)
        for _ in range(50):
            s, _, b = call("GET", f"/v1/async/chat/completions/{job['id']}")
            if json.loads(b)["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)
        done = json.loads(b)
        check("async job completes with the result", done["status"] == "completed" and done["status_code"] == 200 and done["result"]["choices"][0]["message"]["content"] == "Hello from gpt-4o-mini" and "expires_at" in done, b)
        s, _, _ = call("GET", f"/v1/async/jobs/{job['id']}")
        check("the generic job path still works", s == 200, s)
        s, _, _ = call("GET", f"/v1/async/embeddings/{job['id']}")
        check("polling under another op is 404", s == 404, s)
        s, _, b = call("POST", "/v1/async/rerank", {"model": "openai/rr", "query": "q", "documents": ["a", "b"]})
        check("async rerank is accepted", s == 202, (s, b))
        s, _, _ = call("GET", "/v1/async/jobs/job_nope")
        check("unknown job is 404", s == 404)

        # Plugins
        before = len(seen())
        s, h, b = chat("openai/mock-me")
        check("mocker plugin short-circuits", s == 200 and json.loads(b)["choices"][0]["message"]["content"] == "mocked!" and len(seen()) == before, b)
        chat("openai/gpt-4o-mini", seed=700)
        last = seen()[-1]
        check("header plugin tags upstream requests", last["team"] == "e2e", last)
        check("maxtokens plugin sets a default", json.loads(last["body"]).get("max_tokens") == 777, last["body"][:200])

        # Semantic cache: a near-duplicate prompt with the same cache key is served from cache
        key = {"x-bf-cache-key": "faq", "x-bf-mcp-include-clients": "none"}  # requests with tools are never cached
        def ask(q, extra=None):
            return call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": q}]}, {**key, **(extra or {})})
        s, h, _ = ask("What is the capital city of France?")
        n = len(seen())
        s, h, b = ask("what is the capital city of france ?")
        hl = {k.lower(): v for k, v in h.items()}
        check("semantic cache serves a near-duplicate prompt", s == 200 and hl.get("x-bf-cache") == "semantic-hit" and float(hl.get("x-bf-cache-similarity", 0)) >= 0.95 and len([x for x in seen()[n:] if x["path"] == "/v1/chat/completions"]) == 0, (h, b))
        s, h, _ = ask("Write a haiku about penguins sliding on ice")
        hl = {k.lower(): v for k, v in h.items()}
        check("semantic cache misses an unrelated prompt", hl.get("x-bf-cache") != "semantic-hit", h)
        n = len(seen())
        call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "what is the capital city of france ??"}]})
        check("no semantic lookup without a cache key", not any(x["path"] == "/v1/embeddings" for x in seen()[n:]))

        # Streaming: chunks reach the client as the upstream produces them (both servers)
        if True:
            import socket as _s
            body = json.dumps({"model": "slowai/slow", "stream": True, "messages": [{"role": "user", "content": "count"}]}).encode()
            sock = _s.create_connection(("127.0.0.1", 18098), timeout=10)
            sock.sendall(b"POST /v1/chat/completions HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nx-bf-mcp-include-clients: none\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            t0 = time.time(); arrivals = []; data = b""
            while b"[DONE]" not in data:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
                for w in [b"one", b"two", b"three", b"four"]:
                    if w in chunk:
                        arrivals.append(round(time.time() - t0, 2))
            sock.close()
            spread = arrivals[-1] - arrivals[0] if len(arrivals) == 4 else 0
            check("stream chunks arrive incrementally", len(arrivals) == 4 and spread > 0.3, arrivals)
            check("streamed model renamed for the caller", b'"model":"slowai/slow"' in data and b"[DONE]" in data, data[:300])
            check("usage chunk dropped when not requested", b'"usage"' not in data, data[-300:])

            # the Anthropic route streams incrementally from an OpenAI-format provider too
            body = json.dumps({"model": "slowai/slow", "max_tokens": 50, "stream": True, "messages": [{"role": "user", "content": "count"}]}).encode()
            sock = _s.create_connection(("127.0.0.1", 18098), timeout=10)
            sock.sendall(b"POST /anthropic/v1/messages HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nx-bf-mcp-include-clients: none\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            t0 = time.time(); arrivals = []; data = b""
            while b"message_stop" not in data:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
                for w in [b"one", b"two", b"three", b"four"]:
                    if w in chunk:
                        arrivals.append(round(time.time() - t0, 2))
            sock.close()
            spread = arrivals[-1] - arrivals[0] if len(arrivals) == 4 else 0
            check("anthropic route streams events as they arrive", len(arrivals) == 4 and spread > 0.3 and b"content_block_delta" in data and b'"output_tokens":4' in data, (arrivals, data[-400:]))

        # --- wave 5 ---
        hl = lambda h: {k.lower(): v for k, v in h.items()}
        s, _, b = chat("vaulted/gpt-4o-mini", seed=901)
        vault_reads = [x for x in seen() if x["path"] == "/v1/secret/data/raiju"]
        check("vault secret resolved into a provider key", s == 200 and seen()[-1]["auth"] == "Bearer sk-from-vault" and vault_reads and vault_reads[0]["body"] == "root-token", (s, b, seen()[-1]))

        s, h, b = chat("auto", seed=902)
        check("complexity router sends a simple prompt to the simple tier", s == 200 and json.loads(b)["choices"][0]["message"]["content"] == "Hello from gpt-4o-mini" and hl(h).get("x-bf-complexity-tier") == "SIMPLE", (h, b))
        s, h, b = chat("auto", headers={"x-bf-complexity-tier": "complex"}, seed=903)
        check("complexity tier override picks the complex tier", s == 200 and json.loads(b)["choices"][0]["message"]["content"] == "Hi from claude", b)

        attempts = []
        for i in range(6):
            s, h, _ = chat("openai/rotate-me", headers={"x-bf-session-id": "sess-42", "x-bf-mcp-include-clients": "none"}, seed=910 + i)
            attempts.append((s, hl(h).get("x-bf-attempts")))
        check("session affinity keeps a session on the key that worked", all(a == (200, "1") for a in attempts[1:]), attempts)

        s, h, b = call("POST", "/v1/chat/completions", {"model": "openai/agent-x", "messages": [{"role": "user", "content": "weather in Oslo?"}]})
        r = json.loads(b)
        check("MCP agent mode runs the tool and answers", s == 200 and r["choices"][0]["message"]["content"] == "It is sunny in Oslo" and hl(h).get("x-bf-agent-tool-calls") == "1", (h, b))

        # the gateway as an MCP server
        s, h, b = call("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1"}}})
        sid = hl(h).get("mcp-session-id", "")
        check("MCP server initialize gives a session", s == 200 and sid != "" and "protocolVersion" in b, (s, h, b))
        s, _, b = call("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"mcp-session-id": sid})
        check("MCP server lists the connected tools", s == 200 and "weather-get_weather" in b, b)
        s, _, b = call("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "weather-get_weather", "arguments": {"city": "Oslo"}}}, {"mcp-session-id": sid})
        check("MCP server runs a tool", s == 200 and "Sunny in Oslo" in b, b)
        s, _, _ = call("POST", "/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        check("MCP server refuses requests without a session", s == 400)

        # external guardrails (a webhook provider)
        s, _, b = call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "tell me something forbidden"}]})
        check("an external guardrail blocks a prompt", s == 400 and "forbidden topic" in b and "policy-hook" in b, (s, b))
        s, _, b = call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "my secret-word"}]})
        check("an external guardrail redacts a prompt", s == 200 and json.loads(seen()[-1]["body"])["messages"][0]["content"] == "my [REDACTED]", seen()[-1]["body"][:200])
        s, _, b = chat("openai/forbidden-model", seed=1200)
        check("an external guardrail blocks an answer", s == 400 and "response blocked" in b, (s, b))

        # access profiles: one policy shared by keys
        PK = {"x-bf-vk": "sk-bf-profiled"}
        s, _, b = chat("openai/gpt-4o-mini", headers=PK, seed=1100)
        check("an access profile's required header is enforced", s == 400 and "x-project" in b, (s, b))
        s, _, b = chat("anthropic/claude-sonnet-4", headers={**PK, "x-project": "p1"}, seed=1101)
        check("an access profile limits models", s == 403, (s, b))
        s, _, b = chat("openai/gpt-4o-mini", headers={**PK, "x-project": "p1"}, seed=1102, max_tokens=500)
        up = json.loads(seen()[-1]["body"])
        names = [t["function"]["name"] for t in up.get("tools", [])]
        check("an access profile caps max_tokens and narrows MCP tools", s == 200 and up.get("max_tokens") == 64 and names == ["weather-get_weather"], (s, up.get("max_tokens"), names))
        s, _, b = call("POST", "/api/governance/access-profiles", {"id": "readers", "allowed_models": ["openai/*"]})
        s2, _, b2 = call("GET", "/api/governance/access-profiles")
        check("access profiles are managed through the API", s == 201 and s2 == 200 and "readers" in b2 and "restricted" in b2, (s, b, b2))
        s, _, b = call("DELETE", "/api/governance/access-profiles/restricted")
        check("a profile in use can't be deleted", s == 409 and "vk-profiled" in b, (s, b))
        s, _, _ = call("DELETE", "/api/governance/access-profiles/readers")
        check("an unused profile is deleted", s == 200, s)

        # virtual MCP: a renamed tool with argument defaults
        s, h, b = call("POST", "/mcp/weather-desk", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1"}}})
        vsid = hl(h).get("mcp-session-id", "")
        s, _, b = call("POST", "/mcp/weather-desk", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"mcp-session-id": vsid})
        names = [t["name"] for t in json.loads(b)["result"]["tools"]] if s == 200 else []
        check("a virtual MCP lists only its renamed tools", names == ["forecast"] and "Forecast for a city" in b, b[:300])
        s, _, b = call("POST", "/mcp/weather-desk", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "forecast", "arguments": {"city": "Oslo"}}}, {"mcp-session-id": vsid})
        up = [x for x in seen() if x["path"] == "/mcp" and "tools/call" in x["body"]][-1]["body"]
        check("a virtual MCP tool call reaches the source tool with defaults", s == 200 and "Sunny in Oslo" in b and '"name":"get_weather"' in up and '"units":"metric"' in up and '"city":"Oslo"' in up, (b, up))
        s, _, _ = call("POST", "/mcp/nope", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        check("unknown virtual MCP is 404", s == 404, s)
        s, _, b = call("GET", "/api/mcp/virtual")
        check("virtual MCPs are listed", s == 200 and '"forecast"' in b, b)
        s, _, b = call("GET", "/api/mcp/clients")
        check("Bifrost's MCP clients list", s == 200 and '"client_id":"local"' in b.replace(" ", ""), b[:400])
        s, _, b = call("POST", "/api/mcp/client/local/refresh-tools")
        check("an MCP client's tools refresh on the live manager", s == 200 and '"tool_count"' in b, (s, b))
        s, _, b = call("POST", "/api/mcp/client/nope/reconnect")
        check("reconnecting an unknown MCP client is 404", s == 404, (s, b))
        s, _, b = call("GET", "/api/mcp/client/local/openapi-spec")
        check("openapi-spec: no client here is OpenAPI, so 404", s == 404 and "OpenAPI MCP client not found" in b, (s, b))
        s, _, b = call("POST", "/api/mcp/client/local/complete-oauth")
        check("complete-oauth: no OAuth config to finish, so 404", s == 404 and "OAuth config not found" in b, (s, b))
        s, _, b = call("POST", "/api/mcp/client/local/initiate-verification")
        check("initiate-verification refuses a client that is not OAuth", s == 400 and "OAuth-based clients" in b, (s, b))
        s, _, b = call("POST", "/api/mcp/client/local/verify-headers")
        check("verify-headers refuses a client without per-user headers", s == 400 and "per_user_headers" in b, (s, b))
        s, _, b = call("POST", "/api/mcp/client/nope/verify-exchange")
        check("verify-exchange on an unknown client is 404", s == 404, (s, b))
        s, _, b = call("GET", "/api/config")
        check("the config view masks MCP env secrets", s == 200 and '"MCP_GREETING":"hello"' not in b.replace(" ", ""), b[:300])

        # RBAC: a viewer reads but can't change anything
        s, _, b = call("POST", "/api/users", {"name": "viewer1", "role": "viewer"})
        token = json.loads(b).get("token", "") if s == 201 else ""
        check("admin creates a user and gets its token once", s == 201 and token.startswith("sk-admin-"), (s, b))
        time.sleep(0.2)
        V = {"authorization": "Bearer " + token}
        s, _, _ = call("GET", "/api/config", headers=V)
        check("a viewer can read the config", s == 200, s)
        s, _, _ = call("PUT", "/api/providers/nope", {"keys": []}, headers=V)
        check("a viewer can't change providers", s == 403, s)
        s, _, b = call("GET", "/api/users")
        check("users are listed without credential hashes", s == 200 and "viewer1" in b and "sha256" not in b, b)
        saved = json.load(open(config))
        check("users are saved hashed", any(u["name"] == "viewer1" and len(u.get("token_sha256", "")) == 64 for u in saved["governance"]["users"]), saved["governance"].get("users"))

        # audit log
        s, _, b = call("GET", "/api/audit-logs")
        ev = json.loads(b).get("events", []) if s == 200 else []
        check("audit log records changes with the actor", any(e["actor"] == "legacy-token" and e["path"] == "/api/users" and e["status"] == 201 for e in ev), b[:500])
        check("audit log records denied changes", any(e["status"] == 403 and e["actor"] == "unauthenticated" for e in ev), b[:800])
        s, _, b = call("GET", "/api/audit-logs/verify")
        check("audit chain verifies", s == 200 and json.loads(b)["ok"] is True and json.loads(b)["checked"] >= 2, b)
        s, h, b = call("GET", "/api/audit-logs/export")
        check("audit export is JSONL", s == 200 and all(json.loads(l)["sig"] for l in b.strip().split("\n")), b[:300])
        s, _, _ = call("GET", "/api/audit-logs", headers=V)
        check("a viewer can't read the audit log", s == 403, s)

        # alerting: "any traffic" fires to the webhook within one interval
        time.sleep(1.5)
        hooks = [json.loads(x["body"]) for x in seen() if x["path"] == "/alert-hook"]
        check("an alert fires to the webhook", any(x.get("kind") == "firing" and x.get("rule") == "any-traffic" for x in hooks), hooks)
        s, _, b = call("GET", "/api/alerts")
        check("alert state is visible", s == 200 and '"firing"' in b, b[:300])
        # Bifrost's alert rules: CEL over a virtual key's budget usage, managed through /api/alerting
        s, _, b = call("POST", "/api/alerting/rules", {"name": "vk budget", "enabled": True, "scope_type": "virtual_key", "scope_id": "vk-budget", "cel_expression": "budget_usage_percent >= 0.0 && budget_limit > 0.0", "channel_ids": ["hook"], "cooldown_milliseconds": 0})
        rid = json.loads(b).get("id", "") if s in (200, 201) else ""
        s2, _, _ = call("POST", "/api/alerting/rules", {"name": "bad", "enabled": True, "scope_type": "virtual_key", "scope_id": "vk-budget", "cel_expression": "budget_usage_percent >", "channel_ids": ["hook"]})
        time.sleep(2.5)
        hooks = [x["body"] for x in seen() if x["path"] == "/alert-hook"]
        _, _, hb = call("GET", "/api/alerting/history")
        check("a Bifrost alert rule is created over the API and fires", s in (200, 201) and rid != "" and s2 == 400 and any(rid in h or "vk budget" in h for h in hooks) and rid in hb, (s, b, s2, hooks[-2:], hb[:300]))
        s, _, _ = call("DELETE", "/api/alerting/rules/" + rid)
        check("alert rules delete", s == 200, s)

        # --- wave 7: providers and embeddings ---
        s, _, b = chat("watsonx/ibm/granite-3-8b-instruct", seed=1001, headers={"x-bf-mcp-include-clients": "none"})
        wx = [x for x in seen() if x["path"] == "/ml/v1/text/chat"]
        iam = [x for x in seen() if x["path"] == "/identity/token"]
        check("watsonx chat with an IAM token", s == 200 and "Hi from watsonx" in b and wx and wx[-1]["auth"] == "Bearer iam-token" and json.loads(wx[-1]["body"])["project_id"] == "proj-1" and iam and "apikey=ibm-key" in iam[0]["body"], (s, b, wx[-1:] if wx else None))
        s, _, b = chat("nvidia/meta/llama-3.1-8b-instruct", seed=1002, headers={"x-bf-mcp-include-clients": "none"})
        check("a long-tail OpenAI-compatible provider", s == 200 and "Hello from meta/llama-3.1-8b-instruct" in b and seen()[-1]["auth"] == "Bearer nv-key", b)
        s, _, b = call("POST", "/v1/embeddings", {"model": "gemini/text-embedding-004", "input": ["alpha", "beta"]})
        r = json.loads(b) if s == 200 else {}
        check("gemini embeddings", s == 200 and len(r["data"]) == 2 and r["data"][1]["embedding"] == [1.5, 1] and seen()[-1]["path"].endswith(":batchEmbedContents"), b[:300])
        n = len(seen())
        s, _, b = call("POST", "/v1/embeddings", {"model": "bedrock/amazon.titan-embed-text-v2:0", "input": ["one", "two", "three"]})
        r = json.loads(b) if s == 200 else {}
        calls = [x for x in seen()[n:] if x["path"].endswith("/invoke")]
        check("bedrock titan embeddings, one call per input", s == 200 and len(r["data"]) == 3 and r["usage"]["prompt_tokens"] == 9 and len(calls) == 3, (b[:300], len(calls)))

        # --- wave 8: a config in Bifrost's dialect ---
        wait("http://127.0.0.1:18093/health")
        BGW = "http://127.0.0.1:18093"
        def bchat(model, headers=None, content="hello"):
            return call("POST", "/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": content}]}, headers, base=BGW)
        s, _, _ = bchat("openai/gpt-4o-mini")
        check("inference auth is on by default when the config has keys", s == 401, s)
        BK = {"x-bf-vk": "sk-bf-dialect"}
        s, _, _ = bchat("openai/gpt-4o-mini", BK)
        check("a virtual key passes inference auth", s == 200, s)
        s, _, _ = bchat("openai/gpt-4o-mini", {"authorization": "Basic YWRtaW46cHc="})
        check("Bifrost's auth_config admin credentials pass inference auth", s == 200, s)
        s, _, _ = call("GET", "/api/config", base=BGW, auth=False, headers={"authorization": "Basic YWRtaW46cHc="})
        check("Bifrost's auth_config guards the management API", s == 200 and call("GET", "/api/config", base=BGW, auth=False)[0] == 401, s)
        # /api/session/*: login issues a UI session token, the token opens the API, logout drops it
        s, _, b = call("POST", "/api/session/login", {"username": "admin", "password": "pw"}, base=BGW, auth=False)
        stok = json.loads(b).get("token", "") if s == 200 else ""
        check("session login issues a session token", s == 200 and stok.startswith("sk-sess-"), (s, b[:200]))
        s2, _, b2 = call("POST", "/api/session/login", {"username": "admin", "password": "wrong"}, base=BGW, auth=False)
        check("session login refuses a wrong password", s2 == 401, (s2, b2[:200]))
        SH = {"authorization": "Bearer " + stok}
        s3, _, b3 = call("GET", "/api/session/is-auth-enabled", base=BGW, auth=False, headers=SH)
        check("is-auth-enabled reports the session token as valid", s3 == 200 and '"has_valid_token":true' in b3 and '"is_auth_enabled":true' in b3, (s3, b3[:300]))
        s4, _, _ = call("GET", "/api/config", base=BGW, auth=False, headers=SH)
        check("the session token opens the management API", s4 == 200, s4)
        s5, _, _ = call("POST", "/api/session/logout", base=BGW, auth=False, headers=SH)
        s6, _, _ = call("GET", "/api/config", base=BGW, auth=False, headers=SH)
        check("logout drops the session token", s5 == 200 and s6 == 401, (s5, s6))
        s, _, b = bchat("openai/gpt-4o-mini", BK, "something forbidden")
        check("Bifrost's guardrails_config is enforced", s == 400 and "forbidden topic" in b, (s, b))
        SK = {**BK, "x-bf-cache-key": "e2e"}
        q1, h1, qb = bchat("openai/gpt-4o-mini", SK, "what is the capital of france")
        _, h2, _ = bchat("openai/gpt-4o-mini", SK, "what is the capital of france?")
        qc = json.loads(call("GET", "/_calls", base="http://127.0.0.1:18089")[2])
        check("the semantic cache plugin uses Bifrost's vector_store (Qdrant)", q1 == 200 and hl(h1).get("x-bf-cache") != "semantic-hit" and hl(h2).get("x-bf-cache") == "semantic-hit"
              and {"method": "PUT", "path": "/collections/e2e-ns/points"} in qc and {"method": "POST", "path": "/collections/e2e-ns/points/query"} in qc, (q1, qb, h1, h2, qc))
        # the semantic cache on Weaviate, Pinecone and chromem: a near-duplicate is served from the store,
        # entries stay with the virtual key that wrote them unless disable_identity_scoping, responses with
        # tool calls are not kept, and chromem's entries survive a restart
        for port in (18110, 18111, 18112):
            wait(f"http://127.0.0.1:{port}/health")
        def vs_chat(port, model, vk, content):
            return call("POST", "/v1/chat/completions", {"model": model, "messages": [{"role": "user", "content": content}]}, {"x-bf-vk": vk, "x-bf-cache-key": "vs-e2e"}, base=f"http://127.0.0.1:{port}")
        _, vw1, _ = vs_chat(18110, "openai/gpt-4o-mini", "sk-bf-a", "what is the capital of france")
        _, vw2, _ = vs_chat(18110, "openai/gpt-4o-mini", "sk-bf-a", "what is the capital of france?")
        _, vw3, _ = vs_chat(18110, "openai/gpt-4o-mini", "sk-bf-b", "what is the capital of france?")
        wc = json.loads(call("GET", "/_calls", base="http://127.0.0.1:18114")[2])
        check("weaviate: a near-duplicate from the same key is served from the store", hl(vw2).get("x-bf-cache") == "semantic-hit" and hl(vw1).get("x-bf-cache") != "semantic-hit", (vw1, vw2))
        check("weaviate: another virtual key does not see the entry (identity scoping)", hl(vw3).get("x-bf-cache") != "semantic-hit", vw3)
        check("weaviate: the schema, objects and nearVector queries reach the server", {"method": "POST", "path": "/v1/schema"} in wc and {"method": "POST", "path": "/v1/objects"} in wc and {"method": "POST", "path": "/v1/graphql"} in wc, wc[-5:])
        _, vp1, _ = vs_chat(18111, "openai/gpt-4o-mini", "sk-bf-a", "what is the capital of france")
        _, vp2, _ = vs_chat(18111, "openai/gpt-4o-mini", "sk-bf-a", "what is the capital of france?")
        check("pinecone: a near-duplicate is served from the index", hl(vp2).get("x-bf-cache") == "semantic-hit" and hl(vp1).get("x-bf-cache") != "semantic-hit", (vp1, vp2))
        _, vt1, _ = vs_chat(18111, "openai/agent-weather", "sk-bf-a", "weather in oslo")
        _, vt2, _ = vs_chat(18111, "openai/agent-weather", "sk-bf-a", "weather in oslo?")
        check("pinecone: a response with tool calls is not kept", hl(vt1).get("x-bf-cache") != "semantic-hit" and hl(vt2).get("x-bf-cache") != "semantic-hit", (vt1, vt2))
        pc = json.loads(call("GET", "/_calls", base="http://127.0.0.1:18115")[2])
        check("pinecone: upserts and queries reach the index", {"method": "POST", "path": "/vectors/upsert"} in pc and {"method": "POST", "path": "/query"} in pc, pc[-5:])
        _, vc1, _ = vs_chat(18112, "openai/gpt-4o-mini", "sk-bf-a", "what is the capital of france")
        _, vc2, _ = vs_chat(18112, "openai/gpt-4o-mini", "sk-bf-b", "what is the capital of france?")
        check("chromem: with disable_identity_scoping another key's entry is served", hl(vc2).get("x-bf-cache") == "semantic-hit" and hl(vc1).get("x-bf-cache") != "semantic-hit", (vc1, vc2))
        gw_vc.terminate(); gw_vc.wait()
        gw_vc = vs_gateway("chromem", 18112)
        wait("http://127.0.0.1:18112/health")
        _, vc3, _ = vs_chat(18112, "openai/gpt-4o-mini", "sk-bf-b", "what is the capital of france?")
        check("chromem: entries survive a restart from their file", hl(vc3).get("x-bf-cache") == "semantic-hit" and os.path.exists(os.path.join(BUILD, "e2e-chromem", "E2eSemChromem.jsonl")), vc3)
        s1, _, _ = bchat("openai/custom-model", BK)
        s2, _, b2 = bchat("openai/custom-model", BK)
        check("pricing_overrides price an unknown model, so its budget runs down", s1 == 200 and s2 == 402, (s1, s2, b2))
        log = open(os.path.join(BUILD, "e2e.bifrost.log")).read()
        check("unknown config keys are reported at startup", 'unknown key "server" is ignored' in log, log[:600])

        # Bifrost's x-bifrost-* response headers
        _, h, _ = chat("openai/gpt-4o-mini", seed=1400, headers={"x-bf-mcp-include-clients": "none"})
        H = hl(h)
        check("routed-identity headers", H.get("x-bifrost-provider") == "openai" and H.get("x-bifrost-resolved-model") == "gpt-4o-mini" and H.get("x-bifrost-original-model") == "openai/gpt-4o-mini" and H.get("x-bifrost-request-type") == "chat_completion" and H.get("x-bifrost-fallback-index") == "0" and "x-bifrost-latency-ms" in H and H.get("x-bifrost-cache-hit") == "false", H)
        _, h, _ = chat("openai/gpt-4o-mini", seed=1400, headers={"x-bf-mcp-include-clients": "none"})
        H = hl(h)
        check("cache headers on a hit", H.get("x-bifrost-cache-hit") == "true" and H.get("x-bifrost-cache-hit-type") == "direct", H)
        check("cache id and hit latency on a direct hit", H.get("x-bifrost-cache-id", "") != "" and "x-bifrost-cache-hit-latency-ms" in H, H)
        _, h, _ = chat("openai/down-model", extra=None, fallbacks=["anthropic/claude-fallback"], seed=1401)
        H = hl(h)
        check("fallback headers", H.get("x-bifrost-fallback-index") == "1" and H.get("x-bifrost-routing-info-is-fallback") == "true" and H.get("x-bifrost-provider") == "anthropic", H)
        _, h, _ = call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "x"}]}, {"origin": "http://localhost:3000"})
        check("CORS exposes the gateway's headers", "x-bifrost-provider" in hl(h).get("access-control-expose-headers", ""), hl(h).get("access-control-expose-headers"))
        _, h, _ = chat("openai/limited-model", seed=1402, headers={"origin": "http://localhost:3000"})
        H = hl(h)
        check("retry-after-ms and error type on an upstream 429", H.get("x-bifrost-retry-after-ms") == "2500" and H.get("x-bifrost-error-type") == "rate_limit" and H.get("x-bifrost-provider") == "openai", H)
        exposed = H.get("access-control-expose-headers", "")
        check("CORS exposes the retry, cache-id and routing-info headers", "x-bifrost-retry-after-ms" in exposed and "x-bifrost-cache-id" in exposed and "x-bifrost-routing-info-key" in exposed, exposed)

        # --- X07 ---
        req = urllib.request.Request(GW + "/openai/v1/audio/speech", data=json.dumps({"model": "openai/tts-1", "input": "hi", "voice": "alloy"}).encode(), method="POST", headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            audio = res.read()
        check("the OpenAI SDK route serves audio under /openai/v1", audio[:3] == b"ID3", audio[:10])
        s, _, b = call("POST", "/pydanticai/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "via pydantic"}]})
        check("PydanticAI route prefix", s == 200 and "Hello from gpt-4o-mini" in b, b)
        s, _, b = call("GET", "/openai/v1/models/openai/gpt-4o-mini")
        check("model retrieve", s == 200 and json.loads(b)["id"] == "openai/gpt-4o-mini" and json.loads(b)["owned_by"] == "openai", b)
        s, _, _ = call("GET", "/v1/models/nope/x")
        check("model retrieve for an unknown provider is 404", s == 404, s)
        s, _, b = chat("proxied/gpt-4o-mini", seed=990, headers={"x-bf-mcp-include-clients": "none"})
        import base64 as _b64
        check("provider requests go through its HTTP proxy with credentials", s == 200 and "via proxy" in b and proxied and proxied[-1]["target"] == "http://upstream.example:8000/v1/chat/completions" and proxied[-1]["auth"] == "Basic " + _b64.b64encode(b"proxy-user:pa:ss").decode(), (s, b, proxied))
        s, _, b = call("POST", "/litellm/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "via litellm"}]})
        check("LiteLLM route prefix", s == 200 and "Hello from gpt-4o-mini" in b, b)
        s, _, b = call("GET", "/langchain/v1/models")
        check("LangChain route prefix", s == 200 and '"data"' in b, b[:200])
        s, _, b = call("POST", "/v1/ocr", {"model": "openai/mistral-ocr-latest", "document": {"type": "document_url", "document_url": "https://example.com/a.pdf"}})
        check("OCR passes through", s == 200 and seen()[-1]["path"] == "/v1/ocr" and json.loads(seen()[-1]["body"])["model"] == "mistral-ocr-latest", (s, b, seen()[-1]))

        # Azure-style deployment paths (Bifrost's /openai/deployments/{deployment}/{op}): the deployment is the
        # model ("azure/{deployment}", or "{provider}/{deployment}"), the caller's api-version is ignored, and the
        # call reaches the /v1 route of its operation. The mock records the deployment call, then the /v1 call.
        DEP = "/openai/deployments/"
        CHAT = [{"role": "user", "content": "hi"}]
        s, _, b = call("POST", DEP + "prod-4o/chat/completions?api-version=2024-02-15-preview", {"model": "ignored", "messages": CHAT})
        up = seen()
        check("deployment chat: azure/{deployment} is the model, the caller's api-version is dropped", s == 200 and "Hello from prod-4o" in b and up[-2]["path"] == DEP + "prod-4o/chat/completions?api-version=2024-10-21" and up[-1]["path"] == "/v1/chat/completions" and json.loads(up[-1]["body"])["model"] == "prod-4o", (s, b, up[-2:]))
        s, _, b = call("POST", DEP + "openai/gpt-4o-mini/chat/completions", {"model": "ignored", "messages": CHAT})
        check("deployment chat: provider/deployment is the model", s == 200 and "Hello from gpt-4o-mini" in b and seen()[-1]["path"] == "/v1/chat/completions" and json.loads(seen()[-1]["body"])["model"] == "gpt-4o-mini", (s, b, seen()[-1]))
        s, _, b = call("POST", DEP + "prod-4o/chat/completions", {"model": "ignored", "stream": True, "messages": CHAT})
        check("deployment chat streams", s == 200 and '"content":"Hel"' in b and b.rstrip().endswith("data: [DONE]") and json.loads(seen()[-1]["body"])["model"] == "prod-4o", (s, b[:300]))
        s, _, b = call("POST", DEP + "openai/gpt-4o-mini/chat/completions", {"model": "ignored", "stream": True, "messages": CHAT})
        check("deployment chat with provider/deployment streams", s == 200 and '"content":"Hel"' in b and b.rstrip().endswith("data: [DONE]"), (s, b[:300]))
        s, _, b = call("POST", DEP + "prod-emb/embeddings", {"model": "ignored", "input": "hello"})
        check("deployment embeddings", s == 200 and '"embedding"' in b and seen()[-1]["path"] == "/v1/embeddings" and json.loads(seen()[-1]["body"])["model"] == "prod-emb", (s, b[:200], seen()[-1:]))
        s, _, b = call("POST", DEP + "prod-img/images/generations", {"model": "ignored", "prompt": "a red fox", "n": 1})
        check("deployment images", s == 200 and "fox.png" in b and seen()[-1]["path"] == "/v1/images/generations" and json.loads(seen()[-1]["body"])["model"] == "prod-img", (s, b, seen()[-1:]))
        req = urllib.request.Request(GW + DEP + "prod-tts/audio/speech", data=json.dumps({"model": "ignored", "input": "hi", "voice": "alloy"}).encode(), method="POST", headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            audio = res.read(); ctype = res.headers.get("content-type")
        check("deployment speech returns the audio bytes", audio == bytes([0x49, 0x44, 0x33, 0xff, 0xfb, 0x90, 0x00, 0x80, 0xc3, 0x28]) and ctype == "audio/mpeg" and json.loads(seen()[-1]["body"])["model"] == "prod-tts", (audio, ctype, seen()[-1:]))
        s, b = multipart(DEP + "prod-stt/audio/transcriptions", "clip.wav", b"RIFF-fake-audio", {"model": "whisper-1", "response_format": "json"})
        check("deployment transcription: the deployment replaces the form's model", s == 200 and "transcribed by prod-stt" in b and seen()[-1]["path"] == "/v1/audio/transcriptions" and json.loads(seen()[-1]["body"])["model"] == "prod-stt", (s, b, seen()[-1:]))
        s, _, b = call("POST", DEP + "openai/gpt-4o/responses", {"model": "ignored", "input": "hi"})
        check("deployment responses", s == 200 and "native responses" in b and seen()[-1]["path"] == "/v1/responses" and json.loads(seen()[-1]["body"])["model"] == "gpt-4o", (s, b, seen()[-1:]))
        s, _, b = call("POST", DEP + "prod-resp/responses", {"model": "ignored", "input": "hi"})
        check("deployment responses through the chat bridge for azure", s == 200 and "Hello from prod-resp" in b, (s, b))
        s, _, _ = call("GET", DEP + "prod-4o/models")
        check("deployment models is not routed, as in Bifrost", s == 404, s)

        # the workers of one node share rate limits and the response cache
        if os.environ.get("RAIJU_SERVER", "bun") == "bun":
            wait("http://127.0.0.1:18094/health")
            WGW = "http://127.0.0.1:18094"
            codes = []
            for i in range(6):
                codes.append(call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "w"}], "seed": 1300 + i}, {"x-bf-vk": "sk-bf-workers"}, base=WGW)[0])
                time.sleep(0.4)
            check("workers share a rate limit", codes == [200, 200, 200, 429, 429, 429], codes)
            hits = []
            for i in range(5):
                _, h, _ = call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "cache me across workers"}]}, base=WGW)
                hits.append(hl(h).get("x-bf-cache", "miss"))
            check("workers share the response cache", hits == ["miss", "hit", "hit", "hit", "hit"], hits)
            stats = [json.loads(call("GET", "/api/logs/stats", base=WGW)[2])["requests"] for _ in range(4)]
            check("any worker reports every worker's request logs", stats == [11] * 4, stats)
            time.sleep(1.3)
            def upstream_total():
                b = call("GET", "/metrics", base=WGW)[2]
                return sum(float(l.rsplit(" ", 1)[1]) for l in b.split("\n") if l.startswith("bifrost_upstream_requests_total{"))
            totals = [upstream_total() for _ in range(4)]
            check("any worker's /metrics sums every worker", totals == [4.0] * 4, totals)

        # --- wave 6 ---
        # clustering: a rate limit of 3 requests shared by both nodes
        vk = {"x-bf-vk": "sk-bf-cluster", "x-bf-mcp-include-clients": "none"}
        r1 = [chat("openai/gpt-4o-mini", headers=vk, seed=950 + i)[0] for i in range(2)]
        time.sleep(0.8)
        r2 = [call("POST", "/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "seed": 960 + i}, vk, base=GW_B)[0] for i in range(2)]
        check("cluster nodes share rate-limit usage", r1 == [200, 200] and r2 == [200, 429], (r1, r2))
        s, _, _ = call("POST", "/api/cluster/sync", "{}", {"x-raiju-cluster-sig": "00"}, auth=False)
        check("cluster sync needs the shared secret", s == 401, s)

        # log exports to S3-compatible storage
        time.sleep(1.5)
        puts = [x for x in seen() if x["path"].startswith("/logs/raiju-logs/")]
        lines = [json.loads(l) for x in puts for l in x["body"].strip().split("\n") if l]
        check("request logs are exported to object storage", puts and puts[0]["path"].endswith(".jsonl") and puts[0]["auth"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/") and any("gpt-4o-mini" in l.get("model", "") for l in lines), [p["path"] for p in puts][:3])

        # log exporters
        hooks = [x for x in seen() if x["path"] == "/export-hook"]
        bulk = [x for x in seen() if x["path"] == "/_bulk"]
        lines = [json.loads(l) for x in hooks for l in x["body"].strip().split("\n") if l]
        check("request logs reach an HTTP exporter as NDJSON", hooks and any("gpt-4o-mini" in l.get("model", "") for l in lines), [h["body"][:200] for h in hooks[:1]])
        bl = bulk[0]["body"].split("\n") if bulk else []
        check("request logs reach Elasticsearch's bulk API", bulk and bulk[0]["auth"] == "ApiKey es-key" and '"_index":"raiju-' in bl[0] and bulk[0]["body"].endswith("\n"), [b["body"][:200] for b in bulk[:1]])

        # SSO (OIDC, authorization code + PKCE)
        import http.client, base64, hashlib
        s, _, b = call("GET", "/api/oidc/status", auth=False)
        check("SSO status is public", s == 200 and json.loads(b)["enabled"] is True, b)
        conn = http.client.HTTPConnection("127.0.0.1", 18098, timeout=10)
        conn.request("GET", "/api/oidc/login"); r = conn.getresponse(); r.read()
        loc = r.getheader("location") or ""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
        check("SSO login redirects to the provider with PKCE", r.status == 302 and loc.startswith("http://127.0.0.1:18096/authorize?") and q.get("code_challenge_method") == ["S256"] and q.get("client_id") == ["raiju"], loc)
        idp_state["nonce"] = q.get("nonce", [""])[0]
        st = q.get("state", [""])[0]
        s, _, page = call("GET", "/api/oidc/callback?code=abc&state=" + st, auth=False)
        verifier = idp_state["verifier"]
        check("the token request carries the PKCE verifier", base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode() == q.get("code_challenge", [""])[0], verifier)
        import re as _re
        m = _re.search(r'"(sk-sess-[0-9a-f]+)"', page)
        check("SSO callback signs the browser in", s == 200 and m is not None, (s, page[:300]))
        S = {"authorization": "Bearer " + (m.group(1) if m else "none")}
        s1, _, _ = call("GET", "/api/config", headers=S)
        s2, _, _ = call("POST", "/api/governance/budgets", {"id": "sso-made", "max_limit": 5, "reset_duration": "1d"}, headers=S)
        s3, _, _ = call("POST", "/api/users", {"name": "x", "role": "admin"}, headers=S)
        check("an SSO editor (from the groups claim) reads and edits but can't manage users", (s1, s3) == (200, 403) and s2 < 300, (s1, s2, s3))
        s, _, _ = call("GET", "/api/oidc/callback?code=abc&state=" + st, auth=False)
        check("an SSO state can't be reused", s == 401, s)
        s, _, b = call("GET", "/api/audit-logs")
        check("SSO changes are audited under the user", '"actor":"sso:alice"' in b, b[-400:])

        s, _, b = call("POST", "/api/governance/model-configs", {"model_name": "gpt-mc", "provider": "openai", "rate_limit": {"request_max_limit": 1, "request_reset_duration": "1h"}})
        mcid = json.loads(b).get("id", "") if s == 201 else ""
        s1, _, _ = chat("openai/gpt-mc", seed=1701)
        s2, _, b2 = chat("openai/gpt-mc", seed=1702)
        s3, _, _ = chat("openai/gpt-4o-mini", seed=1703)
        check("a model config's rate limit applies to that model only", s == 201 and (s1, s2, s3) == (200, 429, 200), (s, s1, s2, s3, b2))
        s, _, _ = call("DELETE", "/api/governance/model-configs/" + mcid)
        check("model configs delete", s == 200, s)

        s, _, b = call("GET", "/metrics")
        check("prometheus metrics", 'bifrost_upstream_requests_total{provider="openai"' in b and "bifrost_cost_total" in b, b[:500])
        import re as _re
        check("Bifrost metric families and labels",
              all(f in b for f in ["bifrost_success_requests_total{", "bifrost_error_requests_total{", "bifrost_stream_first_token_latency_seconds_bucket{", "http_requests_total{path=\"/v1/chat/completions\""])
              and _re.search(r'bifrost_success_requests_total\{[^}]*method="chat_completion"[^}]*virtual_key_id="', b) is not None
              and _re.search(r'bifrost_error_requests_total\{[^}]*status_code="5\d\d"', b) is not None, b[:800])
        check("Bifrost gauge and key families",
              "# TYPE bifrost_active_requests gauge" in b and 'bifrost_active_requests{method="chat_completion"} 0' in b
              and _re.search(r'bifrost_provider_key_up\{provider="openai",key_id="[^"]*",key_name="[^"]*"\} [01]', b) is not None, b[:800])

        s, _, b = call("POST", "/v1/chat/completions", "{not json")
        check("bad JSON is a 400", s == 400, b)

        # Direct keys: the caller's own key replaces the pool key, only with the header and the server setting
        wait(GW_D + "/health")
        def msg(text, model="openai/gpt-4o-mini", **kw):
            return {"model": model, "messages": [{"role": "user", "content": text}], **kw}
        s, _, b = call("POST", "/v1/chat/completions", msg("direct-1"), {"x-bf-direct-key": "true", "authorization": "Bearer sk-caller"}, base=GW_D)
        check("a direct key serves the request without a virtual key", s == 200 and seen()[-1]["auth"] == "Bearer sk-caller", (s, b, seen()[-1]))
        s, _, b = call("POST", "/v1/chat/completions", msg("direct-2"), {"authorization": "Bearer sk-caller"}, base=GW_D)
        check("without x-bf-direct-key the same bearer is not a credential", s == 401, (s, b))
        s, _, b = call("POST", "/v1/chat/completions", msg("direct-3", "anthropic/claude-sonnet-4", max_tokens=20), {"x-bf-direct-key": "true", "x-api-key": "sk-ant-caller"}, base=GW_D)
        check("a direct x-api-key goes upstream to its provider", s == 200 and seen()[-1]["auth"] == "sk-ant-caller", (s, b, seen()[-1]))
        s, _, b = call("POST", "/v1/chat/completions", msg("direct-4"), {"x-bf-direct-key": "true", "authorization": "Bearer sk-bf-direct-vk"}, base=GW_D)
        check("a virtual key in Authorization is not a direct key", s == 200 and seen()[-1]["auth"] == "Bearer sk-pool", (s, b, seen()[-1]))
        s, _, b = call("POST", "/v1/chat/completions", msg("direct-5"), {"x-bf-direct-key": "true", "authorization": "Bearer sk-caller"}, base=GW)
        check("direct keys are ignored unless client.allow_direct_keys is on", s == 200 and seen()[-1]["auth"] == "Bearer sk-from-env", (s, b, seen()[-1]))
        # the GenAI routes need a virtual key while auth is enforced (the Gemini provider is not in this config)
        s, _, b = call("GET", "/genai/v1beta/files", base=GW_D)
        check("genai files need a virtual key when auth is enforced", s == 401, (s, b))
        s, _, b = call("POST", "/genai/v1/rank", {"model": "raiju/lexical", "query": "q", "records": [{"id": "a", "content": "x"}]}, base=GW_D)
        check("genai rank needs a virtual key when auth is enforced", s == 401, (s, b))
        s, _, b = call("GET", "/genai/v1beta/files", None, {"authorization": "Bearer sk-bf-direct-vk"}, base=GW_D)
        check("genai files with a virtual key get past the check", s != 401, (s, b))

        # Raw echo: the provider's send_back_raw_response, and per-request headers when allowed
        VK = {"authorization": "Bearer sk-bf-direct-vk"}
        s, _, b = call("POST", "/v1/chat/completions", msg("raw-1"), VK, base=GW_D)
        ef = json.loads(b).get("extra_fields", {})
        check("send_back_raw_response puts the upstream body in extra_fields", s == 200 and ef.get("raw_response", {}).get("choices", [{}])[0].get("message", {}).get("content") == "Hello from gpt-4o-mini" and "raw_request" not in ef, b)
        s, _, b = call("POST", "/v1/chat/completions", msg("raw-2"), {**VK, "x-bf-send-back-raw-request": "true"}, base=GW_D)
        ef = json.loads(b).get("extra_fields", {})
        check("x-bf-send-back-raw-request echoes the upstream request", s == 200 and ef.get("raw_request", {}).get("model") == "gpt-4o-mini" and ef["raw_request"]["messages"][0]["content"] == "raw-2", b)
        s, _, b = call("POST", "/v1/chat/completions", msg("raw-3", "anthropic/claude-sonnet-4", max_tokens=20), VK, base=GW_D)
        check("no raw fields unless asked for", s == 200 and "extra_fields" not in json.loads(b), b)
        s, _, b = call("POST", "/v1/chat/completions", msg("raw-4"), {"x-bf-send-back-raw-response": "true"}, base=GW)
        check("per-request raw headers are ignored without allow_per_request_raw_override", s == 200 and "extra_fields" not in json.loads(b), b)

        # prometheus_labels: named labels filled from x-bf-dim-<name> headers, empty when absent
        s, _, b = call("POST", "/v1/chat/completions", msg("labels-1"), {**VK, "x-bf-dim-env": "prod"}, base=GW_D)
        _, _, m = call("GET", "/metrics", base=GW_D)
        check("prometheus_labels are filled from x-bf-dim headers", s == 200 and _re.search(r'bifrost_upstream_requests_total\{[^}]*env="prod",team=""\}', m) is not None, m[:400])
        check("drop_excess_requests logs that it has no effect", "drop_excess_requests has no effect" in open(os.path.join(BUILD, "e2e.direct.log")).read(), "")

        # ---- provider passthroughs (passthrough.tov) ----
        s, _, b = call("POST", "/openai_passthrough/pt/echo?x=1", {"a": 1}, headers={"authorization": "Bearer caller-key", "x-bf-vk": "sk-bf-nope", "anthropic-beta": "beta-1"})
        pe = json.loads(b) if s == 200 else {}
        check("openai passthrough: POST, query and body reach the provider unchanged", s == 200 and pe.get("method") == "POST" and pe.get("path") == "/pt/echo" and pe.get("query") == "?x=1" and json.loads(pe.get("body", "{}")) == {"a": 1}, (s, b))
        check("openai passthrough: the key's auth replaces the caller's, gateway headers stay home, caller headers go", seen()[-1]["auth"] == "Bearer sk-from-env" and "anthropic-beta=beta-1" in pe.get("headers", []) and "authorization=Bearer caller-key" not in pe.get("headers", []) and not any(x.startswith("x-bf-vk=") for x in pe.get("headers", [])), (seen()[-1], pe))
        s, _, b = call("GET", "/anthropic_passthrough/pt/echo?beta=true", headers={"x-api-key": "caller-ant"})
        pe = json.loads(b) if s == 200 else {}
        check("anthropic passthrough: x-api-key and anthropic-version", s == 200 and pe.get("method") == "GET" and "anthropic-version=2023-06-01" in pe.get("headers", []) and seen()[-1]["auth"] == "sk-ant", (s, b, seen()[-1]))
        s, _, b = call("POST", "/genai_passthrough/pt/echo", {"contents": []})
        check("genai passthrough: x-goog-api-key", s == 200 and seen()[-1]["auth"] == "g-key" and json.loads(seen()[-1]["body"]) == {"contents": []}, (s, b))
        s, _, b = call("GET", "/azure_passthrough/pt/echo?api-version=2024-02-01")
        check("azure passthrough: api-key and the caller's api-version query", s == 200 and seen()[-1]["auth"] == "az-key" and json.loads(b)["query"] == "?api-version=2024-02-01", (s, b, seen()[-1]))
        s, _, b = call("POST", "/bedrock_passthrough/knowledgebases/KB1/retrieve", {"retrievalQuery": {"text": "hi"}})
        kb = [x for x in seen() if x["path"] == "/knowledgebases/KB1/retrieve"]
        check("bedrock passthrough: SigV4-signed retrieve", s == 200 and len(kb) > 0 and kb[-1]["auth"].startswith("AWS4-HMAC-SHA256"), (s, b, kb[-1:]))
        s, _, b = call("POST", "/bedrock_passthrough/model/anthropic.claude/converse", {"messages": []})
        check("bedrock passthrough refuses operations other than InvokeAgent, Retrieve and ApplyGuardrail", s == 400 and "only forwards" in b, (s, b))
        s, h, b = call("GET", "/openai_passthrough/pt/sse")
        check("passthrough streams an event stream back unchanged", s == 200 and b == "data: one\n\ndata: two\n\n" and {k.lower(): v for k, v in h.items()}.get("content-type", "").startswith("text/event-stream") and {k.lower(): v for k, v in h.items()}.get("x-upstream-tag") == "sse", (s, h, b))
        s, h, b = call("GET", "/openai_passthrough/pt/gzip")
        hl = {k.lower(): v for k, v in h.items()}
        check("passthrough does not relay the gateway's own or encoding headers", s == 200 and "x-bf-internal" not in hl and "content-encoding" not in hl, hl)
        s, _, b = call("GET", "/openai_passthrough/pt/x%2Fsecret")
        check("passthrough refuses encoded slashes", s == 400 and "invalid passthrough path" in b, (s, b))
        s, _, b = call("POST", "/chatgpt_passthrough/backend-api/other", {})
        check("chatgpt passthrough forwards only the Codex responses endpoint", s == 404 and "codex/responses" in b, (s, b))
        s, _, b = call("GET", "/runware_passthrough/v1/tasks")
        check("runware passthrough is not served", s == 404, (s, b))
        s, _, b = call("GET", "/api/version")
        check("GET /api/version", s == 200 and json.loads(b) == "0.1.0", (s, b))
        s, _, b = call("GET", "/api/keys")
        check("GET /api/keys lists keys with secrets masked", s == 200 and any(k.get("provider") == "openai" for k in json.loads(b)) and "bad-key" not in b and '"sk-ant"' not in b, b[:300])
        s, _, b = call("GET", "/api/models?provider=openai&limit=50")
        check("GET /api/models lists the configured models in Bifrost's shape", s == 200 and {"name": "rotate-me", "provider": "openai"} in json.loads(b)["models"], (s, b))
        s, _, b = call("GET", "/api/models/nope")
        check("GET /api/models/{provider} is a 404 for an unknown provider", s == 404, (s, b))
        s, _, b = call("GET", "/api/config")
        client = json.loads(b).get("client", {})
        client["drop_excess_requests"] = True
        s, _, b = call("PUT", "/api/config", {"client_config": client})
        s2, _, b2 = call("GET", "/api/config")
        check("PUT /api/config replaces the client section and saves it", s == 200 and json.loads(b2)["client"].get("drop_excess_requests") is True, (s, b, b2[:300]))
        s, _, b = call("PUT", "/api/config", {"client_config": {"no_such_setting": 1}})
        check("PUT /api/config refuses unknown settings", s == 400, (s, b))
        s, _, b = call("POST", "/api/pricing/force-sync")
        check("pricing force-sync reports a failed datasheet fetch", s == 500 and "HTTP 404" in b, (s, b))
        s, _, b = call("GET", "/api/pricing/force-sync")
        check("pricing force-sync is POST only", s == 405, (s, b))
        # the virtual-key gate, on the gateway that enforces inference auth
        GW_BF = "http://127.0.0.1:18093"
        s, _, b = call("POST", "/openai_passthrough/pt/echo", {}, base=GW_BF)
        check("passthrough needs a virtual key when inference auth is enforced", s == 401, (s, b))
        s, _, b = call("POST", "/openai_passthrough/pt/echo", {}, headers={"x-bf-vk": "sk-bf-dialect"}, base=GW_BF)
        check("passthrough with a virtual key goes through", s == 200 and seen()[-1]["auth"] == "Bearer sk-from-env", (s, b))
        # cluster discovery and the identity-aware proxies (their own gateways and mocks)
        discovery_and_proxy()
    finally:
        gw.terminate(); gw_b.terminate(); gw_d.terminate(); mock.terminate(); qdrant.terminate(); gw_w.terminate(); gw_bf.terminate(); idp.shutdown(); proxy.shutdown(); tls_up.shutdown()
        gw_vw.terminate(); gw_vp.terminate(); gw_vc.terminate(); weav.terminate(); pine.terminate()
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)

main()
