#!/usr/bin/env python3
"""End-to-end tests: runs the gateway against the mock upstream.

Usage: tests/e2e.py  (builds both binaries into ./build first)
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
GW = "http://127.0.0.1:18098"
MOCK = "http://127.0.0.1:18099"

def build():
    os.makedirs(BUILD, exist_ok=True)
    for src, out in [("src/main.tov", "raiju"), ("tests/mock_upstream.tov", "mock_upstream")]:
        env = {**os.environ, "TOV_CFLAGS": os.environ.get("TOV_CFLAGS", "-DTV_PLAIN_ALLOC")}
        subprocess.run(["tov", "build", os.path.join(ROOT, src), "-o", os.path.join(BUILD, out)], check=True, capture_output=True, env=env)

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
    cfg["providers"]["vertex"] = {
        "keys": [{"name": "vx", "models": [], "weight": 1.0, "vertex_key_config": {"project_id": "proj", "region": "us-central1", "auth_credentials": json.dumps(sa)}}],
        "network_config": {"base_url": MOCK},
    }
    path = os.path.join(BUILD, "e2e.config.json")
    json.dump(cfg, open(path, "w"))
    return path

def main():
    build()
    config = write_config()
    import shutil
    shutil.rmtree(os.path.join(ROOT, "build/e2e-logs"), ignore_errors=True)
    env = {**os.environ, "E2E_OPENAI_KEY": "sk-from-env", "E2E_ADMIN_TOKEN": "admin-secret", "MOCK_PORT": "18099"}
    mock = subprocess.Popen([os.path.join(BUILD, "mock_upstream")], env=env, stdout=subprocess.DEVNULL)
    gw = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", "18098", "-host", "127.0.0.1", "-config", config], env=env, stderr=subprocess.DEVNULL)
    try:
        wait(MOCK + "/_seen"); wait(GW + "/health")

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
        check("non-openai streaming replayed as SSE", s == 200 and '"delta":{"content":"Hi from claude"}' in b and '"usage":' in b and b.endswith("data: [DONE]\n\n"), b)

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

        # Media pass-through keeps binary bodies and content types
        req = urllib.request.Request(GW + "/v1/audio/speech", data=json.dumps({"model": "openai/tts-1", "input": "hi", "voice": "alloy"}).encode(), method="POST", headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as res:
            audio = res.read(); ctype = res.headers.get("content-type")
        check("audio speech pass-through", audio == b"ID3fake-mp3-bytes" and ctype == "audio/mpeg" and json.loads(seen()[-1]["body"])["model"] == "tts-1", (audio, ctype))

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

        s, _, b = call("GET", "/metrics")
        check("prometheus metrics", 'bifrost_upstream_requests_total{provider="openai"' in b and "bifrost_cost_total" in b, b[:500])

        s, _, b = call("POST", "/v1/chat/completions", "{not json")
        check("bad JSON is a 400", s == 400, b)
    finally:
        gw.terminate(); mock.terminate()
    print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
    sys.exit(1 if FAILS else 0)

main()
