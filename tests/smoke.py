#!/usr/bin/env python3
"""Real-provider smoke tests: one gateway (port 18271) in front of every provider that has credentials in the
environment, and a small matrix per provider: chat whole and streamed, a tool call, embeddings where offered, the
provider's native route through Raiju, a request just over large_payload_optimization's threshold, and the usage
and cost of the log row. Providers without credentials are skipped; with none at all every check skips and the
exit status is 0. It exits 1 only when a check fails.

Usage: tests/smoke.py  (or make smoke; builds build/raiju unless SMOKE_NO_BUILD is set)

The config refers to secrets as env.NAME, so no key value is written to disk or printed; text that is printed
(an error body) has every credential value masked first. Spend is kept tiny: short prompts, max_tokens 16 to 64.
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
PORT = 18271
GW = f"http://127.0.0.1:{PORT}"
# large_payload_optimization is set low here so a few KiB take the streamed path
LARGE_THRESHOLD = 8192

# name, the environment variables that must be set, chat model, embeddings model ("" = none offered), native route
PROVIDERS = [
    ("openai", ["OPENAI_API_KEY"], "gpt-4.1-nano", "text-embedding-3-small", "responses"),
    ("anthropic", ["ANTHROPIC_API_KEY"], "claude-haiku-4-5", "", "messages"),
    ("gemini", ["GEMINI_API_KEY"], "gemini-2.5-flash-lite", "gemini-embedding-001", "genai"),
    ("mistral", ["MISTRAL_API_KEY"], "mistral-small-latest", "mistral-embed", ""),
    ("groq", ["GROQ_API_KEY"], "openai/gpt-oss-20b", "", ""),
    ("cohere", ["COHERE_API_KEY"], "command-r7b-12-2024", "embed-english-light-v3.0", "cohere"),
    ("xai", ["XAI_API_KEY"], "grok-4.20-non-reasoning", "", ""),
    ("openrouter", ["OPENROUTER_API_KEY"], "openai/gpt-4o-mini", "", ""),
    ("bedrock", ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"], "amazon.nova-micro-v1:0", "amazon.titan-embed-text-v2:0", "converse"),
    ("azure", ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"], "", "", ""),
    ("vertex", ["GOOGLE_APPLICATION_CREDENTIALS"], "gemini-2.5-flash-lite", "text-embedding-005", "genai"),
]

# variables whose values are masked in anything printed
SECRET_VARS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY", "COHERE_API_KEY",
               "XAI_API_KEY", "OPENROUTER_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
               "AZURE_OPENAI_API_KEY", "SMOKE_VERTEX_CREDENTIALS"]
# the gateway reads the service account JSON from this variable (the file's content, set for the child only)
VERTEX_CREDS_VAR = "SMOKE_VERTEX_CREDENTIALS"
OFF = ("-", "none", "off")


def model_for(env, name, default, kind=""):
    """SMOKE_<PROVIDER>_MODEL (or _EMBED_MODEL) when set, else the default; "-", "none" or "off" turn it off."""
    v = env.get(f"SMOKE_{name.upper()}_{kind}MODEL", "").strip()
    if v.lower() in OFF:
        return ""
    return v or default


def _read(path):
    with open(path) as f:
        return f.read()


def build_config(env, logs_dir, read_file=_read):
    """The gateway config for the providers that have credentials in env. Returns (config, extra child environment,
    plan, skipped): plan maps each configured provider to its {model, embed, native} names (models carry the
    provider prefix), skipped maps each other provider to the reason. Key values never appear in the config: keys
    are env.NAME references."""
    providers, plan, skipped, extra = {}, {}, {}, {}
    for name, need, chat, embed, native in PROVIDERS:
        missing = [v for v in need if not env.get(v)]
        if missing:
            skipped[name] = "no " + ", ".join(missing)
            continue
        key = {"name": f"smoke-{name}", "models": [], "weight": 1.0}
        if name == "bedrock":
            bk = {"access_key": "env.AWS_ACCESS_KEY_ID", "secret_key": "env.AWS_SECRET_ACCESS_KEY",
                  "region": env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1"}
            if env.get("AWS_SESSION_TOKEN"):
                bk["session_token"] = "env.AWS_SESSION_TOKEN"
            key["bedrock_key_config"] = bk
        elif name == "azure":
            key["value"] = "env.AZURE_OPENAI_API_KEY"
            key["azure_key_config"] = {"endpoint": "env.AZURE_OPENAI_ENDPOINT", "api_version": env.get("AZURE_OPENAI_API_VERSION") or "2024-10-21"}
            chat = env.get("AZURE_OPENAI_DEPLOYMENT", "")
            embed = env.get("AZURE_OPENAI_EMBED_DEPLOYMENT", "")
        elif name == "vertex":
            try:
                text = read_file(env["GOOGLE_APPLICATION_CREDENTIALS"])
                sa = json.loads(text)
            except (OSError, ValueError):
                skipped[name] = "GOOGLE_APPLICATION_CREDENTIALS is not a readable JSON file"
                continue
            if not isinstance(sa, dict) or sa.get("type") != "service_account":
                skipped[name] = "GOOGLE_APPLICATION_CREDENTIALS is not a service account key (Raiju signs with one)"
                continue
            project = env.get("VERTEX_PROJECT") or env.get("GOOGLE_CLOUD_PROJECT") or sa.get("project_id") or ""
            if not project:
                skipped[name] = "no VERTEX_PROJECT or GOOGLE_CLOUD_PROJECT"
                continue
            extra[VERTEX_CREDS_VAR] = text
            key["vertex_key_config"] = {"project_id": project, "region": env.get("VERTEX_REGION") or env.get("GOOGLE_CLOUD_REGION") or "us-central1",
                                        "auth_credentials": "env." + VERTEX_CREDS_VAR}
        else:
            key["value"] = "env." + need[0]
        model = model_for(env, name, chat)
        if not model:
            skipped[name] = f"no model (SMOKE_{name.upper()}_MODEL is off)"
            continue
        emb = model_for(env, name, embed, "EMBED_")
        providers[name] = {"keys": [key], "network_config": {"max_retries": 1, "default_request_timeout_in_seconds": 60}}
        plan[name] = {"model": f"{name}/{model}", "embed": f"{name}/{emb}" if emb else "", "native": native}
    cfg = {
        "client": {"enable_logging": True, "enforce_auth_on_inference": False},
        "logs_store": {"enabled": True, "dir": logs_dir, "content_logging": False},
        "large_payload_optimization": {"enabled": True, "request_threshold_bytes": LARGE_THRESHOLD, "response_threshold_bytes": 1048576,
                                       "prefetch_size_bytes": 4096, "max_payload_bytes": 16777216, "truncated_log_bytes": 1024},
        "providers": providers,
    }
    return cfg, extra, plan, skipped


# ---------------------------------------------------------------- running

class Report:
    def __init__(self, secrets):
        self.secrets = sorted((s for s in secrets if s and len(s) >= 4), key=len, reverse=True)
        self.counts = {"ok": 0, "FAIL": 0, "skip": 0}

    def mask(self, text):
        text = str(text)
        for s in self.secrets:
            text = text.replace(s, "***")
        return text

    def line(self, status, provider, check, detail=""):
        self.counts[status] += 1
        tail = f"  ({self.mask(detail)[:300]})" if detail else ""
        print(f"{status:4}  {provider:10}  {check}{tail}", flush=True)


def call(method, path, body=None, headers=None, timeout=90):
    data = None if body is None else (body if isinstance(body, (bytes, str)) else json.dumps(body))
    if isinstance(data, str):
        data = data.encode()
    req = urllib.request.Request(GW + path, data=data, method=method, headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf8", "replace")
    except Exception as e:  # a timeout or a dropped connection
        return 0, {}, f"{type(e).__name__}: {e}"


def jget(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def sse_events(text):
    out = []
    for line in text.split("\n"):
        if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]"):
            ev = jget(line[6:])
            if ev is not None:
                out.append(ev)
    return out


def log_row(rid, want_tokens=True):
    """The request's log row (logging is asynchronous, so it is polled for a few seconds)."""
    for _ in range(30):
        s, _, b = call("GET", "/api/logs/" + urllib.parse.quote(rid, safe=""), timeout=5)
        if s == 200:
            row = jget(b) or {}
            if not want_tokens or row.get("prompt_tokens"):
                return row
        time.sleep(0.2)
    return None


