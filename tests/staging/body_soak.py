#!/usr/bin/env python3
"""Memory soak against a deployed gateway (re-audit 6 P0-A: "a soak test asserting flat RSS over many big bodies"):
mixed traffic for --duration (short chats, streams, long-context chats, and request bodies from 64 KB to 50 MB)
while the gateway's RSS is sampled. Passes when the RSS stays flat over the second half, never comes near the
memory limit, and no restart (an OOM kill) shows up.

Usage: tests/staging/body_soak.py --duration 24h [--rate 2] [--concurrency 16]
         [--kinds chat:30,stream:25,long:10,body:35] [--mix default|l210|64K:40,1M:20,...]
         [--rss-cmd "CMD" | --rss-metric NAME [--metrics-url URL]] [--limit-mb 512] [--max-growth-mb 32]
         [--out DIR]

RSS: --rss-cmd runs a shell command each --sample-every seconds and reads sizes from its output, one per line
(several lines: one per task or pod, the largest is charted): "204800 kB", "200Mi", "209715200" all work, so
`kubectl top pod -l app=raiju --no-headers | awk '{print $3}'`, a CloudWatch query, or `grep VmRSS /proc/PID/status`
on a host fit. --rss-metric reads a gauge from Prometheus text (process_resident_memory_bytes from a sidecar
exporter, container_memory_working_set_bytes from cAdvisor) at --metrics-url (default BASE_URL/metrics). Without
either the soak still runs and reports the traffic, but cannot pass (exit 2: no memory data).

Bodies: kind "body" posts chat bodies of the --mix sizes to --body-model (the staging counterpart of
tests/soak/bodies.py, which runs the same leak check against a local worker in CI; --mix l210 replays its loop,
--mix default spans 64 KB to 50 MB). The default model, staging-discard/none, names
no provider, so the gateway reads the whole body (the budget, the rate rule, the leak re-audit 6 found) and answers
400 without calling anyone: memory is exercised at no provider cost. Give a real model to send them upstream
(large_payload_optimization's streamed path); bodies past the budget answer 503 and are counted as refused.
Kinds chat, stream and long use RAIJU_MODEL with max_tokens 16 (long: --long-kb of prompt, about 250 tokens a KB).

Output (--out, default staging-soak-<run>): samples.csv, rss.svg (the RSS over time against the limit) and
summary.json. One PASS/FAIL line ends the run.
"""
import argparse
import csv
import json
import os
import random
import subprocess
import sys
import threading
import time
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit  # noqa: E402

DISCARD_MODEL = "staging-discard/none"
# named mixes: "default" spans 64 KB to 50 MB; "l210" is tests/soak/bodies.py's loop (1 MB, 4 MB and 200 KB bodies),
# the pattern that grew a worker from 20 to 836 MB in 100 s before L210
MIXES = {"default": "64K:40,256K:25,1M:20,8M:10,24M:4,50M:1", "l210": "200K:1,1M:1,4M:1"}


# ---------------------------------------------------------------- pure parts

def parse_rss_output(text):
    """The largest size in a command's output (one size per line), in MB; None when no line holds one."""
    best = None
    for line in str(text).splitlines():
        n = kit.parse_size(line)
        if n is not None and (best is None or n > best):
            best = n
    return None if best is None else best / 1048576.0


def restarts(series, drop=0.5, floor_mb=8.0):
    """Points where the RSS fell below `drop` of the running peak since the last restart (a process that was killed
    and started again begins small): their indexes. Falls under floor_mb of change are ignored."""
    out, peak = [], None
    for i, v in enumerate(series):
        if v is None:
            continue
        if peak is not None and v < peak * drop and peak - v > floor_mb:
            out.append(i)
            peak = v
            continue
        peak = v if peak is None else max(peak, v)
    return out


