# Port notes — workstream s1 (HTTP server and worker processes)

Branch `port-s1`, on upstream Tov v0.1.0 (`ca1e3d2`). One commit per patch (`git log --oneline v0.1.0..port-s1`).

| Patch | Status | Commit subject |
|---|---|---|
| 0001 streamed response bodies | PORT (applied textually; upstream has none) | `port 0001: ...` |
| 0012 server lifecycle | PORT | `port 0012: ...` |
| 0021 `Math.random` seeding | PORT (re-derived on upstream's inline generator) | `port 0021: ...` |
| 0019 worker respawn, `Bun.plainAlloc` | PORT, plus two fixes found here | `port 0019 (prerequisite): ...`, `port 0019: ...` (2) |
| 0026 clean worker re-execution | PORT | `port 0026: ...` |
| 0008 request body streams | PARTIAL: server half, `UnderlyingSource.pull`, `Socket.pause/resume` ported; fetch-client half left to s2 | `port 0008 (server half): ...` |
| 0017 `server.requestIP` | PORT (not a DROP: upstream's std/http has no `requestIP`) | `port 0017: ...` |
| 0022 write-stall limit on upgraded sockets | PARTIAL: server part ported; peer policy on `Bun.connect`/`WebSocket` left to s2 | `port 0022 (server part): ...` |

Nothing was dropped: upstream v0.1.0's `std/http.tov` has none of these capabilities (checked by reading
`crates/tov/src/std/http.tov`, `crates/tov/src/check/builtins.rs` and `runtime/tov.c` at v0.1.0; the only
`requestIP` in the tree is in a JavaScript npm test fixture, `tests/npm/node_modules/bun-serve/index.js`).

How the ports were made: the patch series was applied at the pin (`c2048582`) as one commit per patch on a
scratch branch, and each of my patches was cherry-picked onto v0.1.0 so git did a real three-way merge;
conflicts and upstream's changed internals were resolved by hand as described below.

## Read this first: three things that affect the other workstreams and Raiju

1. **`TOV_CFLAGS=-DTV_PLAIN_ALLOC` corrupts the heap on unmodified v0.1.0.** Upstream split the
   "plain malloc" switch into four (`TV_PLAIN_ALLOC` in `runtime/tov.c`, `TV_SB_SMALL` there too,
   `TV_ARRBUF_PLAIN` in `runtime/tov.h`, `TVG_PLAIN_ALLOC` in `crates/tov/src/codegen/prelude.h`), each
   keyed on AddressSanitizer only. Passing just `-DTV_PLAIN_ALLOC` (what Raiju and every test in
   `tov-patches/tests/run.sh` do) makes the runtime `free()` blocks the generated code carved from the
   small-object lists: `free(): invalid pointer` on the first closure environment released (seen with
   `stream_body.tov`; valgrind showed `tv_env_release` freeing a `tvg_alloc_small` block). Commit
   `port 0019 (prerequisite)` makes the user flag turn on all four, i.e. exactly the configuration
   upstream runs under ASan. **s2 and s3 need this commit (or the same four-line change) before any test
   built with `-DTV_PLAIN_ALLOC` means anything.** Not verified: whether upstream still needs the flag
   for thread safety at all, and whether other single-thread caches (e.g. the `TV_STR_KEEP` freed-string
   cache in `runtime/tov.c`) are safe for whatever allocates off the loop thread — that is fetch/DNS
   territory (s2).
2. **The build container's JavaScriptCore (`TOV_JSC_DIR=/src/build/jsc/current`) is too old for
   v0.1.0**: any program that needs the engine fails to compile (`node.c: call to undeclared function
   'TVHeapStatistics'`). Raiju's `scripts/build-jsc.sh` must build the WebKit release v0.1.0 pins. Until
   then JSC-backed programs only build with `TOV_JSC=system` and WebKitGTK installed
   (`libjavascriptcoregtk-4.1-dev`, 2.52.6 on Ubuntu 24.04), which is how 0026 was tested here (a derived
   local image `raiju:dev4-s1jsc` = `raiju:dev4` + that package).
3. **`req.signal` on `Bun.serve` requests (patch 0015) is not in this branch** and Raiju uses it
   (2 call sites). It is server-side code that touches the same `Request` class and `serve()` this branch
   edits; upstream already has the runtime half (`tv_http_on_gone` / `tv_http_note_gone`, used by Node's
   http), so whoever owns 0015 needs only `httpOnGone` and the Tov side. Expect a small textual conflict
   in `Request`'s field list with 0017's `peerAddr`/`peerPort`.

## `Bun.serve` API: upstream v0.1.0 vs the patched pin vs this branch

Raiju's "Bun.serve option mismatch" type errors against unpatched v0.1.0 are these missing names.
`+` = restored by this branch, `-` = still missing here (other workstream).

```
ServeOptions (v0.1.0: port, hostname, routes, fetch, error, websocket, development, workers)
+ idleTimeout?: number            (pin: number)
+ headerTimeout?: number          (pin: number)
+ bodyTimeout?: number            (pin: number)
+ maxConnections?: number         (pin: int)
+ bodyStreamThreshold?: number    (pin: int)
+ maxRequestBodySize?: number     (pin: int)
~ workers?: number                (pin: int; upstream's own change)

Server
+ requestIP(req): SocketAddress | undefined       (0017)
+ get openConnections(): int                      (0012)

Request
+ get body(): ReadableStream | undefined          (0008)
~ text/json/formData/blob/bytes/arrayBuffer are `async` methods again (same types as the pin's)
- get signal(): AbortSignal, clientLeft()         (0015, not in this branch)

RequestInit
+ body?: BodyInit | ReadableStream                (0008; see the fetch caveat under 0008)
- pool?: PoolOptions, peer?: PeerPolicy           (0007/0013, s2)

Response
+ constructor(body?: BodyInit | ReadableStream, init?)   (0001)

ReadableStream / globals
+ new ReadableStream({ start?, pull?, cancel? })  (0001, 0008); upstream's constructor takes no argument
+ ReadableStreamDefaultController (global): enqueue(u8[] | string), close(), error(e), desiredSize
+ UnderlyingSource (type)

Socket
+ pause(), resume()                               (0008)

Bun
+ onStopSignal(f), fdLimit()                      (0012)
+ plainAlloc()                                    (0019)
+ cleanWorkers(), workersReady(), workerSupervisor(), workerState(name, value)   (0026)
- gunzipSync, inflateSync, spawnSocket, udpSocket (0015, 0002, 0004: other workstreams / upstream's own)

WebSocketHandler (upstream's own change, nothing to port)
~ maxPayloadLength, idleTimeout, backpressureLimit: number (pin: int)
```

The option fields this branch adds are typed `number` and truncated with `Math.trunc`, following
upstream's convention for `workers` and `port` (the pin used `int`). An `int` value still type-checks
where `number` is expected, so Raiju's call sites need no change for that.

Language changes Raiju's callers of these APIs will meet (seen while porting the tests): `parseInt`
returns `NaN`, not `undefined` — `parseInt(x) ?? d` must become `parseInt(x) || d`.

## 0001 — streamed response bodies for `Bun.serve` — PORT

Upstream has no streamed responses: `ReadableStream` has no underlying source and no controller, and
`Response` takes only a `BodyInit` (hence Raiju's type errors on the constructor and controller).
The patch cherry-picked without conflicts and its C needed no change (`tv_native_httpWriteRaw`, which it
builds on, is unchanged upstream).

- Files: `runtime/tov.c`, `runtime/tov.h` (`httpStreamStart`, `httpStreamWrite`, `httpStreamAbort`),
  `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`, `crates/tov/src/driver.rs` (the
  `ReadableStreamDefaultController` global).
- API: unchanged from the patch.
- Test: `raiju-tests/stream_body.tov` (run.sh section `stream`), 2 of 2 checks: chunks arrive spread
  out with 2 workers; a failed stream cuts the connection without the last chunk. Valgrind (memcheck,
  `-DTV_PLAIN_ALLOC -g`) reports nothing on three streamed requests including the failing one.

## 0012 — server lifecycle — PORT

Three conflicts (the connection and server structs, the read loop), all from neighbouring patches rather
than upstream changes; the sweep, the signal pipe, the spare descriptor and the supervisor's exit status
went in as written. Upstream's loop gained an io_uring "rings" phase and `tv_loop_host_busy`; the sweep
hooks sit beside them unchanged.

- Files: `runtime/tov.c`, `runtime/tov.h`, `runtime/net.c` (spare descriptor for `Bun.listen`),
  `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`, `docs/spec.md`.
- API: as the patch, except `maxConnections?: number` (was `int`).
- Security behaviour unchanged: header/body timeouts answer 408 and close, idle and write-stall close,
  the cap answers 503, EMFILE/ENFILE is shed with 503 from the spare descriptor.
- Test: `raiju-tests/server_lifecycle.tov` + `server_lifecycle_client.py` (section `lifecycle`),
  18 of 18 checks.

## 0021 — `Math.random` seeding — PORT (re-derived)

Upstream moved the generator inline into `tov.h` and seeds it at program start, only in programs that
draw numbers (`tv_random_init`, inserted by codegen), still **with a constant seed unless `TOV_SEED` is
set** — so the problem the patch fixes is still there. The port keeps upstream's structure (inline
`tv_random`, no per-draw check) and changes `tv_random_init` to seed from the system unless
`TOV_SEED=<n>`; `tv_random_after_fork(w)` reseeds in each forked worker (`tv_http_spawn`) and in each
clean worker's bootstrap. The system source is upstream's own `tv_random_bytes` (getrandom on Linux,
`arc4random_buf` elsewhere).

- Difference from the patch: no fallback to clock/pid when the system gives no bytes — `tv_random_bytes`
  traps instead ("no random bytes from the system"), upstream's convention.
- Behaviour change against upstream: programs that relied on the constant default seed now need
  `TOV_SEED=<n>`. Upstream's `run` suite (which has programs using `Math.random`) still passes.
- Files: `runtime/tov.c`, `runtime/tov.h`, `runtime/README.md`.
- Test: `raiju-tests/random_seed.tov` + `random_seed_client.py` (section `random`), 5 of 5 checks.

## 0019 — worker respawn with backoff, `Bun.plainAlloc()` — PORT (+ two fixes)

Cherry-picked cleanly apart from `docs/spec.md`. Two additions made here:

- **`port 0019 (prerequisite)`**: `-DTV_PLAIN_ALLOC` as a coherent user flag (see "Read this first").
  Files: `runtime/tov.c`, `runtime/tov.h`, `crates/tov/src/codegen/prelude.h`.
- **A bug in the patch itself, found by upstream's `http` suite** (`workers respawned`): when every
  worker is dead at once and their slots are in the respawn pause, `waitpid(-1, WNOHANG)` returns
  `ECHILD`, the supervisor took that as "every worker finished" and exited, closing the port. The
  patched pin has the same bug (its own test kills one of two workers, so it never saw it). Fixed: with
  a slot waiting, `ECHILD` sleeps 100 ms and continues. Raiju behaviour change: a node whose workers all
  crash together now recovers instead of exiting 0.

- Files: `runtime/tov.c`, `runtime/tov.h`, `crates/tov/src/check/builtins.rs`,
  `crates/tov/src/std/http.tov`, `docs/spec.md`.
- API: unchanged (`Bun.plainAlloc(): boolean`).
- Test: `raiju-tests/worker_respawn.tov` + `worker_respawn_client.py` (section `respawn`), 10 of 10.

## 0026 — clean worker re-execution — PORT

One conflict (`http.tov`, neighbouring 0015 methods); the C merged automatically and was checked against
upstream's `tv_http_run`, `tv_http_spawn` and `tv_async_run`. The four `Bun` statics now sit in one block
at the end of `class Bun` with the other s1 additions.

- Files: `runtime/tov.c`, `runtime/tov.h`, `crates/tov/src/check/builtins.rs`,
  `crates/tov/src/std/http.tov`.
- API: unchanged (`Bun.cleanWorkers()`, `Bun.workersReady()`, `Bun.workerSupervisor()`,
  `Bun.workerState(name, value)`).
- Test (needs `pkg-config javascriptcoregtk-4.1`, so it fails in plain `raiju:dev4`):
  `raiju-tests/clean_workers.sh` (section `clean`): 5 of 5 checks in each of the two startup
  orders (10 "ok" lines), run with `TOV_JSC=system` in the derived image because the container's static
  engine cannot build against v0.1.0. **Not tested with the static engine Raiju links** — that needs
  the engine rebuilt first. As the patch's README says, this does not prove deployed stability.

## 0008 — request body streams — PARTIAL (server half ported)

Ported: `Bun.serve`'s body streams (`tv_http_bs` and the natives `httpBodyOptions`, `httpBodyStream`,
`httpBodyRead`, `httpBodyTake`, `httpBodyCancel`), `Request.body`, `bodyStreamThreshold`,
`maxRequestBodySize`, `UnderlyingSource.pull`, and `Socket.pause()` / `resume()` (`netPause` in
`runtime/net.c`). The 0012 sweep's rule for a body stream (a paused reader is not timed out) was added
back with it.

