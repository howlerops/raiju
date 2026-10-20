# Request bodies as streams: fetch with a ReadableStream body, req.body in Bun.serve, Socket.pause

Branch `feat/request-body-streams`, one commit on top of `base/request-body-streams`, which is
`feat/alpn` + `feat/fetch-pool-http2` + `feat/stream-response-bodies` (the latter cherry-picked
onto the pool branch; it applies there without changes). Series: [request-body-streams/](request-body-streams/).
Raiju patch: `0008-request-body-streams.patch`, including the use-after-free fix made in
`httpBodyCancel` (Raiju L157).

Depends on, in this order: `feat/alpn` → `feat/fetch-pool-http2` (the HTTP/2 data provider and the
pool's retry rules this changes) and `feat/stream-response-bodies` (`ReadableStream`'s underlying
source and controller, which this extends with `pull`). Open it after both pull requests; with them
merged it applies with `git am`.

## What

- `fetch` sends a `ReadableStream` body as it is read: chunked on HTTP/1.1 (as it is, when the
  caller gives a `Content-Length`) and as DATA frames on HTTP/2.
- `Bun.serve` hands a body larger than `bodyStreamThreshold` to the handler as soon as its head is
  in, as `req.body`, a stream fed by the connection as bytes arrive. `maxRequestBodySize` bounds it.