def soak_verdict(samples, limit_mb, max_growth_mb, warmup=0.1, headroom=0.9, max_error_ratio=0.01, requests=0, errors=0):
    """samples: [(t_seconds, rss_mb)]. Growth is the least-squares slope over the second half (after warmup) times
    that half's length, so noise does not count but a steady leak does. (ok, numbers, reasons)."""
    pts = [(t, v) for t, v in samples if v is not None]
    reasons = []
    if len(pts) < 4:
        return False, {"samples": len(pts)}, ["fewer than 4 RSS samples"]
    t0, t1 = pts[0][0], pts[-1][0]
    start = t0 + (t1 - t0) * warmup
    body = [p for p in pts if p[0] >= start]
    mid = start + (t1 - start) / 2
    second = [p for p in body if p[0] >= mid] or body
    growth = kit.slope(second) * (second[-1][0] - second[0][0]) if len(second) > 1 else 0.0
    peak = max(v for _, v in pts)
    rs = restarts([v for _, v in pts])
    ratio = errors / requests if requests else 0.0
    nums = {"samples": len(pts), "rss_start_mb": round(body[0][1], 1), "rss_end_mb": round(pts[-1][1], 1), "peak_mb": round(peak, 1),
            "growth_2nd_half_mb": round(growth, 2), "limit_mb": limit_mb, "restarts": len(rs), "requests": requests,
            "error_ratio": round(ratio, 4)}
    if growth > max_growth_mb:
        reasons.append(f"RSS grew {growth:.1f} MB over the second half (limit {max_growth_mb})")
    if peak > limit_mb * headroom:
        reasons.append(f"peak {peak:.0f} MB is above {headroom:.0%} of the {limit_mb} MB limit")
    if rs:
        reasons.append(f"{len(rs)} restart(s): the RSS dropped as a new process would (an OOM kill?)")
    if ratio > max_error_ratio:
        reasons.append(f"error ratio {ratio:.2%} above {max_error_ratio:.2%}")
    return not reasons, nums, reasons


def svg_chart(samples, limit_mb, title="RSS", width=900, height=320):
    """An SVG line chart of [(t_seconds, rss_mb)] with the limit as a dashed line; standalone, no scripts."""
    pts = [(t, v) for t, v in samples if v is not None]
    pad_l, pad_r, pad_t, pad_b = 56, 16, 28, 36
    w, h = width - pad_l - pad_r, height - pad_t - pad_b
    tmax = max([p[0] for p in pts] + [1.0])
    tmin = min([p[0] for p in pts] + [0.0])
    ymax = max([p[1] for p in pts] + [limit_mb or 0, 1.0]) * 1.08

    def x(t):
        return pad_l + (t - tmin) / ((tmax - tmin) or 1.0) * w

    def y(v):
        return pad_t + h - v / ymax * h

    hours = (tmax - tmin) >= 7200
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="sans-serif" font-size="11">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           f'<text x="{pad_l}" y="16" font-size="13" fill="#222">{escape(title)}</text>']
    for i in range(5):
        v = ymax * i / 4
        out.append(f'<line x1="{pad_l}" x2="{pad_l + w}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e4e4e4"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y(v) + 4:.1f}" text-anchor="end" fill="#555">{v:.0f} MB</text>')
    for i in range(6):
        t = tmin + (tmax - tmin) * i / 5
        label = f"{(t - tmin) / 3600:.1f} h" if hours else f"{(t - tmin) / 60:.0f} min"
        out.append(f'<text x="{x(t):.1f}" y="{pad_t + h + 18}" text-anchor="middle" fill="#555">{label}</text>')
    if limit_mb:
        out.append(f'<line x1="{pad_l}" x2="{pad_l + w}" y1="{y(limit_mb):.1f}" y2="{y(limit_mb):.1f}" stroke="#c0392b" stroke-dasharray="6 4"/>')
        out.append(f'<text x="{pad_l + w}" y="{y(limit_mb) - 4:.1f}" text-anchor="end" fill="#c0392b">limit {limit_mb} MB</text>')
    if pts:
        path = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in pts)
        out.append(f'<polyline fill="none" stroke="#2c6fbb" stroke-width="1.5" points="{path}"/>')
    out.append("</svg>")
    return "\n".join(out)