Adapted to upstream: arrays are shared references now, so `httpBodyTake` returns `tv_arr_fresh()` and
sets `a.p->len` (the pin had a value `tv_arr` with `.len`); option fields are `number`.

**Left to s2** (everything under the fetch client in `runtime/tov.c`, and upstream's HTTP/2, which
replaced `runtime/h2.c`): the natives `fetchWrite` / `fetchEnd`, the `tv_fr` stream-body fields and
replay rules, the HTTP/2 data provider, the 307/308 rule, and in `http.tov` the `sendBody` pump and the
`fetchStart` flag. To keep the two halves mergeable I kept the patch's `Request` class and
`RequestInit.body` text verbatim, and in `fetch()` kept the lines that find `bodyStream` but replaced the
`sendBody(id, bodyStream)` call with a `FetchError` (`ERR_NOT_IMPLEMENTED`, "fetch() with a ReadableStream
body is not supported in this build") thrown before `fetchStart`, so a stream body fails loudly instead
of being sent empty. s2 replaces that block with the pump.

- Files: `runtime/tov.c`, `runtime/tov.h`, `runtime/net.c`, `crates/tov/src/check/builtins.rs`,
  `crates/tov/src/std/http.tov`.
- Tests:
  - `raiju-tests/request_body_server.tov` + `request_body_client.py` (section `body`): **18 of 19**.
    The failing check is "req.body can be the body of a fetch() (10 MiB relayed)", which needs the
    client half (it gets the 502 from the `FetchError` above). run.sh still expects 19, so that section
    fails until s2's half is merged; it is the last section so the others report first. Same 18 with the
    default allocator. Valgrind reports nothing over the first 14 checks.
  - `raiju-tests/socket_pause.tov` (section `pause`): 2 of 2.
  - `request_body_fetch.tov` (36 checks, needs the HTTP/2 test server) is the client half: not ported, not run.

## 0017 — `server.requestIP(req)` — PORT

The brief expected a DROP; upstream's std/http has no `requestIP` (see the top). Ported as written
(`tv_http_conn.peer`, `httpPeer`, `Request.peer()`, `SocketAddress`).

- Files: `runtime/tov.c`, `runtime/tov.h`, `crates/tov/src/check/builtins.rs`,
  `crates/tov/src/std/http.tov`, `docs/spec.md`.
- API: unchanged: `{ address: string, family: "IPv4" | "IPv6" (typed string), port: int } | undefined`.
- Test: `raiju-tests/request_ip.tov` (section `ip`), 4 of 4.

## 0022 — write-stall limit on upgraded sockets — PARTIAL (server part ported)

The stall limit separated cleanly and was applied by hand: the `stall_*` fields and list in
`runtime/net.c` (`tv_ns_stall_watch`, `tv_ns_stall_sweep`, the two `at_take` updates), the hook in the
server's sweep (`tv_http_sweep_net` in `runtime/tov.c`), and the call in `wsUpgrade` (`runtime/ws.c`).

**Left to s2**: the address policy (`netPeer`, `tv_peer_refuses`, `ConnectOptions.peer`,
`WebSocketOptions.peer`, the WebSocket client connecting in a microtask) — it shares 0013's code in the
fetch client. `socket_peer.tov` (16 checks) not ported, not run.

- Files: `runtime/net.c`, `runtime/ws.c`, `runtime/tov.c`, `docs/spec.md`.
- API: none new (`idleTimeout` on a server with `websocket` handlers).
- Test: `raiju-tests/ws_stall.tov` + `ws_stall_client.py` (section `stall`), 5 of 5.

## Test results

Raiju's patch tests, `raiju-tests/run.sh` (run in the container:
`TOV=/tov/target/release/tov sh raiju-tests/run.sh [section ...]`; every program built with
`TOV_CFLAGS=-DTV_PLAIN_ALLOC` as in the original): stream 2/2, lifecycle 18/18, respawn 10/10,
random 5/5, clean 10/10 (system JSC), ip 4/4, stall 5/5, pause 2/2, body 18/19 (see 0008).
Changes made to the copied tests: `parseInt(x) ?? d` → `parseInt(x) || d` in four `.tov` files; nothing
else, and no expected count was lowered.

