# fetch: pool options (keep-alive timeout, connections per origin) and HTTP/2 to servers that pick h2

Branch `feat/fetch-pool-http2`, one commit on top of `feat/alpn`. Series: [fetch-pool-http2/](fetch-pool-http2/).
Raiju patch: `0007-fetch-pool-http2.patch`.

Depends on: `feat/alpn` (the TLS ALPN pull request): `http2: "prefer"` offers `h2` through the
client offer that change adds. `feat/request-body-streams` builds on this one.

## What

`fetch`'s `init` takes `pool: { keepAliveTimeout, maxConnections, http2, http2PingInterval }`.
Idle connections can expire, the connections to an origin can be capped (further requests queue),
and requests can go over HTTP/2 to a TLS server that picks `h2`.

## Why

`fetch` pooled keep-alive connections with no way to tune them: an idle connection lived until the
server closed it, any number of concurrent requests opened that many connections to a host, and
every request was HTTP/1.1. A client that talks to a few busy APIs (a gateway in front of model
providers, say) needs a per-origin idle timeout and connection cap, and HTTP/2 to the servers that
offer it: many requests on one connection, with flow control per request.

## API

```ts
const res = try await fetch("https://api.example.com/v1/x", {
  pool: {
    keepAliveTimeout: 30,      // seconds an idle connection is kept (default: until the server closes it)
    maxConnections: 100,       // connections to the origin at once; more requests wait their turn (default: no limit)
    http2: "prefer",           // "off" (default) | "prefer" | "require"
    http2PingInterval: 10,     // seconds without a frame before a PING is sent (0: none)
  },
})
```

`"require"` fails the request with a `FetchError` whose code is `HTTP2NotNegotiated` when the
server does not pick `h2`. Requests without `pool` behave as before.

## Design

- Requests whose options differ do not share connections: the options are part of the pool key,
  so each set of settings is a pool of its own.
- `maxConnections` counts connections open or being made. A request that cannot start (no idle
  connection, no HTTP/2 connection with a free stream, cap reached) waits in a per-origin FIFO
  queue and starts when a connection goes idle or closes. An aborted waiting request leaves the
  queue.
- `keepAliveTimeout` stamps a connection when it goes idle and closes it once the stamp is that
  old: checked when a connection is picked, and by one timer that does not keep the program
  running.
- `http2: "prefer"` offers `h2` then `http/1.1` in ALPN. A server that picks `h2` gets one
  connection with many streams (concurrent requests wait for that connection's handshake instead
  of each opening one, and spill to another connection past the server's stream limit); one that
  does not gets HTTP/1.1, as Go's `ForceAttemptHTTP2` does. Plain `http:` URLs are always HTTP/1.1
  (no h2c).
- The framing is [nghttp2](https://nghttp2.org) 1.64.0, vendored in `vendor/nghttp2` and compiled
  with the other TLS-side libraries. `runtime/h2.c` is a thin layer over it; `runtime/tov.c` keeps
  the sockets, TLS and request objects. The request head is the HTTP/1.1 head `fetch` always
  builds, turned into pseudo-headers and headers; the response head is turned back into an HTTP/1.1
  head for the existing parser, so content decoding, redirects, `res.body` streaming and abort
  behave as on HTTP/1.1.
- Flow control follows the reader: body bytes are returned to the stream's window only once the
  reader has room (the 256 KiB mark that pauses an HTTP/1.1 socket), so a slow reader holds its own
  stream and not the connection's others. Windows are 1 MiB per stream and 16 MiB per connection.
- With `http2PingInterval`, a connection that has received no frame for that long sends a PING;
  one that is not answered within 15 s is closed and its requests fail (or are retried, if nothing
  of theirs was answered and the connection had served requests before). GOAWAY and
  REFUSED_STREAM retry the requests the server did not process on another connection. An aborted
  request resets its stream and leaves the connection open. Server push is disabled.

## Changes

- `runtime/tov.c`, `runtime/tov.h`: the pool (origin queue, limits, idle timer), the HTTP/2
  connections, and `fetchStart`'s four new arguments; `runtime/node.c` (the Node compatibility layer's fetch binding) passes zeros for them.
- `runtime/h2.c`: the nghttp2 layer; `runtime/tls.c` installs it with the TLS library.
- `vendor/nghttp2`, `crates/tov/build.rs`, `crates/tov/src/tls_flags.rs`: the library, its sources
  and include paths, and `-DHAVE_CONFIG_H -DNGHTTP2_STATICLIB`.
- `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`: the signature, `PoolOptions`.
- `docs/spec.md`: "Pool options" in §7d.
- `tests/fetch.rs`, `tests/fetch/h2/server.py`, `tests/fetch/native_pool.tov` (+ `.stdout`): the test.

## Vendored code

| Library | Version | Licence | Where |
|---|---|---|---|
| [nghttp2](https://nghttp2.org) (the library only: `lib/*.c`, `lib/*.h`, `lib/includes/nghttp2/nghttp2.h`, `nghttp2ver.h`) | 1.64.0, from `nghttp2-1.64.0.tar.xz` (SHA-256 `88bb94c9e4fd1c499967f83dece36a78122af7d5fb40da2019c56b9ccc6eb9dd`) | MIT (`vendor/nghttp2/LICENSE`) | `vendor/nghttp2/TOV.md`; `config.h` is Tov's own |

## Tests

`tests/fetch/native_pool.tov` (23 checks) against `tests/fetch/h2/server.py`, a small Python origin
(asyncio and the `h2` package) that `tests/fetch.rs` starts in three modes: TLS offering `h2`, TLS
with `http/1.1` only, and plain HTTP/1.1. The harness passes their ports as `H2_PORT`,
`H1TLS_PORT` and `H1_PORT`, and skips the program (counted as skipped) when Python's `h2` package is
not installed. Checks: eight concurrent requests on one HTTP/2 connection with eight streams open
at once, a later request reusing it, a 640 KB request body, a 3 MB body through a slow reader, a
body read whole with its headers, gzip, a redirect, HEAD, 250 requests spilling past a connection's
50 streams, an aborted stream leaving the connection usable, GOAWAY, PINGs on an idle connection,
the idle timeout on HTTP/2 and on HTTP/1.1, fallback to HTTP/1.1 under `prefer`, `require` failing,
`off`, six uncapped connections, `maxConnections: 2` queueing the rest, an aborted queued request,
keep-alive reuse and expiry.

Checked on the branch with `cargo test --release --test fetch` (with the sandbox's proxy variables
unset, since Bun reads them for `proxy.tov`), and by running the program against fresh origins
again and again. With `TOV_CFLAGS=-DTV_PLAIN_ALLOC` it passed every run (4 of 4, and in Raiju's
`run.sh`). With the default allocator it crashed in 4 of 9 runs (the harness included), each time in
`tv_promise_new` right after the 250-request check: that is the
async slab allocator fault that unpatched Tov has too (see `compiler-bugs.md`, R1, which reproduces
it at c2048582 with plain HTTP/1.1 fetches). The check exposes it, so the harness run of this test
is flaky until that fault is fixed; either fix the allocator first or lower the 250 to a count
below the fault's reach, and say which in the pull request.

## Limits

- No h2c (plain-text HTTP/2), no server push, no priorities, no `Upgrade`/WebSocket over HTTP/2.
  HTTP/2 through a proxy works through `CONNECT` as HTTPS does.
- Limits are per process: a `Bun.serve` with `workers: n` has a pool per worker.
- The server's counters (`/stats`) are for its lifetime, so the "eight streams at once" check holds
  only on a fresh server, which is how the harness runs it.
