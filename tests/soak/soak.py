#!/usr/bin/env python3
"""Memory soak: drives one gateway worker with streamed and plain chat traffic and fails when its RSS grows.

Usage: tests/soak/soak.py [--seconds N] [--rate R] [--slow N] [--max-growth-mb M] [--max-stream-kb K]
       [--server bun|http1] [--no-build] [--raiju PATH]

It builds build/raiju and build/soak_mock (tests/soak/mock.tov, an upstream that keeps nothing in memory), starts
them on SOAK_MOCK_PORT and SOAK_PORT (18320 and 18321 by default; run it under the e2e lock, as
`flock /tmp/raiju-e2e.lock python3 tests/soak/soak.py`), and runs three phases:

1. open streams: --slow concurrent slow streams (20 chunks 100 ms apart) on a fresh gateway; the RSS they add,
   divided by their number, is the memory one open stream costs (fails above --max-stream-kb).
2. warm-up (a quarter of --seconds, at least 5 s): the full mix, so allocator pools, caches and the log ring fill.
3. soak (--seconds): fast streams and plain calls at --rate requests a second (half each) plus the slow streams,
   with the request log and the log store on. The RSS is sampled every 5 s; its growth over the second half of
   the soak (a leak grows steadily, a heap that has settled does not) fails above --max-growth-mb.

Before the stream leak was fixed (L182), one worker grew about 0.8 MB a second at the default rate and an open
stream cost about 330 KB; after it, the second half grows under 2 MB and a stream costs about 165 KB (about
230 KB on the http1 server).

The load comes from this script (asyncio, keep-alive HTTP/1.1), so it needs nothing but Python 3. A summary line
`soak: ok ...` or `soak: FAIL ...` ends the output; the gateway's stderr is in build/soak.gateway.log.
"""
import argparse, asyncio, json, os, shutil, signal, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(ROOT, "build")
MOCK_PORT = int(os.environ.get("SOAK_MOCK_PORT", "18320"))
PORT = int(os.environ.get("SOAK_PORT", "18321"))