Upstream suites, this branch against an unmodified v0.1.0 tree built the same way (same container):

| Suite | This branch | Unmodified v0.1.0 |
|---|---|---|
| `--test http` | 0 failed | 0 failed |
| `--test run` | 375 programs, 10 failed | 375 programs, 10 failed (the same 10) |
| `--test fetch` | 5 programs, 3 failed | 5 programs, 3 failed |
| `--test async` | 12 programs, 0 failed | not run |
| `--test ui` | 25 cases, 0 failed; examples 7 files, 0 errors | not run |
| `--test cli` | 5 passed | not run |
| `--test robustness` | 22010 inputs, no panics | not run |

With `TOV_JSC=system` (WebKitGTK's engine, in the derived image) `--test run` on this branch is
375 programs, 0 failed. The 10 `run` failures are all the container's old JavaScriptCore (`TVHeapStatistics` undeclared in
`node.c`): `js_callback_trap`, `js_fused_read_uncaught`, `js_read_errors`, `js_read_uncaught`,
`native_js_loop_overflow`, `native_js_loop_remainder_zero`, `native_trap_js_int8array_u8s`,
`native_trap_js_object_u8s`, `npm_const_throws`, `stdin`. The `fetch` failures are TLS in this
container (`CERT_VERIFY_FAILED: Invalid certificate verification context` on every https request), on
both trees. `--test npm` and `--test parity` were not run (they need the engine).