- A `ReadableStream` source may have `pull(controller)`, called when a reader wants a chunk.
- `Socket.pause()` and `resume()` stop and restart reading a socket (Node's pair).

## Why

Neither end of an HTTP request could stream its body. `fetch` took a string or bytes, and
`Bun.serve` held a request whole (up to 64 MiB) before calling the handler, so a server could not
pass a large upload on to another service without holding all of it, nor read the first bytes of a
large request (to route it) before the rest arrived.

## API

```ts
// fetch: a ReadableStream body is sent as it is read
const body = new ReadableStream({
  async pull(c) {                      // called when a reader wants a chunk and none is queued
    c.enqueue(await nextChunk())       // u8[] | string; c.close(), c.error(e)
  },
})
const res = try await fetch(url, { method: "POST", body, headers: { "content-length": "123" } })  // length optional

// Bun.serve: a body over the threshold reaches the handler before it has arrived
Bun.serve({
  bodyStreamThreshold: 262144,         // bytes (Content-Length, or what a chunked body has sent so far)
  maxRequestBodySize: 1 << 30,         // a declared length over it is a 413; a chunked body past it fails its stream
  async fetch(req) {
    for await (const chunk of req.body!) { /* u8[] */ }
    // or req.text(), req.json(), req.bytes(): they read the stream whole
    return new Response("ok")
  },
})

sock.pause(); sock.resume()            // Socket (Bun.connect / Bun.listen)
```

`Request.body` is `ReadableStream | undefined` (a body that came whole is a one-chunk stream).

## Design

- `fetch` (`runtime/tov.c`). A stream body is flagged to `fetchStart`, and the Tov side pumps it:
  `fetchWrite(id, bytes)` appends the next chunk and returns a promise that settles once it is on
  the wire (HTTP/1.1: written to the socket, framed as a chunk unless the caller gave a
  `Content-Length`; HTTP/2: handed to nghttp2 by a deferred data provider that waits for the
  stream's window). So at most one chunk waits in memory and a slow server slows the source. A
  negative result means the request is over (the response came first, it failed, or it was
  aborted) and the pump cancels the source; `fetchEnd` ends the body; a source that fails aborts
  the request.
- The request cannot be repeated, so a 307 or 308 answer is returned instead of followed, and a
  request that fails on a reused connection is retried only while everything sent is still held
  (the first 1 MiB of the body is kept for that, then dropped). A server that answers early and
  closes (an HTTP/1.1 413, say) has its answer read: a write failure switches the request to
  reading.
- `Bun.serve` (`runtime/tov.c`, `tv_http_bs`). A body over `bodyStreamThreshold` is handed to the
  handler once its head is in; the connection's later bytes feed the stream (by Content-Length, or
  an incremental chunked decoder with trailers) while `httpBodyRead` / `httpBodyTake` give them to
  the handler. Once 512 KiB are held the socket is not read until the handler takes them, so a slow
  handler slows the sender. A body nobody reads is dropped when the request is answered (at most
  32 MiB more; past that the connection closes), and the connection serves its next request. A
  client that leaves or half-closes fails the stream. `Expect: 100-continue` is answered for a
  streamed body.
- Cancelling a body that is all in frees its stream at once. `httpBodyCancel` reads the stream's
  connection before discarding the stream, since discarding may free it (an earlier version read
  `b->c` after the free: a use-after-free that crashed a server whose handler cancelled a fully
  received body, for instance when its upstream refused the connection).
- `Socket.pause()` (`runtime/net.c`, `netPause`) takes the socket off the read interest.

## Changes

- `runtime/tov.c`, `runtime/tov.h`: the request writer (`fetchWrite`, `fetchEnd`) and the
  server-side body stream (`httpBodyOptions`, `httpBodyStream`, `httpBodyRead`, `httpBodyTake`,
  `httpBodyCancel`).
- `runtime/h2.c`: the streaming data provider and its resume.
- `runtime/net.c`: `netPause`.
- `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`: the signatures,
  `RequestInit.body`, `UnderlyingSource.pull`, `Request.body`, `ServeOptions`, `Socket.pause`/`resume`.
- `docs/spec.md`: "Request body streams" (§7c), "Stream bodies" (§7d), `pause`/`resume` (§7e).
- Tests: `tests/fetch/native_request_body.tov` (+ `.stdout`), `tests/fetch/h2/server.py` (the
  request-body routes `/upload`, `/slowup`, `/early`, `/redir307`), `tests/fetch.rs` (the program
  needs the HTTP/2 origins); `tests/http/body_stream.tov`, `tests/http/body_stream_client.py`,
  `tests/http.rs`; `tests/run/native_socket_pause.tov` (+ `.stdout`).

## Vendored code

None (nghttp2 comes with `feat/fetch-pool-http2`).

## Tests

- `tests/fetch/native_request_body.tov` (36 checks, 12 per protocol) against the HTTP/2 test
  origins in their three modes (HTTP/1.1, HTTP/1.1 over TLS, HTTP/2): small chunks in order, an
  empty stream, a stream with a Content-Length, 6 MiB produced as consumed, odd chunk sizes,
  backpressure (the source is pulled less than 24 MiB ahead while the server does not read, then
  the whole 64 MiB arrives), an early 413 returned and the source cancelled, a failing source, a
  307 returned, and the next request on the origin. Skipped (counted) without Python's `h2` package.
- `tests/http/body_stream.tov` driven by `tests/http/body_stream_client.py` from `tests/http.rs`
  (19 checks; skipped without python3): a 1 MiB body through `req.body`, a body under the
  threshold, `req.text()` on a streamed body, chunked framing with extensions and trailers (whole
  and byte by byte), the next request on the connection, an ignored body dropped and the connection
  usable, an answer before the body is in, `Expect: 100-continue`, both 413 cases, a client that
  leaves mid-body and one that cuts a body short, a sender held back while the handler does not
  read and the server's peak memory (it does not hold a 24 MiB body), `req.body` relayed as a
  `fetch` body (10 MiB), and a handler cancelling a body that is all in (the use-after-free case),
  with the server serving on after it.
- `tests/run/native_socket_pause.tov` (2 checks): a paused socket is not read while a client sends
  64 MiB, and `resume()` reads all of it.

Checked on the branch: `cargo test --release --test http` passes (body streams included);
`cargo test --release --test fetch` runs `native_request_body` green, and fails only on
`native_pool`'s allocator crash described in `fetch-pool-http2.md` (an unpatched-Tov fault); the
run program passes.

## Limits

- A stream body cannot go through a redirect that keeps the method, and after 1 MiB a failed
  request is not retried.
- A TLS HTTP/1.1 server that answers early and resets the connection may cost the answer (HTTP/1.1
  over plain TCP and HTTP/2 return it).
- The worker processes of `workers: n` each hold their own streams.
- `Request.body` of a request already read with `text()` is the empty stream.
