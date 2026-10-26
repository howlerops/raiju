#!/usr/bin/env python3
"""Smoke checks against a deployed gateway: liveness, readiness, TLS and the HTTP redirect, the management lock, the
virtual key, a chat whole and streamed on RAIJU_MODEL, /metrics, and (with --providers) the real-provider matrix of
tests/smoke.py run through BASE_URL instead of a local gateway.

Usage: tests/staging/smoke_check.py [--base-url URL] [--providers openai/gpt-4.1-nano,anthropic/claude-haiku-4-5]
Settings come from the environment (tests/staging/kit.py): RAIJU_BASE_URL, RAIJU_ADMIN_TOKEN, RAIJU_VKS,
RAIJU_MODEL, RAIJU_METRICS_TOKEN, RAIJU_SETUP_TOKEN (checked to open nothing once an admin exists).
Each check prints PASS, FAIL or SKIP with its numbers; the exit status is 1 when one failed.
"""
import argparse
import datetime
import os
import socket
import ssl
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402


def sse_events(text):
    out = []
    for line in text.split("\n"):
        if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]"):
            ev = kit.jload(line[6:])
            if ev is not None:
                out.append(ev)
    return out


def cert_days_left(not_after, now=None):
    """Days until a certificate's notAfter ("Jun  1 12:00:00 2027 GMT")."""
    t = datetime.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (t - now).total_seconds() / 86400.0


def check_tls(rep, s):
    u = urllib.parse.urlsplit(s.base_url)
    if u.scheme != "https":
        rep.add("smoke.tls", None, {}, "BASE_URL is plain http: TLS is not checked (the ECS module serves HTTPS unless allow_plain_http)")
        return
    try:
        raw = socket.create_connection((u.hostname, u.port or 443), timeout=10)
        with kit.ssl_context(s.ca_file).wrap_socket(raw, server_hostname=u.hostname) as t:
            cert = t.getpeercert()
            days = cert_days_left(cert["notAfter"])
            rep.add("smoke.tls", days > 7, {"days_left": round(days, 1), "version": t.version()}, "certificate verified for " + u.hostname)
    except (OSError, ssl.SSLError, KeyError, ValueError) as e:
        rep.add("smoke.tls", False, {}, f"{type(e).__name__}: {e}")
        return
    # the ALB answers plain HTTP with a redirect to HTTPS
    plain = "http://" + u.hostname + "/health"
    st, h, _ = kit.request("GET", plain, timeout=10)
    loc = h.get("location", "")
    rep.add("smoke.http_redirect", st in (301, 302, 307, 308) and loc.startswith("https://"), {"status": st}, loc)


def check_management(rep, s, gw):
    st, _, _ = kit.request("GET", gw.base + "/api/governance/virtual-keys", timeout=15, ca_file=s.ca_file)
    rep.add("smoke.api_locked_without_credentials", st in (401, 403), {"status": st})
    setup = os.environ.get("RAIJU_SETUP_TOKEN", "")
    if setup and (s.admin_token or s.admin_user):
        st, _, _ = kit.request("GET", gw.base + "/api/governance/virtual-keys", headers={"x-bifrost-setup-token": setup}, timeout=15, ca_file=s.ca_file)
        rep.add("smoke.setup_token_closed_after_first_admin", st in (401, 403), {"status": st})
    if not (s.admin_token or s.admin_user):
        rep.add("smoke.admin_api", None, {}, "no RAIJU_ADMIN_TOKEN")
        return
    t0 = time.time()
    st, _, b = gw.api("GET", "/api/governance/virtual-keys")
    rows = (kit.jload(b) or {}).get("virtual_keys", []) if st == 200 else []
    rep.add("smoke.admin_api", st == 200, {"status": st, "virtual_keys": len(rows), "ms": round((time.time() - t0) * 1000)})


