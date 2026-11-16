#!/usr/bin/env python3
"""Token-throughput benchmark for a gateway in front of an OpenAI-style streaming upstream.

  tokbench.py mock PORT TOKENS      SSE upstream: every POST answers TOKENS content chunks, a usage chunk, [DONE]
                                    (stream:false answers one JSON body with the same text)
  tokbench.py load URL C SECONDS [nostream]
                                    C concurrent clients for SECONDS; prints one JSON line:
                                    requests, tokens/s (content chunks received), req/s, time to first token, errors
"""
import asyncio, json, sys, time

CHUNK = b'data: {"id":"chatcmpl-b","object":"chat.completion.chunk","created":1,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"content":"tok "},"finish_reason":null}]}\n\n'
FIRST = b'data: {"id":"chatcmpl-b","object":"chat.completion.chunk","created":1,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'


async def read_request(reader):
    head = await reader.readuntil(b"\r\n\r\n")
    n = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            n = int(line.split(b":", 1)[1])
    body = await reader.readexactly(n) if n else b""
    return head, body


async def mock_conn(reader, writer, tokens):
    try:
        while True:
            try:
                head, body = await read_request(reader)
            except (asyncio.IncompleteReadError, ConnectionError):
                return
            if b'"stream":true' in body.replace(b" ", b""):
                writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n")

                def frame(b):
                    return b"%x\r\n" % len(b) + b + b"\r\n"

                writer.write(frame(FIRST))
                for i in range(tokens):
                    writer.write(frame(CHUNK))
                    if i % 8 == 7:
                        await writer.drain()
                last = b'data: {"id":"chatcmpl-b","object":"chat.completion.chunk","created":1,"model":"gpt-4o-mini","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":9,"completion_tokens":%d,"total_tokens":%d}}\n\ndata: [DONE]\n\n' % (tokens, tokens + 9)
                writer.write(frame(last) + b"0\r\n\r\n")
                await writer.drain()
            else:
                out = json.dumps({"id": "chatcmpl-b", "object": "chat.completion", "created": 1, "model": "gpt-4o-mini", "choices": [{"index": 0, "message": {"role": "assistant", "content": "tok " * tokens}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9, "completion_tokens": tokens, "total_tokens": tokens + 9}}).encode()
                writer.write(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: %d\r\n\r\n" % len(out) + out)
                await writer.drain()
    finally:
        writer.close()


async def mock(port, tokens):
    srv = await asyncio.start_server(lambda r, w: mock_conn(r, w, tokens), "127.0.0.1", port, backlog=1024)
    async with srv:
        await srv.serve_forever()


async def client(host, port, path, deadline, stats, stream):
    body = json.dumps({"model": "openai/gpt-4o-mini", "stream": stream, "messages": [{"role": "user", "content": "Write a long answer."}]}).encode()
    req = b"POST %s HTTP/1.1\r\nhost: %s\r\ncontent-type: application/json\r\nx-raiju-cache-no-store: true\r\ncontent-length: %d\r\n\r\n" % (path.encode(), host.encode(), len(body)) + body
    reader = writer = None
    while time.perf_counter() < deadline:
        try:
            if writer is None:
                reader, writer = await asyncio.open_connection(host, port)
            t0 = time.perf_counter()
            writer.write(req)
            await writer.drain()
            head = await reader.readuntil(b"\r\n\r\n")
            if not head.startswith(b"HTTP/1.1 200"):
                stats["errors"] += 1
            chunked = b"transfer-encoding: chunked" in head.lower()
            toks = 0
            first = None
            if chunked:
                while True:
                    size = int((await reader.readline()).strip() or b"0", 16)
                    if size == 0:
                        await reader.readline()
                        break
                    data = await reader.readexactly(size + 2)
                    c = data.count(b'"content":"tok ')
                    if c and first is None:
                        first = time.perf_counter() - t0
                    toks += c
            else:
                n = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        n = int(line.split(b":", 1)[1])
                data = await reader.readexactly(n)
                toks = data.count(b"tok ")
                first = time.perf_counter() - t0
            stats["requests"] += 1
            stats["tokens"] += toks
            stats["lat"].append(time.perf_counter() - t0)
            if first is not None:
                stats["ttft"].append(first)
        except Exception:
            stats["errors"] += 1
            if writer is not None:
                writer.close()
            reader = writer = None
    if writer is not None:
        writer.close()


def pct(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] * 1000.0


async def load(url, c, seconds, stream):
    rest = url.split("://", 1)[1]
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    stats = {"requests": 0, "tokens": 0, "errors": 0, "lat": [], "ttft": []}
    t0 = time.perf_counter()
    await asyncio.gather(*[client(host, int(port), "/" + path, t0 + seconds, stats, stream) for _ in range(c)])
    dt = time.perf_counter() - t0
    print(json.dumps({"tokens_per_s": round(stats["tokens"] / dt), "req_per_s": round(stats["requests"] / dt, 1), "ttft_p50_ms": round(pct(stats["ttft"], 0.5), 2), "ttft_p99_ms": round(pct(stats["ttft"], 0.99), 2), "lat_p50_ms": round(pct(stats["lat"], 0.5), 1), "lat_p99_ms": round(pct(stats["lat"], 0.99), 1), "requests": stats["requests"], "errors": stats["errors"]}))


if __name__ == "__main__":
    if sys.argv[1] == "mock":
        asyncio.run(mock(int(sys.argv[2]), int(sys.argv[3])))
    else:
        asyncio.run(load(sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), not (len(sys.argv) > 5 and sys.argv[5] == "nostream")))