def check_row(rep, name, label, rid):
    row = log_row(rid)
    if row is None:
        rep.line("FAIL", name, f"log row ({label}): usage and cost", "no log row with tokens for " + rid)
    elif (row.get("prompt_tokens") or 0) > 0 and (row.get("completion_tokens") or 0) > 0 and (row.get("cost") or 0) > 0:
        rep.line("ok", name, f"log row ({label}): usage and cost", f"{row['prompt_tokens']}+{row['completion_tokens']} tokens, ${row['cost']:.8f}")
    else:
        why = "cost 0: the model is not in the price table" if (row.get("prompt_tokens") or 0) > 0 and not row.get("cost") else "missing usage"
        rep.line("FAIL", name, f"log row ({label}): usage and cost", f"{why}: prompt {row.get('prompt_tokens')}, completion {row.get('completion_tokens')}, cost {row.get('cost')}")


def rid():
    return "smoke-" + uuid.uuid4().hex[:16]


ASK = [{"role": "user", "content": "Reply with the single word: ok"}]
TOOLS = [{"type": "function", "function": {"name": "get_weather", "description": "Current weather for a city",
                                            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]


def run_provider(rep, name, p):
    model = p["model"]
    # chat, whole: also the credential check; a rejected key skips the rest
    r = rid()
    s, _, b = call("POST", "/v1/chat/completions", {"model": model, "max_tokens": 16, "messages": ASK}, {"x-request-id": r})
    d = jget(b) or {}
    msg = ((d.get("choices") or [{}])[0] or {}).get("message")
    if s == 200 and isinstance(msg, dict) and (d.get("usage") or {}).get("prompt_tokens"):
        rep.line("ok", name, f"chat ({model})", repr((msg.get("content") or "")[:40]))
        chat_rid = r
    else:
        rep.line("FAIL", name, f"chat ({model})", f"{s} {b[:300]}")
        chat_rid = ""
        if s in (401, 403) or s == 0:
            for c in ("chat stream", "tool call", "embeddings", "native route", "large request", "log rows"):
                rep.line("skip", name, c, "the chat request failed with " + (str(s) if s else "no answer"))
            return

    # chat, streamed, with usage
    r = rid()
    s, h, b = call("POST", "/v1/chat/completions", {"model": model, "max_tokens": 16, "stream": True, "stream_options": {"include_usage": True}, "messages": ASK}, {"x-request-id": r})
    evs = sse_events(b)
    text = "".join(((c.get("delta") or {}).get("content") or "") for e in evs for c in (e.get("choices") or []))
    usage = [e["usage"] for e in evs if e.get("usage")]
    if s == 200 and h.get("content-type", "").startswith("text/event-stream") and evs and usage and b.rstrip().endswith("data: [DONE]"):
        rep.line("ok", name, "chat stream", f"{len(evs)} chunks, {text[:30]!r}")
        stream_rid = r
    else:
        rep.line("FAIL", name, "chat stream", f"{s} {h.get('content-type')} usage={bool(usage)} {b[:300]}")
        stream_rid = ""

    # a tool call
    s, _, b = call("POST", "/v1/chat/completions", {"model": model, "max_tokens": 64, "tool_choice": "required", "tools": TOOLS,
                                                    "messages": [{"role": "user", "content": "What is the weather in Paris? Use the tool."}]})
    d = jget(b) or {}
    calls = (((d.get("choices") or [{}])[0] or {}).get("message") or {}).get("tool_calls") or []
    fn = (calls[0].get("function") or {}) if calls else {}
    args = jget(fn.get("arguments") or "")
    if s == 200 and fn.get("name") == "get_weather" and isinstance(args, dict):
        rep.line("ok", name, "tool call", f"get_weather({fn.get('arguments')})")
    else:
        rep.line("FAIL", name, "tool call", f"{s} {b[:300]}")

    # embeddings
    if p["embed"]:
        s, _, b = call("POST", "/v1/embeddings", {"model": p["embed"], "input": ["smoke test"]})
        d = jget(b) or {}
        vec = ((d.get("data") or [{}])[0] or {}).get("embedding")
        if s == 200 and isinstance(vec, list) and len(vec) > 0:
            rep.line("ok", name, f"embeddings ({p['embed']})", f"{len(vec)} dimensions")
        else:
            rep.line("FAIL", name, f"embeddings ({p['embed']})", f"{s} {b[:300]}")
    else:
        rep.line("skip", name, "embeddings", "none offered (set SMOKE_%s_EMBED_MODEL)" % name.upper())

    native_check(rep, name, p)

    # a request just over the large payload threshold: streamed to the provider (and converted as it streams)
    filler = ("The quick brown fox jumps over the lazy dog. " * (LARGE_THRESHOLD // 45 + 20))
    body = {"model": model, "max_tokens": 16, "messages": [{"role": "user", "content": filler + "\nReply with the single word: ok"}]}
    raw = json.dumps(body).encode()
    s, _, b = call("POST", "/v1/chat/completions", raw)
    d = jget(b) or {}
    if s == 200 and d.get("choices") and (d.get("usage") or {}).get("prompt_tokens", 0) > 1000:
        rep.line("ok", name, f"large request ({len(raw)} bytes, threshold {LARGE_THRESHOLD})", f"{d['usage']['prompt_tokens']} prompt tokens")
    else:
        rep.line("FAIL", name, f"large request ({len(raw)} bytes, threshold {LARGE_THRESHOLD})", f"{s} {b[:300]}")

    # the log rows of the two chat requests carry usage and cost
    if chat_rid:
        check_row(rep, name, "chat", chat_rid)
    if stream_rid:
        check_row(rep, name, "stream", stream_rid)


def native_check(rep, name, p):
    bare = p["model"].split("/", 1)[1]
    kind = p["native"]
    if kind == "responses":
        s, _, b = call("POST", "/v1/responses", {"model": p["model"], "max_output_tokens": 16, "input": "Reply with the single word: ok"})
        d = jget(b) or {}
        good = s == 200 and d.get("object") == "response" and d.get("output")
        label = "native route: Responses"
    elif kind == "messages":
        s, _, b = call("POST", "/anthropic/v1/messages", {"model": p["model"], "max_tokens": 16, "messages": ASK}, {"anthropic-version": "2023-06-01"})
        d = jget(b) or {}
        good = s == 200 and d.get("type") == "message" and isinstance(d.get("content"), list) and (d.get("usage") or {}).get("input_tokens")
        label = "native route: Anthropic Messages"
    elif kind == "genai":
        # a Gemini model by its bare name; a Vertex one as vertex/<model>
        path_model = bare if name == "gemini" else p["model"]
        s, _, b = call("POST", f"/genai/v1beta/models/{path_model}:generateContent",
                       {"contents": [{"role": "user", "parts": [{"text": "Reply with the single word: ok"}]}], "generationConfig": {"maxOutputTokens": 16}})
        d = jget(b) or {}
        good = s == 200 and d.get("candidates")
        label = "native route: GenAI generateContent"
    elif kind == "converse":
        s, _, b = call("POST", f"/bedrock/model/{urllib.parse.quote(bare, safe='')}/converse",
                       {"messages": [{"role": "user", "content": [{"text": "Reply with the single word: ok"}]}], "inferenceConfig": {"maxTokens": 16}})
        d = jget(b) or {}
        good = s == 200 and ((d.get("output") or {}).get("message") or {}).get("content") is not None and (d.get("usage") or {}).get("inputTokens")
        label = "native route: Bedrock Converse"
    elif kind == "cohere":
        s, _, b = call("POST", "/cohere/v2/chat", {"model": p["model"], "max_tokens": 16, "messages": ASK})
        d = jget(b) or {}
        good = s == 200 and isinstance((d.get("message") or {}).get("content"), list)
        label = "native route: Cohere v2 chat"
    else:
        rep.line("skip", name, "native route", "OpenAI-compatible: the chat checks are its native route")
        return
    rep.line("ok" if good else "FAIL", name, label, "" if good else f"{s} {b[:300]}")


def build():
    os.makedirs(BUILD, exist_ok=True)
    env = {**os.environ, "TOV_CFLAGS": os.environ.get("TOV_CFLAGS", "-DTV_PLAIN_ALLOC")}
    subprocess.run([os.environ.get("TOV", "tov"), "build", os.path.join(ROOT, "src/main.tov"), "-o", os.path.join(BUILD, "raiju")], check=True, capture_output=True, env=env)


def wait_up(proc):
    for _ in range(200):
        if proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(GW + "/health", timeout=1)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.05)
    return False


def main():
    env = dict(os.environ)
    rep = Report([env.get(v, "") for v in SECRET_VARS])
    logs_dir = tempfile.mkdtemp(prefix="raiju-smoke-logs-")
    cfg, extra, plan, skipped = build_config(env, logs_dir)
    rep.secrets = sorted(set(rep.secrets + [v for v in extra.values() if v]), key=len, reverse=True)
    for name, why in skipped.items():
        rep.line("skip", name, "all checks", why)
    if not plan:
        print(f"smoke: no provider credentials found; {rep.counts['skip']} skipped, nothing failed")
        shutil.rmtree(logs_dir, ignore_errors=True)
        return 0
    if not os.environ.get("SMOKE_NO_BUILD"):
        build()
    fd, cfg_path = tempfile.mkstemp(prefix="raiju-smoke-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f)
    log_path = os.path.join(BUILD, "smoke.log")
    gw = subprocess.Popen(cwd=ROOT, args=[os.path.join(BUILD, "raiju"), "-port", str(PORT), "-host", "127.0.0.1", "-config", cfg_path],
                          env={**env, **extra}, stderr=open(log_path, "w"), stdout=subprocess.DEVNULL)
    try:
        if not wait_up(gw):
            rep.line("FAIL", "gateway", "start", f"the gateway did not come up on {PORT} (see build/smoke.log)")
        else:
            for name, p in plan.items():
                try:
                    run_provider(rep, name, p)
                except Exception as e:  # one provider's surprise must not hide the others' results
                    rep.line("FAIL", name, "matrix", f"{type(e).__name__}: {e}")
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gw.kill()
        os.unlink(cfg_path)
        shutil.rmtree(logs_dir, ignore_errors=True)
    c = rep.counts
    print(f"smoke: {c['ok']} ok, {c['FAIL']} failed, {c['skip']} skipped")
    return 1 if c["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