def check_inference(rep, s, gw):
    if not s.vks:
        rep.add("smoke.inference", None, {}, "no RAIJU_VKS")
        return
    st, _, _ = gw.infer("/v1/chat/completions", {"model": s.model, "max_tokens": 4, "messages": [{"role": "user", "content": "hi"}]}, vk="sk-bf-" + "not-a-real-key")
    rep.add("smoke.unknown_virtual_key_refused", st in (401, 403), {"status": st})
    t0 = time.time()
    st, _, b = gw.get("/v1/models", {"x-bf-vk": s.vks[0]})
    n = len((kit.jload(b) or {}).get("data", [])) if st == 200 else 0
    rep.add("smoke.models", st == 200 and n > 0, {"status": st, "models": n, "ms": round((time.time() - t0) * 1000)})
    ask = [{"role": "user", "content": "Reply with the single word: ok"}]
    t0 = time.time()
    st, _, b = gw.infer("/v1/chat/completions", {"model": s.model, "max_tokens": 16, "messages": ask})
    d = kit.jload(b) or {}
    usage = d.get("usage") or {}
    rep.add("smoke.chat", st == 200 and bool(d.get("choices")) and usage.get("prompt_tokens", 0) > 0,
            {"status": st, "ms": round((time.time() - t0) * 1000), "prompt_tokens": usage.get("prompt_tokens", 0)}, s.model if st == 200 else b[:200].decode("utf8", "replace"))
    t0 = time.time()
    st, h, b = gw.infer("/v1/chat/completions", {"model": s.model, "max_tokens": 16, "stream": True, "stream_options": {"include_usage": True}, "messages": ask})
    text = b.decode("utf8", "replace")
    evs = sse_events(text)
    ok = st == 200 and h.get("content-type", "").startswith("text/event-stream") and bool(evs) and text.rstrip().endswith("data: [DONE]")
    rep.add("smoke.chat_stream", ok, {"status": st, "chunks": len(evs), "ms": round((time.time() - t0) * 1000)})


def check_metrics(rep, s, gw):
    h = {"authorization": "Bearer " + s.metrics_token} if s.metrics_token else {}
    st, _, b = gw.get("/metrics", h)
    if st == 404:
        rep.add("smoke.metrics", None, {"status": st}, "served on the cluster listener (cluster.serve_metrics)")
        return
    if st == 401 and not s.metrics_token:
        rep.add("smoke.metrics", None, {"status": st}, "server.metrics_token is set: give RAIJU_METRICS_TOKEN")
        return
    reqs = kit.metric_sum(b.decode("utf8", "replace"), "bifrost_upstream_requests_total") if st == 200 else None
    rep.add("smoke.metrics", st == 200, {"status": st, "bytes": len(b), "upstream_requests": reqs if reqs is not None else 0})


def run_matrix(rep, s, models):
    """tests/smoke.py's per-provider matrix, sent to BASE_URL with the virtual key and the admin token."""
    sys.path.insert(0, os.path.dirname(HERE))
    import smoke  # tests/smoke.py
    smoke.GW = s.base_url
    gw = kit.Gateway(s.base_url, s)
    extra = {"x-bf-vk": s.vks[0]} if s.vks else {}
    extra.update(gw.admin_headers())
    orig = smoke.call

    def call(method, path, body=None, headers=None, timeout=90):
        h = dict(extra)
        h.update(headers or {})
        return orig(method, path, body, h, timeout)

    smoke.call = call
    table = {p[0]: p for p in smoke.PROVIDERS}
    srep = smoke.Report(s.secrets())
    for full in models:
        name, _, model = full.partition("/")
        row = table.get(name)
        embed = os.environ.get(f"SMOKE_{name.upper()}_EMBED_MODEL", row[3] if row else "")
        p = {"model": full, "embed": f"{name}/{embed}" if embed and embed.lower() not in smoke.OFF else "", "native": row[4] if row else ""}
        before = dict(srep.counts)
        try:
            smoke.run_provider(srep, name, p)
        except Exception as e:  # one provider's surprise must not hide the others
            srep.line("FAIL", name, "matrix", f"{type(e).__name__}: {e}")
        got = {k: srep.counts[k] - before[k] for k in srep.counts}
        rep.add(f"smoke.matrix.{name}", got["FAIL"] == 0 and got["ok"] > 0, {"ok": got["ok"], "failed": got["FAIL"], "skipped": got["skip"]}, full)


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--providers", default=os.environ.get("RAIJU_SMOKE_MODELS", ""), help="provider/model list for tests/smoke.py's matrix (RAIJU_SMOKE_MODELS)")
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    rep = kit.Report(s)
    if not s.base_url:
        rep.add("smoke", False, {}, "no base URL (RAIJU_BASE_URL or --base-url)")
        return rep.exit_code()
    gw = kit.Gateway(s.base_url, s)
    st, _, b = gw.get("/health")
    rep.add("smoke.health", st == 200 and (kit.jload(b) or {}).get("status") == "ok", {"status": st})
    st, _, b = gw.get("/ready")
    rep.add("smoke.ready", st == 200, {"status": st}, "" if st == 200 else b[:200].decode("utf8", "replace"))
    check_tls(rep, s)
    check_management(rep, s, gw)
    check_inference(rep, s, gw)
    check_metrics(rep, s, gw)
    models = kit.split_list(a.providers)
    if models:
        run_matrix(rep, s, models)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
