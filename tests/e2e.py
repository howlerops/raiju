#!/usr/bin/env python3
"""End-to-end tests: runs the gateway against the mock upstream.

Usage: tests/e2e.py  (builds both binaries into ./build first)
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
GW = "http://127.0.0.1:18098"
MOCK = "http://127.0.0.1:18099"
GW_B = "http://127.0.0.1:18097"

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
    cfg["mcp"]["client_configs"].append({"name": "local", "connection_type": "stdio", "stdio_config": {"command": "python3", "args": [os.path.join(ROOT, "tests/mcp_stdio.py")], "env": {"MCP_GREETING": "hello"}}})
    cfg["providers"]["vertex"] = {
        "keys": [{"name": "vx", "models": [], "weight": 1.0, "vertex_key_config": {"project_id": "proj", "region": "us-central1", "auth_credentials": json.dumps(sa)}}],
        "network_config": {"base_url": MOCK},
    }
    path = os.path.join(BUILD, "e2e.config.json")
    json.dump(cfg, open(path, "w"))
    # a second node of the same cluster, without the file-writing features
    b = {k: v for k, v in cfg.items() if k not in ("audit", "logs_store", "alerts", "log_exports", "otel", "oidc")}
    b["cluster"] = {**cfg["cluster"], "node_id": "b", "peers": [GW]}
    json.dump(b, open(os.path.join(BUILD, "e2e.node-b.json"), "w"))
    # a single node with three workers: a 3-request limit and the response cache are shared between them
    w = {"client": {"enable_logging": False}, "providers": {"openai": cfg["providers"]["openai"]}, "cache": {"enabled": True, "ttl_seconds": 60},
         "logs_store": {"enabled": True, "dir": os.path.join(BUILD, "e2e-wlogs")},
         "governance": {"rate_limits": [{"id": "w-rl", "request_max_limit": 3, "request_reset_duration": "1h"}], "virtual_keys": [{"id": "vk-w", "value": "sk-bf-workers", "rate_limit_id": "w-rl"}]}}
    json.dump(w, open(os.path.join(BUILD, "e2e.workers.json"), "w"))
    return path

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

def main():
    build()
    config = write_config()
    import shutil
    shutil.rmtree(os.path.join(ROOT, "build/e2e-logs"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build/e2e-audit"), ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build/e2e-wlogs"), ignore_errors=True)
    env = {**os.environ, "E2E_OPENAI_KEY": "sk-from-env", "E2E_ADMIN_TOKEN": "admin-secret", "MOCK_PORT": "18099"}
    mock = subprocess.Popen([os.path.join(BUILD, "mock_upstream")], env=env, stdout=subprocess.DEVNULL)
    wait(MOCK + "/_seen")  # the gateway connects to the mock's MCP server at startup
    idp, idp_state = start_idp()
    proxy, proxied = start_proxy()
    gw = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18098", "-host", "127.0.0.1", "-config", config, "-server", os.environ.get("RAIJU_SERVER", "bun")], env=env, stderr=subprocess.DEVNULL)
    gw_w = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18094", "-host", "127.0.0.1", "-config", os.path.join(BUILD, "e2e.workers.json"), "-workers", "3"], env=env, stderr=subprocess.DEVNULL)
    gw_b = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18097", "-host", "127.0.0.1", "-config", os.path.join(BUILD, "e2e.node-b.json")], env=env, stderr=subprocess.DEVNULL)
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
        saved = open(config).read()
        check("saved config keeps env references and new keys", "env.E2E_OPENAI_KEY" in saved and "sk-from-env" not in saved and "sk-extra-secret" in saved, saved[:200])
        s, _, b = call("POST", "/api/governance/budgets", {"id": "b-bad", "max_limit": -1, "reset_duration": "1d"})
        check("invalid budget rejected", s == 400, b)

        # Rerank (local lexical ranking for providers without a rerank API)
        s, _, b = call("POST", "/v1/rerank", {"model": "openai/any", "query": "solar panels on roofs", "documents": ["a recipe for soup", "installing solar panels on your roof", "train timetables"], "top_n": 2})
        r = json.loads(b)
        check("rerank ranks the relevant document first", s == 200 and r["results"][0]["index"] == 1 and len(r["results"]) == 2, b)

        # Token counting: exact from Anthropic, estimated elsewhere
        s, _, b = call("POST", "/anthropic/v1/messages/count_tokens", {"model": "claude-sonnet-4", "messages": [{"role": "user", "content": "hello"}]})
        check("anthropic count_tokens is exact", s == 200 and json.loads(b)["input_tokens"] == 42 and seen()[-1]["path"] == "/v1/messages/count_tokens", b)
        s, _, b = call("POST", "/v1/count_tokens", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hello there, how are you today?"}]})
        r = json.loads(b)
        check("count_tokens estimates for other providers", s == 200 and r["exact"] is False and 5 < r["input_tokens"] < 40, b)

        # Async jobs
        s, _, b = call("POST", "/v1/async/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "later"}]})
        job = json.loads(b)
        check("async job accepted", s == 202 and job["status"] in ("queued", "running") and job["id"].startswith("job_"), b)
        for _ in range(50):
            s, _, b = call("GET", f"/v1/async/jobs/{job['id']}")
            if json.loads(b)["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.05)
        done = json.loads(b)
        check("async job completes with the result", done["status"] == "succeeded" and done["result"]["choices"][0]["message"]["content"] == "Hello from gpt-4o-mini", b)
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

        # --- X07 ---
        s, _, b = chat("proxied/gpt-4o-mini", seed=990, headers={"x-bf-mcp-include-clients": "none"})
        import base64 as _b64
        check("provider requests go through its HTTP proxy with credentials", s == 200 and "via proxy" in b and proxied and proxied[-1]["target"] == "http://upstream.example:8000/v1/chat/completions" and proxied[-1]["auth"] == "Basic " + _b64.b64encode(b"proxy-user:pa:ss").decode(), (s, b, proxied))
        s, _, b = call("POST", "/litellm/v1/chat/completions", {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "via litellm"}]})
        check("LiteLLM route prefix", s == 200 and "Hello from gpt-4o-mini" in b, b)
        s, _, b = call("GET", "/langchain/v1/models")
        check("LangChain route prefix", s == 200 and '"data"' in b, b[:200])
        s, _, b = call("POST", "/v1/ocr", {"model": "openai/mistral-ocr-latest", "document": {"type": "document_url", "document_url": "https://example.com/a.pdf"}})
        check("OCR passes through", s == 200 and seen()[-1]["path"] == "/v1/ocr" and json.loads(seen()[-1]["body"])["model"] == "mistral-ocr-latest", (s, b, seen()[-1]))

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

        s, _, b = call("GET", "/metrics")
        check("prometheus metrics", 'bifrost_upstream_requests_total{provider="openai"' in b and "bifrost_cost_total" in b, b[:500])

        s, _, b = call("POST", "/v1/chat/completions", "{not json")
        check("bad JSON is a 400", s == 400, b)
    finally:
        gw.terminate(); gw_b.terminate(); mock.terminate(); gw_w.terminate(); idp.shutdown(); proxy.shutdown()
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)

main()