def pick(weights, rng):
    total = sum(weights.values())
    r = rng.random() * total
    for k, w in weights.items():
        r -= w
        if r <= 0:
            return k
    return list(weights)[-1]


# ---------------------------------------------------------------- traffic

class Counters:
    def __init__(self):
        self.lock = threading.Lock()
        self.by = {}
        self.requests = self.errors = self.refused = 0
        self.bytes_sent = 0
        self.last_error = ""

    def add(self, kind, status, body, sent):
        with self.lock:
            self.requests += 1
            self.bytes_sent += sent
            key = f"{kind}:{status}"
            self.by[key] = self.by.get(key, 0) + 1
            if kit.is_busy(status, body) or status == 413:
                self.refused += 1
            elif status == 0 or status >= 500 or (status == 408 and kind != "body"):
                self.errors += 1
                self.last_error = f"{kind} {status} {body[:160]!r}"


def request_for(kind, a, s, rng, bodies):
    if kind == "body":
        size = pick(bodies["weights"], rng)
        if size not in bodies["cache"]:
            bodies["cache"][size] = kit.chat_body(size, a.body_model)
        return {"path": "/v1/chat/completions", "body": bodies["cache"][size]}
    if kind == "long":
        filler = ("The quick brown fox jumps over the lazy dog. " * (a.long_kb * 1024 // 45 + 1))[: a.long_kb * 1024]
        return {"path": "/v1/chat/completions", "body": json.dumps({"model": s.model, "max_tokens": 16, "messages": [{"role": "user", "content": filler + "\nReply with: ok"}]}).encode()}
    msg = {"model": s.model, "max_tokens": 16, "messages": [{"role": "user", "content": "Reply with the single word: ok"}]}
    if kind == "stream":
        msg["stream"] = True
    return {"path": "/v1/chat/completions", "body": json.dumps(msg).encode()}


def sample_rss(a, s):
    try:
        if a.rss_cmd:
            out = subprocess.run(a.rss_cmd, shell=True, capture_output=True, text=True, timeout=60)
            return parse_rss_output(out.stdout) if out.returncode == 0 else None
        if a.rss_metric:
            url = a.metrics_url or (s.base_url + "/metrics")
            h = {"authorization": "Bearer " + s.metrics_token} if s.metrics_token else {}
            st, _, b = kit.request("GET", url, headers=h, timeout=20, ca_file=s.ca_file)
            if st != 200:
                return None
            v = kit.metric_sum(b.decode("utf8", "replace"), a.rss_metric)
            return None if v is None else v / 1048576.0
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def main(argv=None):
    ap = kit.add_common_args(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("--duration", default="30m")
    ap.add_argument("--rate", type=float, default=2.0, help="requests started per second")
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--kinds", default="chat:30,stream:25,long:10,body:35")
    ap.add_argument("--mix", default="default", help="size:weight list, or a named mix (default, l210)")
    ap.add_argument("--body-model", default=DISCARD_MODEL)
    ap.add_argument("--long-kb", type=int, default=64)
    ap.add_argument("--rss-cmd", default=os.environ.get("RAIJU_RSS_CMD", ""))
    ap.add_argument("--rss-metric", default=os.environ.get("RAIJU_RSS_METRIC", ""))
    ap.add_argument("--metrics-url", default="")
    ap.add_argument("--sample-every", type=float, default=30.0)
    ap.add_argument("--limit-mb", type=float, default=512.0, help="the memory limit (the chart's and the ECS module's 512Mi)")
    ap.add_argument("--max-growth-mb", type=float, default=32.0)
    ap.add_argument("--max-error-ratio", type=float, default=0.01)
    ap.add_argument("--out", default="")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    s = kit.settings_from(a)
    rep = kit.Report(s)
    if not s.base_url or not s.vks:
        rep.add("soak", False, {}, "needs RAIJU_BASE_URL and RAIJU_VKS")
        return rep.exit_code()
    duration = kit.parse_duration(a.duration)
    kinds = kit.parse_weights(a.kinds)
    bodies = {"weights": dict(kit.parse_mix(MIXES.get(a.mix, a.mix))), "cache": {}}
    out = a.out or os.path.join(s.results_dir or ".", "staging-soak-" + kit.run_id())
    os.makedirs(out, exist_ok=True)
    rng = random.Random(a.seed or None)
    gw = kit.Gateway(s.base_url, s)
    c = Counters()
    stop = time.time() + duration
    slots = threading.Semaphore(a.concurrency)
    samples = []
    t_start = time.time()
    rep.note(f"soak: {a.duration} at {a.rate}/s against {s.base_url}; kinds {kinds}; mix {a.mix}; output {out}")

    def one(kind, req):
        try:
            st, _, b = gw.infer(req["path"], req["body"], timeout=300)
            c.add(kind, st, b, len(req["body"]))
        finally:
            slots.release()

    def sampler():
        f = open(os.path.join(out, "samples.csv"), "w", newline="")
        w = csv.writer(f)
        w.writerow(["t_s", "rss_mb", "requests", "errors", "refused"])
        while True:
            v = sample_rss(a, s)
            t = time.time() - t_start
            samples.append((t, v))
            with c.lock:
                w.writerow([round(t, 1), "" if v is None else round(v, 2), c.requests, c.errors, c.refused])
            f.flush()
            if time.time() >= stop:
                break
            time.sleep(min(a.sample_every, max(0.0, stop - time.time())))
        f.close()

    smp = threading.Thread(target=sampler, daemon=True)
    smp.start()
    next_at = time.time()
    last_note = time.time()
    while time.time() < stop:
        now = time.time()
        if now < next_at:
            time.sleep(min(next_at - now, 0.5))
            continue
        next_at += 1.0 / a.rate
        if not slots.acquire(timeout=5):
            continue  # all slots busy: the gateway is slower than the rate (counted in the summary as fewer requests)
        kind = pick(kinds, rng)
        threading.Thread(target=one, args=(kind, request_for(kind, a, s, rng, bodies)), daemon=True).start()
        if now - last_note > 600:
            last_note = now
            rss = next((v for _, v in reversed(samples) if v is not None), None)
            rep.note(f"  t={int(now - t_start)}s requests={c.requests} errors={c.errors} refused={c.refused} rss={'n/a' if rss is None else f'{rss:.0f} MB'}")
    for _ in range(a.concurrency):
        slots.acquire(timeout=320)
    smp.join(120)

    with open(os.path.join(out, "rss.svg"), "w") as f:
        f.write(svg_chart(samples, a.limit_mb, f"Raiju RSS, {a.duration} soak against {s.base_url}"))
    have_rss = any(v is not None for _, v in samples)
    summary = {"duration_s": duration, "requests": c.requests, "errors": c.errors, "refused": c.refused, "statuses": c.by,
               "bytes_sent": c.bytes_sent, "last_error": c.last_error[:300]}
    if have_rss:
        ok, nums, reasons = soak_verdict(samples, a.limit_mb, a.max_growth_mb, max_error_ratio=a.max_error_ratio, requests=c.requests, errors=c.errors)
        summary.update(nums)
        summary["reasons"] = reasons
        rep.add("soak", ok, nums, "; ".join(reasons) or f"flat; statuses {c.by}")
    else:
        rep.add("soak", False, {"requests": c.requests, "errors": c.errors}, "no RSS data (--rss-cmd or --rss-metric)")
    with open(os.path.join(out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    if not have_rss:
        return 2
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