FAST = json.dumps({"model": "openai/gpt-4o-mini", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode()
PLAIN = json.dumps({"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}).encode()
SLOW = json.dumps({"model": "openai/slow-stream", "stream": True, "messages": [{"role": "user", "content": "hi"}]}).encode()


def build():
    os.makedirs(BUILD, exist_ok=True)
    env = {**os.environ, "TOV_CFLAGS": os.environ.get("TOV_CFLAGS", "-DTV_PLAIN_ALLOC")}
    tov = os.environ.get("TOV", "tov")
    for src, out in [("src/main.tov", "raiju"), ("tests/soak/mock.tov", "soak_mock")]:
        subprocess.run([tov, "build", os.path.join(ROOT, src), "-o", os.path.join(BUILD, out)], check=True, capture_output=True, env=env)


def rss_kb(pid):
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


class Stats:
    def __init__(self):
        self.ok = 0
        self.bad = 0
        self.errors = 0
        self.last_error = ""


async def read_response(reader):
    """Reads one HTTP/1.1 response (content-length or chunked); returns (status, body bytes, keep_alive)."""
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    hs = {}
    for l in lines[1:]:
        if ":" in l:
            k, v = l.split(":", 1)
            hs[k.strip().lower()] = v.strip()
    body = b""
    if hs.get("transfer-encoding", "").lower() == "chunked":
        parts = []
        while True:
            size_line = await reader.readuntil(b"\r\n")
            n = int(size_line.split(b";")[0].strip(), 16)
            if n == 0:
                await reader.readuntil(b"\r\n")
                break
            parts.append(await reader.readexactly(n))
            await reader.readexactly(2)
        body = b"".join(parts)
    elif "content-length" in hs:
        body = await reader.readexactly(int(hs["content-length"]))
    else:
        body = await reader.read()
        return status, body, False
    return status, body, hs.get("connection", "").lower() != "close"


class Client:
    """One keep-alive connection, reopened when the server closes it."""

    def __init__(self, stats):
        self.stats = stats
        self.reader = None
        self.writer = None

    async def request(self, body):
        try:
            if self.writer is None:
                self.reader, self.writer = await asyncio.open_connection("127.0.0.1", PORT)
            self.writer.write(b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                              b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            status, data, keep = await asyncio.wait_for(read_response(self.reader), 30)
            if status == 200 and (body is PLAIN or b"[DONE]" in data):
                self.stats.ok += 1
            else:
                self.stats.bad += 1
                self.stats.last_error = f"status {status}: {data[:200]!r}"
            if not keep:
                self.close()
        except Exception as e:
            self.stats.errors += 1
            self.stats.last_error = repr(e)
            self.close()

    def close(self):
        if self.writer is not None:
            self.writer.close()
        self.reader = None
        self.writer = None


async def paced(stats, body, rate, until):
    """Open-loop load at `rate` requests a second, over as many connections as the requests in flight need."""
    if rate <= 0:
        return
    idle = []
    tasks = set()
    start = time.monotonic()
    sent = 0

    async def one():
        c = idle.pop() if idle else Client(stats)
        await c.request(body)
        idle.append(c)

    while time.monotonic() < until:
        due = int((time.monotonic() - start) * rate)
        while sent < due:
            t = asyncio.ensure_future(one())
            tasks.add(t)
            t.add_done_callback(tasks.discard)
            sent += 1
        await asyncio.sleep(0.002)
    if tasks:
        await asyncio.wait(tasks, timeout=30)
    for c in idle:
        c.close()


async def looped(stats, body, until):
    c = Client(stats)
    while time.monotonic() < until:
        await c.request(body)
    c.close()


async def load(rate, slow, seconds, stats):
    until = time.monotonic() + seconds
    jobs = [paced(stats, FAST, rate / 2.0, until), paced(stats, PLAIN, rate / 2.0, until)]
    jobs += [looped(stats, SLOW, until) for _ in range(slow)]
    await asyncio.gather(*jobs)


async def open_streams(pid, n):
    """Opens n slow streams, reads their first chunk, and samples the RSS while all are open."""
    conns = []
    for _ in range(n):
        r, w = await asyncio.open_connection("127.0.0.1", PORT)
        w.write(b"POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(SLOW)).encode() + b"\r\n\r\n" + SLOW)
        conns.append((r, w))
    # every stream has sent its head and first chunk (the slow streams last 2 s)
    for r, _ in conns:
        await asyncio.wait_for(r.readuntil(b"data: "), 30)
    peak = rss_kb(pid)

    async def finish(r, w):
        try:
            await asyncio.wait_for(r.readuntil(b"0\r\n\r\n"), 30)
        except Exception:
            pass
        w.close()

    await asyncio.gather(*[finish(r, w) for r, w in conns])
    return peak


def wait_up(port):
    import socket
    for _ in range(200):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.05)
    raise SystemExit(f"soak: nothing listening on {port}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=float(os.environ.get("SOAK_SECONDS", "60")))
    ap.add_argument("--rate", type=float, default=float(os.environ.get("SOAK_RATE", "600")))
    ap.add_argument("--slow", type=int, default=int(os.environ.get("SOAK_SLOW", "100")))
    ap.add_argument("--max-growth-mb", type=float, default=float(os.environ.get("SOAK_MAX_GROWTH_MB", "8")))
    ap.add_argument("--max-stream-kb", type=float, default=float(os.environ.get("SOAK_MAX_STREAM_KB", "240")))
    ap.add_argument("--server", default=os.environ.get("RAIJU_SERVER", "bun"))
    ap.add_argument("--no-build", action="store_true")
    # another gateway binary (an older build, to compare); implies --no-build for the gateway
    ap.add_argument("--raiju", default="")
    a = ap.parse_args()
    if not a.no_build:
        build()
    tmp = tempfile.mkdtemp(prefix="raiju-soak-")
    cfg = {
        "client": {"enable_logging": True},
        # (a small ring, so the warm-up fills it: its entries are not growth)
        "logs_store": {"enabled": True, "dir": os.path.join(tmp, "logs"), "max_memory_entries": 2000},
        "providers": {"openai": {"keys": [{"name": "k1", "value": "sk-soak-" + "0123456789", "models": [], "weight": 1.0}],
                                 "network_config": {"base_url": f"http://127.0.0.1:{MOCK_PORT}"}}},
    }
    path = os.path.join(tmp, "config.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    mock = subprocess.Popen([os.path.join(BUILD, "soak_mock")], env={**os.environ, "MOCK_PORT": str(MOCK_PORT), "MOCK_WORKERS": "2"},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = open(os.path.join(BUILD, "soak.gateway.log"), "w")
    gw = subprocess.Popen([a.raiju or os.path.join(BUILD, "raiju"), "-port", str(PORT), "-host", "127.0.0.1", "-config", path, "-server", a.server],
                          stdout=subprocess.DEVNULL, stderr=log)
    failures = []
    try:
        wait_up(MOCK_PORT)
        wait_up(PORT)
        time.sleep(0.5)
        start_kb = rss_kb(gw.pid)
        # 1. what an open stream costs, on a fresh gateway (the allocator rarely gives memory back, so a second round
        # would reuse the first one's pages and read as free)
        peak_kb = asyncio.run(open_streams(gw.pid, a.slow))
        per_stream = max(0, peak_kb - start_kb) / max(1, a.slow)
        print(f"soak: start {start_kb / 1024:.1f} MB; {a.slow} open streams add {(peak_kb - start_kb) / 1024:.1f} MB, {per_stream:.0f} KB each")
        if per_stream > a.max_stream_kb:
            failures.append(f"an open stream costs {per_stream:.0f} KB (limit {a.max_stream_kb:.0f} KB)")
        # 2. warm-up
        warm = max(5.0, a.seconds / 4)
        ws = Stats()
        asyncio.run(load(a.rate, a.slow, warm, ws))
        time.sleep(1)
        before_kb = rss_kb(gw.pid)
        print(f"soak: after {warm:.0f} s warm-up {before_kb / 1024:.1f} MB ({ws.ok} ok, {ws.bad} bad, {ws.errors} errors)")
        # 3. soak, sampling the RSS every 5 s
        st = Stats()
        samples = []
        stop = time.monotonic() + a.seconds

        async def sampler():
            while time.monotonic() < stop:
                await asyncio.sleep(5)
                samples.append(rss_kb(gw.pid))
                print(f"soak:   t={a.seconds - max(0, stop - time.monotonic()):4.0f}s rss {samples[-1] / 1024:.1f} MB", flush=True)

        async def soak():
            await asyncio.gather(load(a.rate, a.slow, a.seconds, st), sampler())

        t0 = time.monotonic()
        asyncio.run(soak())
        took = time.monotonic() - t0
        time.sleep(1)
        after_kb = rss_kb(gw.pid)
        growth = (after_kb - before_kb) / 1024
        # the second half: from the sample nearest the middle of the soak to the end
        mid_kb = samples[len(samples) // 2 - 1] if len(samples) >= 2 else before_kb
        late = (after_kb - mid_kb) / 1024
        total = st.ok + st.bad + st.errors
        print(f"soak: {total} requests in {took:.0f} s ({total / took:.0f}/s): {st.ok} ok, {st.bad} bad, {st.errors} errors"
              + (f" (last: {st.last_error})" if st.last_error else ""))
        print(f"soak: rss {before_kb / 1024:.1f} MB -> {after_kb / 1024:.1f} MB (growth {growth:+.1f} MB, {late:+.1f} MB over the second half; peak {max(samples + [after_kb]) / 1024:.1f} MB)")
        if late > a.max_growth_mb:
            failures.append(f"RSS grew {late:.1f} MB over the second half of the soak (limit {a.max_growth_mb:.0f} MB)")
        if st.ok == 0 or (st.bad + st.errors) > total * 0.01:
            failures.append(f"{st.bad + st.errors} of {total} requests failed")
        if gw.poll() is not None:
            failures.append(f"the gateway exited ({gw.returncode})")
    finally:
        for p in (gw, mock):
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print("soak: FAIL: " + "; ".join(failures))
        sys.exit(1)
    print("soak: ok")


if __name__ == "__main__":
    main()