## Open and unverified

- macOS / kqueue paths compile-checked by nobody here: everything was built and run on Linux x86-64 only.
- 0026 was exercised with the system WebKitGTK engine, not the static engine Raiju ships.
- 0008's client half, 0022's peer policy and 0015's `req.signal` are not in this branch (above).
- Whether `-DTV_PLAIN_ALLOC` is still required on v0.1.0, and sufficient for off-thread allocation, was
  not investigated; the flag is now at least self-consistent.

---

# Port notes — workstream s2 (HTTP client `fetch`, raw sockets)

Branch `port-s2`, **rebased onto `port-s1`** (cb2f7ab) so the files both workstreams touch (`std/http.tov`,
`runtime/tov.c`, `net.c`, `tov.h`, `builtins.rs`) merge without conflicts: `port-s2` contains all of s1 and
nine commits on top. Merging s2 after s1 is a fast-forward of s1.

| Patch | Status | Commit |
|---|---|---|
| 0002 `Bun.spawnSocket` | PORT (applies as is) | `port 0002: ...` |
| 0003 TLS ALPN on `Bun.connect` | **PORT, not DROP** (see below) | `port 0003: ...` |
| 0004 UDP (`Bun.udpSocket`, `node:dgram`) | **PORT, not DROP** | `port 0004: ...` |
| 0007 fetch pool options + HTTP/2 | **PORT** (upstream has neither) | `port 0007: ...` |
| 0008 request body streams, fetch half | PORT (on s1's server half) | `port 0008 (fetch half): ...` |
| 0013 fetch address policy (`peer`) | PORT, + one tightening (proxy) | `port 0013: ...` |
| 0022 address policy on `Bun.connect` / `WebSocket` | PORT (the write-stall part is s1's a22a5cc) | `port 0022 (address policy): ...` |
| 0015 client certificates, `Request.signal`, `gunzipSync`/`inflateSync` | **PORT, all three** | `port 0015: ...` |
| 0016 fetch input buffer | PORT (adapted to upstream's buffer cache) | `port 0016: ...` |

## Read this first

1. **The brief's premise is wrong for this workstream.** Upstream v0.1.0 has *no* native (std/http) ALPN
   option, UDP sockets, HTTP/2, pooling options, request body streams, client certificates or
   `gunzipSync`. What upstream grew is in the Node compatibility layer only (`runtime/node/*.js`: `dgram.js`,
   `zlib.js`, `_tls_wrap.js` ... run on JavaScriptCore for npm packages), and even there
   `internalBinding('udp_wrap')` is a stub that throws "not implemented in Tov yet". `docs/spec.md` at v0.1.0
   still says "ALPN `http/1.1`", "HTTP/1.1 on pooled keep-alive connections" and "Not yet: request bodies as
   streams, client certificates". Checked by grep over `crates/tov/src/std`, `runtime/*.c`, `runtime/tov.h`
   and `docs/spec.md`. So nothing here is a DROP: **every Raiju call shape of these patches is kept
   unchanged** and nothing has to be adapted to an upstream API.
2. **How the port was made.** The pin plus the patches was rebuilt as one commit per patch, and each patch
   was cherry-picked (3-way) onto v0.1.0, so only real conflicts needed hand work. `net.c`, `tls.c`, `ws.c`
   and `std/http.tov` barely changed upstream; the fetch client in `tov.c` changed a lot (io_uring rings,
   a socket helper thread with "spare" connections, big bodies received on threads) and the hand work is
   there (0007, 0008, 0013, 0016 below).
3. **An upstream bug found and fixed (in the 0008 commit, `tv_fc_tls_ready`).** A TLS handshake begun while
   TCP is still connecting can finish inside that first call (seen on loopback with a resumed session);
   `c->connecting` stayed set, the connect event then ran the end of the handshake again and **the request
   was sent twice on the connection**. Unmodified v0.1.0 has the same code. It showed as a duplicated
   request head on a streamed upload, in 1 of 3 runs of the test section with `TOV_URING=1` (and in most batches of 8 while it was being traced). Fix: one line clearing
   `c->connecting` when the handshake completes. Verified: 6 of 6 runs clean afterwards.
   Its sibling is **not fixed** (upstream behaviour, left alone): a handshake that *fails* in that same
   window (a certificate error) is reported as `ConnectionRefused` instead of the TLS code. That is the
   flake in upstream's own `--test fetch` (`tls`: "unknown CA: ConnectionRefused"): 2 of 31 runs on
   unmodified v0.1.0 under CPU load, 1 of 10 on this branch.
4. **Test environment facts.** (a) `tovbuild.sh` passes `HTTPS_PROXY` into the container and fetch honours
   it: every local https test then fails with `Invalid certificate verification context`. `run-s2.sh` unsets
   the proxy variables; s1's note that `--test fetch` fails 3 of 5 "on both trees" is this, not TLS: with
   the variables unset it is 5 programs, 0 failed. (b) `TV_PLAIN_ALLOC` needs s1's c3105cd (included here by
   the rebase). (c) The container's own JavaScriptCore is too old for v0.1.0; JSC-backed tests were run in
   `raiju:dev4-s1jsc` with `TOV_JSC=system`.
5. **Commits carry no attribution trailers**: upstream's `AGENTS.md` forbids them in this repository.

## 0002 — `Bun.spawnSocket` — PORT

Cherry-pick applies cleanly; no change to the patch. Files: `runtime/net.c`, `runtime/tov.h`,
`builtins.rs`, `std/http.tov`. Test `spawn_socket.tov`: 1/1. API unchanged.

## 0003 — TLS ALPN on `Bun.connect` — PORT

Upstream's only ALPN is the fixed `http/1.1` its fetch contexts offer. Ported as patched: `tls.alpn:
string[]` on `Bun.connect`, `socket.alpnProtocol` (`""` for none), sessions keyed by the offer. One
conflict: upstream added a `set_io` slot to `tv_tls_ops` (for io_uring); `alpn` now follows it. Files:
`runtime/tls.c`, `net.c`, `ws.c`, `tov.c`, `tov.h`, `builtins.rs`, `std/http.tov`. Test `alpn.tov` with
`tls_server.py`: 3/3. API unchanged.

## 0004 — UDP sockets — PORT

Ported as patched (`Bun.udpSocket`, `UDPSocket`, broadcast, TTLs, multicast membership, `reusePort`,
`ref`/`unref`; `node:dgram` through `udp_wrap.js` and the natives in `node.c`). Adapted to upstream's
array representation (`bytes.p->len`, `tv_arr_fresh()`) and closure type (`tv_env *`); `UDPSocket.port`
uses `Math.trunc(parseInt(..) || 0)`. Files: `runtime/net.c`, `node.c`, `node/internal/bindings/udp_wrap.js`,
`tov.h`, `builtins.rs`, `driver.rs` (the `UDPSocket` global), `std/http.tov`. Tests: `udp.tov` 8/8;
`udp_dgram.tov` (node:dgram) 8/8 with the system JavaScriptCore image, and 8/8 in the stock container with
`JS_CFLAGS='-DTVHeapStatistics(c,v)=((void)0)'` to get past its old engine. API unchanged.

## 0007 — fetch pool options and HTTP/2 — PORT

Upstream fetch is HTTP/1.1 only, with an untunable pool. Ported as patched: `RequestInit.pool`
(`keepAliveTimeout`, `maxConnections`, `http2: "off" | "prefer" | "require"`, `http2PingInterval`),
nghttp2 1.64.0 vendored in `vendor/nghttp2` (57 files, as in the patch), `runtime/h2.c`, the per-origin
queue, idle expiry and PING timer. Fitted to upstream's new fetch internals:

- **Spare connections** (`tv_fc_spare`, opened by the helper thread for JavaScript hosts): not made for an
  origin with `maxConnections` or `http2` set, since a spare is neither counted against the cap nor HTTP/2.
  The idle-reuse loop moved into `tv_fr_place` and still tops the pool up as upstream's did.
- **io_uring**: an HTTP/2 connection never enters a ring (rings are entered in `tv_fr_send`, which HTTP/2
  streams do not go through), so `h2.c`'s flush and read stay on the event queue.
- `tv_fc_close` keeps upstream's early return for a spare still being dialled, then does the pool accounting.

`PoolOptions` fields stay `int` (not upstream's newer `number` convention): a caller's own record type with
`int` fields, as the Raiju test declares, would no longer be assignable otherwise.
Files: `runtime/tov.c`, `tov.h`, `h2.c`, `tls.c`, `node.c`, `vendor/nghttp2`, `crates/tov/build.rs`,
`tls_flags.rs` (one more library and three include directories: expect a trivial conflict with s3's WAMR
entries in the same two lists), `builtins.rs`, `std/http.tov`, `docs/spec.md`.
Tests: `fetch_pool.tov` with `h2_server.py` 23/23 (also with `TOV_URING=1`, and with `-DTV_PLAIN_ALLOC`).
API unchanged.

## 0008 — request body streams, fetch half — PORT

On top of s1's server half: s1's placeholder in `fetch()` (a stream body threw `ERR_NOT_IMPLEMENTED`) is
replaced by the patch's `sendBody` pump; `fetchWrite`/`fetchEnd`, the request-writer fields, the replay
buffer, the early-answer handling and the HTTP/2 data provider (`h2.c` `resume`, `read_body`) are the
patch's. Fitted to upstream:

- A request with a streamed body is **never written through an io_uring ring** (a ring send has no
  backpressure and copies the request): `tv_fr_send` does not move its connection onto a ring, and
  `tv_fr_place` skips idle connections that are on one (if the pool is at `maxConnections` and all that is
  idle is on rings, one such idle connection is closed to make room).
- A response is not handed to a body thread (`tv_bk_start`) while its request has a streamed body.
- The duplicate-request fix of "Read this first" 3.

Files: `runtime/tov.c`, `tov.h`, `h2.c`, `builtins.rs`, `std/http.tov`.
Tests: `request_body_fetch.tov` 36/36 (HTTP/1.1, TLS, HTTP/2; also with `TOV_URING=1`); `socket_pause.tov`
2/2; s1's `request_body_server` is 19/19 on this branch (18/19 on s1 alone, as its notes say). API unchanged.

## 0013 — fetch address policy (`RequestInit.peer`) — PORT, security control

Ported as patched: classes, allow list, check on **every** resolved address in `tv_fr_connect` right before
the socket is opened, policy in the pool key, `AddressNotAllowed`. Every way fetch reaches a server at
v0.1.0 + these ports, and what covers it:

| Path | Enforcement | Test |
|---|---|---|
| HTTP/1.1, new connection (numeric, `localhost`, resolved name) | `tv_fr_connect` | `peer_policy.tov` |
| next address after a failed connect | same list, all checked before the first attempt | by construction |
| redirect hop | re-dials through `tv_fr_connect` | `peer_policy.tov` |
| pooled idle connection | pool key holds the policy bits and a hash of `allow` | `peer_policy.tov`, `peer_paths.tov` (https) |
| HTTPS | check precedes TLS | `peer_paths.tov` |
| HTTP/2 new connection, `prefer` and `require`; fallback of `prefer` to HTTP/1.1 | `tv_fr_connect` | `peer_paths.tov` |
| HTTP/2 connection already open under no policy / another policy | per-key `h2list` | `peer_paths.tov` |
| streamed request body | same dial | `peer_paths.tov` |
| upstream's spare connections | dialled only to the address of a connection of the same pool key, which passed | by construction; not exercised (JavaScript hosts only, and they pass no policy) |
| io_uring, body threads | act on connections already made | n/a |
| proxy (`proxy:` or `HTTP_PROXY`/`HTTPS_PROXY`), address or `localhost` in the URL | **new: checked, before the proxy is contacted** | `peer_paths.tov` (with the `proxy:` option; the environment variables take the same branch, not run) |
| proxy, host *name* in the URL | **not checked** (the proxy resolves it), as in the patch | `peer_paths.tov` records it |
| `unix:` socket | not checked, as in the patch | - |
| `node:http`'s fetch (JavaScript) | passes no policy, as in the patch | - |

**Behaviour change (tightening).** The patch checked nothing through a proxy. Now a literal address or
`localhost` in the URL is judged by the policy even through a proxy. A Raiju deployment that sets a proxy
*and* a `peer` policy *and* fetches literal private addresses must list them in `allow` (or set
`private`/`loopback`), exactly as it must without the proxy. **Still open, unchanged from the patch:** with
a proxy in the environment, a request by host name is outside the policy; Raiju has to keep its own
resolution check for that case or not use a proxy for user-chosen URLs.

Files: `runtime/tov.c`, `tov.h`, `node.c`, `builtins.rs`, `std/http.tov`, `docs/spec.md`.
Tests: `peer_policy.tov` 21/21 (Raiju's, unchanged); `peer_paths.tov` 24/24 (new: https, HTTP/2, streamed
body, proxy). Both need `PEER_NAME` (a name `/etc/hosts` maps to 127.0.0.1; `runsc` in the container).
API unchanged otherwise.

## 0022 — address policy on `Bun.connect` and `WebSocket` — PORT, security control

The policy part, as patched (`netPeer`, shared `tv_peer_refuses`, check in `tv_ns_resolved`, which every
TCP connect of `net.c` passes through: numeric host, cached name, fresh lookup; the WebSocket client
connects through the same socket and starts in a microtask). The write-stall limit is s1's commit; its
test passes here (5/5). Unix sockets and spawned sockets are not checked (no address).
Files: `runtime/net.c`, `tov.c`, `tov.h`, `builtins.rs`, `std/http.tov`, `docs/spec.md`.
Tests: `socket_peer.tov` 16/16 (Raiju's); `socket_peer_tls.tov` 7/7 (new: `Bun.connect` with `tls`, refused
before any handshake; `wss:`). API unchanged.

## 0015 — client certificates, `Request.signal`, `gunzipSync`/`inflateSync` — PORT

None of the three is in upstream's native layer (gunzip is there only for JavaScript programs, as
`node:zlib` on `runtime/compress.c`; std/http has no `Bun.gunzipSync`; upstream has the runtime half of `req.signal`, `tv_http_on_gone`, and no Tov side).
All ported as patched, `req.signal` included as the coordinator asked (it sits next to s1's 0017 fields in
`Request`). Adapted: array representation in `decompress`, closure type in `httpOnGone`.
Files: `runtime/tls.c`, `tov.c`, `net.c`, `ws.c`, `node.c`, `tov.h`, `builtins.rs`, `codegen/mod.rs`,
`std/http.tov`, `docs/spec.md`.
Tests (not in Raiju's `run.sh`, although its README says so; sections written here): `client_cert.tov`
with `client_cert_server.py` 8/8; `server_gone.tov` with `server_gone_client.py` 4/4; `decompress.tov` 8/8.
API unchanged. Not covered, as in the patch: encrypted keys, a client certificate on `WebSocket`.

## 0016 — fetch input buffer — PORT (adapted)

Upstream now takes the first input buffer (64 KB) from a small cache of recycled buffers. Ported to keep
both intents: the buffer starts at 16 KB and a read wants 4 KB of room; when doubling reaches 64 KB the
buffer is taken from upstream's cache, and a pooled connection keeps at most 16 KB. Files: `runtime/tov.c`.
Test `fetch_buffer.tov` with `fetch_buffer_server.py`: 3/3. **Not measured:** the 48 KB per open stream the
patch saved in Raiju was not re-measured on this tree, nor was upstream's small-fetch benchmark.

## Tests

`raiju-tests/run-s2.sh [section ...]` (sections `spawn alpn udp pool peer cert decompress buffer pause`)
with the compiler of this tree, in the build container:

| Check | Result |
|---|---|
| Bun.spawnSocket (0002) | 1/1 |
| Socket ALPN (0003) | 3/3 |
| Bun.udpSocket (0004) | 8/8 |
| node:dgram (0004) | 8/8 (engine caveat above) |
| fetch pool options and HTTP/2 (0007) | 23/23 |
| fetch with a ReadableStream body (0008) | 36/36 |
| fetch address policy, Raiju's test (0013) | 21/21 |
| fetch address policy on HTTPS, HTTP/2, streams, proxies (0013) | 24/24 |
| Bun.connect and WebSocket address policy (0022) | 16/16 |
| Bun.connect (TLS) and wss: address policy (0022) | 7/7 |
| Socket.pause (0008) | 2/2 |
| TLS client certificates (0015) | 8/8 |
| Request.signal on Bun.serve (0015) | 4/4 |
| gunzipSync / inflateSync (0015) | 8/8 |
| fetch input buffer (0016) | 3/3 |

The same, built with `TOV_CFLAGS=-DTV_PLAIN_ALLOC` as Raiju builds (all but `udp`, not rerun): all pass.
`valgrind` on `peer_policy`, `socket_peer`, `decompress`, `udp`, `spawn_socket` (plain allocator): no errors.
s1's `raiju-tests/run.sh` on this branch (system-JSC image): all sections pass.
Changes to the copied Raiju tests: `parseInt(x) ?? 0` rewritten in `alpn.tov` and `client_cert.tov`;
nothing else, and no expected count was lowered.

Upstream suites on this branch (proxy variables unset): `--test fetch` 5 programs, 0 failed (8 of 8 runs
idle; under CPU load it flakes as unmodified v0.1.0 does, see "Read this first" 3); `--test http` 0 failed;
`--test async` 12, 0 failed; `--test ui` 25 cases, 0 failed; `--test cli` 5 passed; `--test robustness` no
panics; `--test run` 375 programs, 0 failed (system JSC image; 10 engine failures in the stock container, as
s1 lists); `runtime/test.sh` all passed. `--test npm` (system JSC image): 41 programs, 6 failed, none in
code touched here as far as the output shows: all six stop at binding `::` or `::1` (this sandbox has no
IPv6: `bun_content_type`, `bun_serve`, `client_gone`, `js_callback`, `node_http`, `node_net`); in one of two
runs `node_child_process` also differed in one line (`maxBuffer null ENOBUFS`). **Not compared against unmodified
v0.1.0** for `npm`, so "environmental" is my reading of the errors, not a measured baseline.

## Open and unverified (s2)

- Linux x86-64 only. The macOS/kqueue branches of the ported code (0002's `FD_CLOEXEC` path, 0004, the
  h2 flush) were not compiled.
- io_uring: exercised only by forcing `TOV_URING=1` on the 0007/0008/fetch tests. Not exercised: a
  streamed-body request arriving when every idle connection of a capped pool is on a ring (the "close one
  to make room" branch).
- HTTP/2 against real servers, and a proxy that actually tunnels (the proxy tests use a counting listener),
  were not tried; Raiju's e2e covers those.
- The address policy does not cover host names sent through a proxy (above). This is the one place where
  a `peer` policy can be bypassed by configuration (`HTTP_PROXY`/`HTTPS_PROXY` in the environment).
- The TLS failure reported as `ConnectionRefused` (upstream race, above) is not fixed.
- 0016's memory saving and any fetch throughput change from 0007/0016 were not benchmarked.
