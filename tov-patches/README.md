# Tov patches

Raiju builds against [Tov](https://github.com/richiemcilroy/Tov) at commit
`c2048582de4e9468267f801313144d75c12e983f` plus the patches here, applied in
order by `scripts/build-tov.sh` (`make tov`). Each patch is written to be offered
upstream. `tests/run.sh` checks all of them with the patched compiler:
`TOV=build/tov/target/release/tov tov-patches/tests/run.sh` (or `make tov-test`).
Patch 0004 is written on top of 0003 (its hunks include the ALPN signatures), so the
patches apply in order only. Patches 0005 (WAMR) and 0006 (libdatachannel) add vendored C
libraries (about 2.7 MB and 4.9 MB of text), which the first four do not; 0006 is applied on top of 0005.
Patch 0008 changes the fetch and HTTP/2 code that 0007 adds, so it is applied on top of 0007.
Patch 0009 (node:fs rename and fsync) touches the shared lists in `builtins.rs` and `tov.h` and is written on top of 0001-0008.
Patch 0010 (WebAssembly wall-clock limit) changes `std/wasm`, `runtime/wasm.c` and the WAMR interpreter that 0005 adds, and is written on top of 0001-0009.
Patch 0012 (server lifecycle) changes the HTTP server in `runtime/tov.c` and `std/http.tov`, and is written on top of 0001-0010.
Patch 0013 (fetch address policy) changes the fetch code in `runtime/tov.c` and `std/http.tov` (and `fetchStart`'s signature, also called from `runtime/node.c`), and is written on top of 0001-0012.
Patch 0015 (client certificates, `Request.signal`, gunzip) changes fetch, sockets and the server (and `fetchStart`'s and `netConnect`'s signatures), and is written on top of 0001-0013.
Patch 0016 (fetch input buffer) changes the fetch connection reads in `runtime/tov.c` and is written on top of 0001-0013 and 0015.
Patch 0017 (`server.requestIP`) changes the HTTP server in `runtime/tov.c` and `Request`/`Server` in `std/http.tov`, and is written on top of 0001-0016.
Patch 0019 (worker respawn) changes the worker supervisor in `runtime/tov.c` and is written on top of 0001-0017 (its `docs/spec.md` hunk is on the line 0017 changes).

## Submitting upstream

Tov (MIT) takes outside pull requests; its rules are in its `AGENTS.md`: no mention of
coding agents anywhere, and no attribution trailers in commits or pull requests. The
upstream-ready versions are in [upstream/](upstream/): one `git format-patch` commit per
pull request, in Tov's `feat: ...` style with tests in Tov's own harness (`tests/http.rs`,
`tests/run/`) and docs in `docs/spec.md`, plus the pull request descriptions. Apply with
`git am` on a fork at the pinned commit and open the PRs from there. Checked with
`cargo test --release --test http` (passes) and `--test run` (passes except
`npm_const_throws`, which fails the same way on unpatched Tov without JavaScriptCore).

## 0001 — streamed response bodies for `Bun.serve`

**Problem.** `Bun.serve` answers with a complete body only. A handler can't send
server-sent events or any other incremental output, so an LLM gateway either
buffers whole answers or runs its own HTTP server on `Bun.listen`, which can't
use `workers: n`. A listener opened before the fork can't be shared.

**API (as in Bun and the web platform).**

```ts
const body = new ReadableStream({
  start(controller) {        // controller.enqueue(u8[] | string), close(), error(e)
    controller.enqueue("data: hi\n\n")
    controller.close()
  },
  cancel() {},               // the client went away
})
return new Response(body, { headers: { "content-type": "text/event-stream" } })
```

**Design.**
- `ReadableStream` gets an optional underlying source. Pushed chunks queue in
  the stream, and `pull()` waits on a promise that the next `enqueue` or `close`
  resolves. `ReadableStreamDefaultController` is a new global.
- `Response` accepts a `ReadableStream` body. `text()` and `bytes()` drain it.
- When a handler's response has a pushed stream, `Bun.serve` defers the request
  (`httpDefer`). It then writes the head with `transfer-encoding: chunked`
  (`httpStreamStart`) and each chunk as it is enqueued (`httpStreamWrite`), and
  ends with the zero chunk.
- Both natives are about 30 lines of C on the runtime's existing
  `tv_native_httpWriteRaw`, which Node compatibility already used. Sending
  therefore stays on the worker's own connection and works in every forked
  worker.
- A client that disconnects (`httpBuffered < 0`) cancels the stream and runs the
  source's `cancel`. A source that fails after the head went out closes the connection
  without the last chunk (`httpStreamAbort`), so the client sees a cut-off body.

**Files.**
- `runtime/tov.c`, `runtime/tov.h`: `httpStreamStart`, `httpStreamWrite`.
- `crates/tov/src/check/builtins.rs`: the natives' signatures.
- `crates/tov/src/std/http.tov`: the stream source and controller, the stream
  body, and pumping in `serve` and `respondLater`.
- `crates/tov/src/driver.rs`: the controller global.

**Measured in Raiju.** Chunks reach the client as they are produced (e2e: a
150 ms-per-event upstream arrives spread out). With 2 workers, the gateway
serves 31–36k rps against 16k for one process on the same 4-core VM.

## 0002 — child processes as sockets (`Bun.spawnSocket`)

**Problem.** Tov can't start processes, so a program can't talk to tools that
run as children. MCP's stdio transport is one example: newline-delimited
JSON-RPC on a child's stdin and stdout.

**API (Tov-specific; Bun's `Bun.spawn` has a different, stream-based shape).**

```ts
const sock = await Bun.spawnSocket({
  cmd: ["python3", "server.py"],
  env: { API_KEY: "..." },   // added to the inherited environment
  cwd: "/srv",
  socket: { data(s, bytes) {}, close(s) {} },   // the usual SocketHandler
})
sock.write("request\n")       // to the child's stdin
```

**Design.**
- `netSpawn(argv, env, cwd)` makes a `socketpair(AF_UNIX)`, forks and execs
  with the child's stdin and stdout on one end, and gives the other end to the
  existing socket table as an already-open socket. Reads, writes, backpressure,
  `end()` and close events then come from the code that serves TCP and Unix
  sockets.
- The child gets `PR_SET_PDEATHSIG(SIGTERM)` on Linux, so it dies with its
  parent (a `Bun.serve` worker, say). Exited children are reaped with
  `waitpid(pid, WNOHANG)` for the spawned pids only, so other code that waits for its
  own children is unaffected.
- stderr is inherited. A missing executable prints to stderr and shows up as
  the socket closing.

**Files.**
- `runtime/net.c`, `runtime/tov.h`: `netSpawn`, and opening a spawned socket in
  `tv_ns_start`.
- `crates/tov/src/check/builtins.rs`: the signature.
- `crates/tov/src/std/http.tov`: `SpawnSocketOptions` and `Bun.spawnSocket`.

**Not covered.** There is no exit status, no
separate stderr pipe and no Windows support. A Bun-compatible `Bun.spawn` with
`stdout: "pipe"` could be built on the same native later.

## 0003 — TLS ALPN on client sockets (`tls.alpn`)

**Problem.** A TLS client couldn't offer application protocols, so it couldn't ask a server for
HTTP/2. gRPC over TLS needs `h2` in ALPN, so an OTLP exporter could only send to a plaintext
collector (h2c). Tov's `fetch` is HTTP/1.1 only, so the gRPC client runs on a raw socket.

**API (Bun's, on `Bun.connect`).**

```ts
const s = try await Bun.connect({
  hostname: "collector",
  port: 4317,
  tls: { alpn: ["h2"], rejectUnauthorized: true, ca: pem },
  socket: {},
})
if (s.alpnProtocol !== "h2") s.terminate()   // "" when the server picked none
```

**Design.**
- `tls.alpn` is the list of protocols offered (`SSL_set_alpn_protos`, as a length-prefixed list).
  Without it the TLS context keeps its default, as before. Resumed sessions are keyed by the list
  too, so a session from one offer is not reused for another.
- `socket.alpnProtocol` reads `SSL_get0_alpn_selected` once the handshake is done. It is `""` for
  plaintext sockets, for no offer, and when the server picks nothing.

**Files.**
- `runtime/tls.c`, `runtime/tov.h`: the offer, the protocol read, and the `alpn` slot in the TLS ops.
- `runtime/net.c`, `runtime/tov.c`, `runtime/ws.c`: `netConnect` takes the offer; `netAlpn` reads it.
- `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`: the signatures, `SocketTLSOptions.alpn`,
  and `Socket.alpnProtocol`.

**Not covered.** Tov's listeners don't pick a protocol (a TLS server can't offer ALPN), so the
test checks the offer and the empty answer; a server that picks is in the Raiju e2e only.

## 0004 — UDP sockets (`Bun.udpSocket` and `node:dgram`)

**Problem.** Tov had no datagram sockets, so `node:dgram` was a stub. Cluster discovery by UDP
broadcast and by mDNS, and any UDP protocol, were out of reach.

**API (Tov, as in Bun's `Bun.udpSocket`).**

```ts
const sock = await Bun.udpSocket({
  hostname: "0.0.0.0",
  port: 9999,
  broadcast: true,
  reusePort: true,            // several sockets may share the port (multicast listeners)
  socket: {
    data(s, bytes, port, address) {   // u8[], the sender's port and address
      s.send("ack", port, address)
    },
  },
})
sock.send("hello", 9999, "255.255.255.255")
sock.addMembership("239.255.42.99")
```

`send` takes text or bytes and returns whether the datagram went (a full kernel buffer is not
retried). `setBroadcast`, `setTTL`, `setMulticastTTL`, `setMulticastLoopback`, `setMulticastInterface`,
`addMembership`, `dropMembership`, `hostname`, `port`, `ref`, `unref` and `close` are as in Bun.

**Design.**
- A socket is a table entry on the same loop as TCP and Unix sockets (`runtime/net.c`), so it
  runs with no thread and keeps the program alive while it reads, unless it is unref'd.
- `node:dgram` runs on the same natives: `runtime/node/internal/bindings/udp_wrap.js` replaces its
  stub with bind, send (with the connected form), membership, options, names and close, and
  `runtime/node.c` adds the natives it calls.
- A datagram that arrives is delivered whole, with the sender's address and port. Failures are
  `-errno` numbers in the natives and a `SocketError` (`ERR_SOCKET`, `ERR_SOCKET_BIND`) from the API.

**Files.**
- `runtime/net.c`, `runtime/tov.h`: the UDP table and natives.
- `runtime/node.c`, `runtime/node/internal/bindings/udp_wrap.js`: `node:dgram`.
- `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`: the signatures and `Bun.udpSocket`.

**Not covered.** No source-specific multicast (IGMPv3), no `connect` on the Tov API (send takes
the address), and no `dgram` buffer sizes beyond the kernel's limits. `node:dgram` tests run
through `tov-patches/tests/udp_dgram.tov`.

## 0005 — WebAssembly modules (`std/wasm`, on WAMR)

**Problem.** Tov could not run WebAssembly. Bifrost's dynamic plugins are WebAssembly modules
(its Go shared-object plugins are out of reach for a native Tov binary), and the only route to a
WebAssembly engine was linking JavaScriptCore into the gateway (about 34 MB). This adds a small
interpreter, [WAMR](https://github.com/bytecodealliance/wasm-micro-runtime), to the runtime
build, behind a Tov module.

**API (Tov, `import { instantiate } from "std/wasm"`).**

```ts
const m = instantiate(bytes, { fuel: 5_000_000, stackBytes: 65536, maxPages: 256 })
m.has("add")                       // an export of that name
m.arity("add")                     // its parameter count, -1 when there is none
m.call("add", [40, 2])             // i32 and i64 arguments as int; the first result as int (42)
m.write(ptr, bytes)                // linear memory, by offset (u8[])
const out = m.read(ptr, len)       // throws when the range is outside memory
m.memorySize()                     // bytes
m.output()                         // what the module wrote to standard output and error (64 KiB at most)
m.close()
```

A trap, a missing export, a wrong argument count or a bad offset throws an `Error` with WAMR's
message. A trapped instance keeps the state it had at the
trap (a module's own stack pointer is not restored), so a host that wants to go on replaces it
with a new instance, as `src/wasmplugin.tov` does.

**Limits per instance.**
- `maxPages`: the most 64 KiB pages of linear memory (default 256). A module whose initial memory
  is above it is refused; `memory.grow` past it returns -1.
- `stackBytes`: the operand stack (default 64 KiB). Past it a call traps.
- `fuel`: the most instructions one call may run (WAMR's instruction metering; default none, at
  most 2^31 - 1). A call past it traps with "instruction limit exceeded". There is no wall-clock
  limit: a call runs on the thread that made it until it returns, traps or runs out of fuel.

**What a module can reach.** Nothing but its own memory and a WASI subset written for this
patch (runtime/wasm.c): `fd_write` to fd 1 and 2 (captured, read back with `output()`),
`fd_read` of an empty stdin, `clock_time_get`, `clock_res_get`, `random_get`, an empty
environment and argument list, `sched_yield`, `proc_exit` (a trap) and refusals (`EBADF`,
`ENOSYS`) for files and polling; and `env.abort`, which AssemblyScript imports. No files, no
sockets, no processes. An import outside that set does not stop the module from loading; calling
it traps.

**Design.**
- WAMR 2.4.5 (`WAMR-2.4.5`, commit `25bd7eb6`, Apache-2.0 with LLVM exception; `vendor/wamr/LICENSE`)
  is vendored under `vendor/wamr`: the fast interpreter, the loader, the runtime, the `ems`
  allocator files and the POSIX platform layer, with its headers (2.7 MB; AOT, JIT, WASI libc,
  threads, SIMD and GC code is not included). It is built with explicit bounds checks
  (`WASM_DISABLE_HW_BOUND_CHECK=1`): no signal handlers and no 8 GiB address reservation per
  memory. Flags are in `crates/tov/src/tls_flags.rs`.
- It is built like BoringSSL: into the vendored archive the compiler carries, linked only into
  programs that call the natives, which `codegen` finds by the `tv_native_wasm` prefix.
  `runtime/wasm.c` is one more file of the TLS library's runtime archive.
- Platforms: Linux on x86-64 and AArch64. Elsewhere `runtime/wasm.c` is compiled as stubs
  (`TV_NO_WASM`) that report "WebAssembly is not supported on this platform", and WAMR is left
  out of the vendored archive, so other targets build as before.
- Instances live in a table of handles (`wasmLoad` returns one; at most 1024 at once).

**Files.**
- `vendor/wamr/**`: WAMR 2.4.5 (the subset above).
- `runtime/wasm.c`, `runtime/tov.h`: the natives `wasmLoad`, `wasmHas`, `wasmArity`, `wasmCall`,
  `wasmRead`, `wasmWrite`, `wasmMemSize`, `wasmOutput`, `wasmFree`, `wasmError`, and the WASI subset.
- `crates/tov/src/std/wasm.tov`, `crates/tov/src/driver.rs`, `crates/tov/src/check/builtins.rs`:
  the `std/wasm` module and the native signatures.
- `crates/tov/src/codegen/mod.rs`: a program that uses the natives links the TLS library's archives.
- `crates/tov/build.rs`, `crates/tov/src/tls_flags.rs`: WAMR's sources and flags, and the platform filter.

**Not covered.** Only the interpreter (no AOT or JIT, so no speed beyond an interpreter's), no
WASI file or socket access, no threads, no SIMD, no floating-point arguments in `call`, no
imports a host function could provide (a module is linked against the fixed set above),
no multi-memory, and one memory read or written by offset, not mapped into Tov. The test is
`tov-patches/tests/wasm.tov`, run against `wasm_mod.wasm` (source `wasm_mod.c`).

## 0006 — WebRTC (`std/rtc`, on libdatachannel)

**Problem.** Tov had no WebRTC, so a program could not be a peer: it could not answer a browser's SDP offer,
open a data channel, or carry audio. An LLM gateway that terminates a browser's WebRTC session (to meter, guard
and log its events, as Bifrost does with Pion) needs all three.

**API (`import { RTCPeerConnection } from "std/rtc"`; callbacks, like the browser's, on Tov's event loop).**

```ts
const pc = new RTCPeerConnection({ iceServers: ["stun:stun.example.test:3478"], bindAddress: "127.0.0.1" })
pc.ondatachannel = (ch) => { ch.onmessage = (m) => ch.send(m) }   // text or bytes
pc.ontrack = (t) => { t.onpacket = (rtp) => other.sendRtp(rtp, ssrc, payloadType) }   // RTP in and out, no decoding
pc.onlocaldescription = (sdp, type) => {}      // the answer to a remote offer is made on its own
pc.ongatheringchange = (s) => { if (s === "complete") reply(pc.localDescription) }   // candidates included
pc.onstatechange = (s) => {}                   // new, connecting, connected, disconnected, failed, closed
pc.setRemoteDescription(offer, "offer")        // "" or the error
pc.addTrack({ codec: "opus", direction: "sendrecv" }); pc.createDataChannel("oai-events")
pc.setLocalDescription()                       // an offer, from the channels and tracks added
pc.close()                                     // frees it, its channels and tracks; its callbacks never fire again
```

`RTCDataChannel` has `send`, `bufferedAmount`, `onopen`, `onmessage`, `onclose`, `onerror`,
`onbufferedamountlow` and `close`; `RTCTrack` has `sendRtp(packet, ssrc?, payloadType?)` (a negative or missing
value keeps the packet's own; otherwise the header is rewritten, which is how a relay puts one leg's packets on
the other's stream), `onpacket`, `payloadType` and `direction`.

**Design.**
- libdatachannel v0.24.6 (MPL-2.0) with its dependencies, vendored under `vendor/rtc/` byte for byte from the
  tags below, minus tests, examples and docs: libjuice (ICE and STUN/TURN, MPL-2.0), usrsctp (SCTP for data
  channels, BSD), libsrtp 2.8.0 (SRTP, BSD) and plog (headers, MIT). `vendor/rtc/srtp/config.h` is the one file
  that is ours (what libsrtp's CMake writes for the OpenSSL backend, by compiler macros). `vendor/rtc/TOV.md`
  lists the commits and the build flags. WebSockets in libdatachannel are compiled out (`RTC_ENABLE_WEBSOCKET=0`).
- The crypto library is the vendored BoringSSL that `fetch()` already links: libdatachannel's OpenSSL backend and
  libsrtp's OpenSSL provider compile and run against it (DTLS 1.2 with the SRTP profiles, X.509 fingerprints),
  so a program carries one TLS library. Programs that use `std/rtc` link it, so they are also fetch programs.
- `runtime/rtc.c` is the bridge (C, over libdatachannel's C API). libdatachannel calls back on threads of its
  own; nothing there touches the Tov runtime. Each callback appends an event to a mutex-protected queue and
  writes a byte to a pipe the event loop watches (`tv_io_add`, `runtime/net.c`); the loop pops the events and
  runs one Tov closure for each: `(kind, id, n, bytes, text)`, which `std/rtc` routes to the objects. A callback
  installs the callbacks of a channel or track the remote side made before it returns, so no event of it is missed.
  RTP packets are dropped (not queued) when 4,096 events wait. A live peer connection keeps the program running.
- The natives are the `rtc*` family in `runtime/net.c` (declared in `tov.h`, signatures in `builtins.rs`); they
  go through a table of operations (`tv_rtc_impl`) that only `rtc.c` fills, so programs without `std/rtc` carry
  none of it. Codegen adds `tv_rtc_install()` to a program that calls `rtcPeer`; `build.rs` then links the rtc
  archive in front of the TLS ones, with `-lstdc++`.
- The archive is compiled the first time a program needs it (about four minutes on four cores at `-O2`), by
  `crates/tov/src/build/rtc.rs` from sources the compiler embeds, as the TLS one is, and cached by their hash,
  the compiler and the flags. Environment: `TOV_RTC_LOG=debug|info|warning|none` sets the library's log level
  (default: errors, to stderr).
- At exit the connections still open are closed (`atexit`), so libdatachannel's threads do not hold the process.

**Files.**
- `runtime/rtc.c`, `runtime/net.c`, `runtime/tov.h`: the bridge, the natives, the operations table.
- `crates/tov/src/std/rtc.tov`, `crates/tov/src/driver.rs`: the module (`std/rtc`) and its registration.
- `crates/tov/src/check/builtins.rs`: the native signatures.
- `crates/tov/src/codegen/mod.rs`, `crates/tov/src/build.rs`, `crates/tov/src/build/rtc.rs`, `crates/tov/build.rs`:
  the install call, the archive and its link.
- `vendor/rtc/`: the libraries.

**Tested.** `tov-patches/tests/rtc.tov` (20 checks): two peers on the loopback address, an offer made from a
track and a channel, the answer made from it, text and bytes both ways, Opus RTP with rewritten SSRC and payload
type, states, the selected candidate pair, close. Raiju's end-to-end tests also run aiortc (Python) as the browser.

**Not covered.** Video (tracks are audio: Opus, PCMU, PCMA), WebSocket and TURN-over-TCP use of the library,
media handlers (packetizers, NACK, bandwidth estimation: RTP passes as it is, with the library's receiver
reports), Windows. The macOS build flags for usrsctp and the C++ link are written from its documentation and
untested. Two Tov compiler faults found on the way, both worked around: `switch` on a string variable releases
the string twice, and a closure that captures a class-typed parameter of the closure around it doesn't compile
(both to report upstream).

## 0007 — fetch pool options and upstream HTTP/2 (`RequestInit.pool`)

**Problem.** `fetch` pooled keep-alive connections with no way to tune them: idle connections
lived until the server closed them, any number of requests opened that many connections to a
host, and every request was HTTP/1.1. An LLM gateway needs a per-provider idle timeout and
connection cap (Bifrost's `keep_alive_timeout_in_seconds` and `max_conns_per_host`), and
HTTP/2 to providers that serve it (`enforce_http2`, `http2_ping_interval_in_seconds`).

**API (Tov; not in Bun).**

```ts
const res = await fetch("https://api.example.com/v1/x", {
  pool: {
    keepAliveTimeout: 30,      // seconds an idle connection is kept for reuse (default: until the server closes it)
    maxConnections: 100,       // connections to the origin at once; more requests wait their turn (default: no limit)
    http2: "prefer",           // "off" (default) | "prefer" | "require"
    http2PingInterval: 10,     // seconds without a frame before a PING is sent (0: none)
  },
})
```

**Design.**
- Requests whose options differ do not share connections: the options are part of the pool
  key, so each provider's settings are its own pool. Requests without `pool` behave as before.
- `maxConnections` counts connections open or being made. A request that cannot start (no idle
  connection, no HTTP/2 connection with room, cap reached) waits in a per-origin FIFO queue
  and starts when a connection goes idle or closes. A waiting request that is aborted leaves
  the queue.
- `keepAliveTimeout` stamps a connection when it goes idle and closes it once the stamp is
  that old (checked when the connection is picked for a request, and by one timer that does
  not keep the program running).
- `http2: "prefer"` offers `h2` then `http/1.1` in the TLS handshake (patch 0003's ALPN). A server
  that picks `h2` gets one connection with many request streams (concurrent requests wait for
  the first connection's answer instead of each opening one); one that does not gets
  HTTP/1.1, as Go's `ForceAttemptHTTP2` does. `"require"` offers only `h2` and fails the
  request with code `HTTP2NotNegotiated` otherwise. Plain `http:` URLs are always HTTP/1.1
  (no h2c).
- The framing is [nghttp2](https://nghttp2.org) 1.64.0 (MIT), vendored in `vendor/nghttp2`
  (see its `TOV.md`) and compiled with the other TLS-side libraries. `runtime/h2.c` is a thin
  layer over it; `runtime/tov.c` keeps the sockets, TLS and request objects. The request head is
  the same HTTP/1.1 head `fetch` always builds, turned into pseudo-headers and headers; the
  response head is turned back into an HTTP/1.1 head and parsed by the existing parser, so
  content decoding, redirects, `res.body` streaming and abort behave as they do on HTTP/1.1.
- Flow control follows the reader: body bytes are returned to the stream's window only once the
  reader has room (the same 256 KiB mark that pauses an HTTP/1.1 socket), so a slow reader holds
  its own stream and not the connection's others. Windows are 1 MiB per stream and 16 MiB for the
  connection.
- With `http2PingInterval`, a connection that has received no frame for that long sends a
  PING; one that is not answered within 15 seconds is closed and its requests fail (or, if
  nothing of theirs was answered and the connection had served requests before, are retried).
  GOAWAY and REFUSED_STREAM retry requests the server did not process on another connection.
- An aborted request cancels its stream (RST_STREAM) and leaves the connection open.

**Files.**
- `runtime/tov.c`, `runtime/tov.h`: the pool (origin queue, limits, timer), the HTTP/2 connections,
  and `fetchStart`'s four new arguments.
- `runtime/h2.c`: the nghttp2 layer; `runtime/tls.c` installs it with the TLS library.
- `vendor/nghttp2`, `crates/tov/build.rs`, `crates/tov/src/tls_flags.rs`: the library and how it is built.
- `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`: the signature and `PoolOptions`.

**Not covered.** No h2c (plain-text HTTP/2), no server push (disabled), no HTTP/2 priorities,
no `Upgrade`/WebSocket over HTTP/2. HTTP/2 over a proxy works through `CONNECT` like HTTPS does.
Limits are per process: a `Bun.serve` with `workers: n` has a pool per worker. The tests
(`tests/fetch_pool.tov`, driven by `tests/h2_server.py`) need Python's `h2` package; `run.sh`
installs it to a temporary directory if it is missing and skips the HTTP/2 and pool checks
if it cannot.


## 0008 — request body streams (`fetch` with a `ReadableStream` body, `req.body` in `Bun.serve`)

**Problem.** Neither end of an HTTP request could stream its body. `fetch` took a string or bytes, and
`Bun.serve` held a request whole (up to 64 MiB) before calling the handler, so a gateway could not pass
a large body to a provider without holding it. Bifrost's `large_payload_optimization` reads the routing
fields from the first bytes of a big request and streams the rest through.

**API (Bun's, plus two options and `Socket.pause()` / `resume()`).**

```ts
// fetch: a ReadableStream body is sent as it is read, chunked on HTTP/1.1 and as DATA frames on HTTP/2
const body = new ReadableStream({
  async pull(c) {                      // new: called when a reader wants a chunk and none is queued
    c.enqueue(await nextChunk())       // c.enqueue(u8[] | string), c.close(), c.error(e)
  },
})
const res = await fetch(url, { method: "POST", body, headers: { "content-length": "123" } })  // length optional

// Bun.serve: a body over the threshold reaches the handler before it has arrived
Bun.serve({
  bodyStreamThreshold: 262144,         // bytes (Content-Length, or what a chunked body has sent so far)
  maxRequestBodySize: 1 << 30,         // bytes; a declared length over it is a 413, a chunked body past it fails its stream
  async fetch(req) {
    for await (const chunk of req.body!) { /* u8[] */ }
    // or req.text(), req.json(), req.bytes()...: they read the stream whole
  },
})
```

`Request.body` is a `ReadableStream | undefined` (the stream of a body that came whole is one chunk).
`Socket.pause()` / `resume()` stop and restart reading a socket (Node's pair).

**Design.**
- `fetch` (runtime/tov.c). A stream body is flagged to `fetchStart`; the Tov side then pumps it:
  `fetchWrite(id, bytes)` appends the next chunk and returns a promise that settles once the chunk is
  on the wire (HTTP/1.1: written to the socket, framed as a chunk unless the caller gave a
  `Content-Length`; HTTP/2: handed to nghttp2 by a deferred data provider, which waits for the
  stream's window), so at most one chunk waits in memory and a slow server slows the source. A
  negative result means the request is over (the response came first, it failed or was aborted) and
  the pump cancels the source. `fetchEnd` ends the body. A source that fails aborts the request.
- The request cannot be repeated, so a 307 or 308 answer is returned instead of followed, and a
  request that fails on a reused connection is retried only while everything sent is still held: the
  first 1 MiB of the body is kept for that, then dropped. A server that answers early and closes
  (an HTTP/1.1 413, say) has its answer read: a write failure switches the request to reading.
- `Bun.serve` (runtime/tov.c, tv_http_bs). A body over `bodyStreamThreshold` is handed to the handler
  as soon as its head is in; the connection's later bytes feed the stream (Content-Length or an
  incremental chunked decoder, with trailers) while `httpBodyRead`/`httpBodyTake` give them to
  the handler. Once 512 KiB are held the socket is not read until the handler takes them, so a slow
  handler slows the sender. A body nobody reads is dropped when the request is answered (at most
  32 MiB further; past that the connection closes), and the connection serves its next request. A
  client that leaves or half-closes fails the stream. `text()`, `json()` and the others read it whole.
  `Expect: 100-continue` is answered for a streamed body. Cancelling a body that is all in frees its
  stream at once (`httpBodyCancel` keeps the connection it marks for reading, not the stream).
- `Socket.pause()` (runtime/net.c) takes the socket off the read interest; `src/http1.tov` uses it for
  the same backpressure on raw sockets.

**Files.**
- `runtime/tov.c`, `runtime/tov.h`: the request writer (`fetchWrite`, `fetchEnd`), the server-side body
  stream (`httpBodyOptions`, `httpBodyStream`, `httpBodyRead`, `httpBodyTake`, `httpBodyCancel`).
- `runtime/h2.c`: the streaming data provider and `resume`.
- `runtime/net.c`: `netPause`.
- `crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov`: the signatures, `RequestInit.body`,
  `UnderlyingSource.pull`, `Request.body`, `ServeOptions`, `Socket.pause`.

**Not covered.** A stream body cannot be sent through a redirect that keeps the method, and after
1 MiB a failed request is not retried. A TLS HTTP/1.1 server that answers early and resets the
connection may cost the answer (HTTP/1.1 over plain TCP and HTTP/2 return it). The worker processes
of `workers: n` each hold their own streams. `Request.body` of a request read with `text()` first is
the empty stream. The tests (`tests/request_body_server.tov` with `request_body_client.py`,
`request_body_fetch.tov` against `h2_server.py`, `socket_pause.tov`) are in `run.sh`.

## 0009 — `node:fs` rename, descriptors and fsync (`renameSync`, `openSync`, `fsyncSync`)

**Problem.** Tov's `node:fs` could write a file only in place (`writeFileSync` truncates, then writes),
and had no `rename` or `fsync`. A program that rewrites a state file (a gateway's config.json) leaves a
truncated or half-written file when it dies mid-write, and another process reading at that moment sees
the same. The usual cure, a temporary file renamed over the target, needs rename and fsync.

**API (Node's).**

```ts
import { renameSync, rename, openSync, writeSync, fsyncSync, fdatasyncSync, closeSync, chmodSync, writeFileSync, statSync } from "node:fs"

writeFileSync(dir + "/.config.json.tmp", text, { mode: 0o600, flush: true })  // new options: mode of a created file, fsync before returning
renameSync(dir + "/.config.json.tmp", dir + "/config.json")   // POSIX rename: replaces the target in one step
const fd = openSync(dir, "r")                                  // "r" opens a directory too
fsyncSync(fd)                                                  // the rename itself survives a power cut
closeSync(fd)

const f = openSync(path, "wx", 0o644)  // flags r, r+, w, wx, w+, wx+, a, ax, a+, ax+
writeSync(f, "text or bytes")          // writes all of it; returns the bytes written
fdatasyncSync(f)
closeSync(f)
rename(a, b, (err) => {})              // the callback form (runs as a microtask)
chmodSync(path, 0o600)
statSync(path).mode                    // st_mode: type and permission bits
```

Errors carry Node's messages: `ENOENT: no such file or directory, rename 'a' -> 'b'`,
`EBADF: bad file descriptor, fsync`, `EEXIST: file already exists, open 'x'`.

**Design.** New natives in `runtime/tov.c` (`rename`, `chmod`, `open`, `writeFd`, `fsync`, `close`):
`open` maps Node's flag strings to `open(2)` flags with `O_CLOEXEC` (an unknown string is EINVAL),
`writeFd` retries short writes and EINTR, `fsync` takes a data-only flag for `fdatasync` and uses
`F_FULLFSYNC` on macOS (where plain fsync stops at the drive cache). `writeFileSync` keeps its old path
(`fopen`) when no option is given, and goes through `open`/`write`/`fsync`/`close` when `mode` or
`flush` is. The `statSync` payload gains `st_mode`. The error table learns EBADF, EXDEV and EINVAL.

**Files.**
- `runtime/tov.c`, `runtime/tov.h`: the natives, two-path and descriptor error messages, `st_mode` in `statInfo`.
- `crates/tov/src/check/builtins.rs`: the signatures.
- `crates/tov/src/std/fs.tov`: `renameSync`, `rename`, `chmodSync`, `openSync`, `writeSync`, `fsyncSync`,
  `fdatasyncSync`, `closeSync`, `writeFileSync`'s options, `Stats.mode`.
- `docs/spec.md`: the `node:fs` line.

**Not covered.** POSIX only, as the rest of Tov's file API (Windows' rename does not replace an existing
file). No `fs.promises`, no `readSync`/positioned writes, no `encoding` or `flag` options on
`writeFileSync`. The test (`tests/fs_atomic.tov`, 17 checks) is in `run.sh`.

## 0010 — a wall-clock limit per WebAssembly call (`std/wasm` `timeMs`)

**Problem.** 0005 bounds a call by its instruction count (`fuel`), but a call that is slow for another
reason (a budget set high, a host import that takes long) still holds the thread. A gateway that runs
plugin hooks on its request path needs a time bound per call as well.

**API.**

```ts
import { instantiate } from "std/wasm"

const m = instantiate(bytes, { fuel: 200000000, timeMs: 5000 })  // the most wall-clock ms one call may take
m.setTimeLimit(250)                                              // changes it later (0: no limit)
m.call("pre_hook", [ptr, len])  // past the limit it throws "time limit exceeded", as a call out of fuel does
```

**Design.** `runtime/wasm.c` keeps the deadline of the call in progress (CLOCK_MONOTONIC nanoseconds) in a
global around `wasm_runtime_call_wasm_a`; a nested call keeps the earlier deadline. WAMR's fast
interpreter runs `CHECK_INSTRUCTION_LIMIT` on every instruction when instruction metering is on (0005
turns it on); the macro now also counts a tick and, every 65536 instructions, compares the clock with the
deadline and raises "time limit exceeded". With no deadline set the added cost is one compare. The limit
is capped at one day.

**Files.**
- `runtime/wasm.c`, `runtime/tov.h`: the deadline, `tv_wasm_now_ns`, the `wasmTimeLimit` native (and its stub
  when WAMR is not built).
- `vendor/wamr/core/iwasm/interpreter/wasm_interp_fast.c`: the clock check in `CHECK_INSTRUCTION_LIMIT`.
- `crates/tov/src/check/builtins.rs`: the signature.
- `crates/tov/src/std/wasm.tov`: `WasmLimits.timeMs`, `WasmInstance.setTimeLimit`.

**Not covered.** The clock is read only between instructions, so one host call that blocks is not cut
short (the call ends at the next check after it returns). Only the fast interpreter is built, so only it
has the check. The test (2 more checks in `tests/wasm.tov`, 24 in all) is in `run.sh`.

## 0012 — server lifecycle: stop signals, request timeouts, a connection cap (`Bun.serve`)

(Numbered 0012: 0011 is kept for the patch written alongside it. 0012 is written on top of 0001-0010.)

**Problem.** A program on `Bun.serve` could not stop gracefully: in one process SIGTERM killed it at once,
and with `workers` the supervisor killed the workers, so a deploy cut every request and stream in flight.
The server also had no timeouts (a client that sends a head byte by byte, or opens connections and sends
nothing, holds a descriptor forever) and no cap on connections; out of descriptors, the listener stayed
readable and the loop spun at full CPU while connections queued unanswered.

**API.**

```ts
const server = Bun.serve({
  fetch: handler,
  workers: 2,
  headerTimeout: 10,    // seconds for a request head (a new connection: from its accept); 408 and close
  bodyTimeout: 60,      // seconds a body may go without a byte; 408 and close
  idleTimeout: 60,      // seconds a connection with no request in hand may stay open (Bun's name)
  maxConnections: 5000, // per process; a request on a connection past it is answered 503
})
Bun.onStopSignal((signal) => {   // SIGTERM or SIGINT, on the loop, in every worker
  server.stop()                  // closes the listener; idle connections close, busy ones after their request
  const t = setInterval(() => { if (server.openConnections === 0) process.exit(0) }, 50)
})
Bun.fdLimit()                    // RLIMIT_NOFILE's soft limit
```

**Design.**
- `tv_http_sweep` runs every 250 ms while a server has a timeout and connections are open (the loop's wait
  is bounded by it). Each connection keeps the loop times of its last read, its last write progress and the
  first byte of the request being read, and whether the input holds part of a head or of a body. A request
  being handled (an answer pending or streaming) is never timed out: unlike Bun's `idleTimeout`, a slow
  answer keeps its connection. Output the client does not take for `idleTimeout` ends the connection.
- `maxConnections`: a connection accepted past it is marked; its first complete head is answered 503.
- A spare descriptor (`/dev/null`) is kept per process: on EMFILE or ENFILE it is closed, the connection
  taken and answered 503 at once, and the spare reopened, so the listener drains instead of spinning. The
  same is done for `Bun.listen` (`runtime/net.c`), which closes such a connection.
- `httpOnSignal(fn)`: a self-pipe watched by the loop; the handler writes the signal number, the loop calls
  `fn(name)`. Each process that runs the loop arms its own pipe and handlers (a worker re-arms after the
  fork). The supervisor still forwards SIGTERM to the workers; it now closes its copy of the listeners
  (otherwise the port keeps accepting connections nobody serves) and exits 0 when every worker exited 0.
- `server.openConnections` counts the process's connections of that server (upgraded ones excepted).

**Files.**
- `runtime/tov.c`, `runtime/tov.h`: the sweep, the per-connection times, the cap, the spare descriptor, the
  signal pipe, the supervisor's listener close and exit status, and the natives `httpLimits`, `httpOpen`,
  `httpFdLimit`, `httpOnSignal`.
- `runtime/net.c`: the spare descriptor for `Bun.listen`.
- `crates/tov/src/check/builtins.rs`: the signatures.
- `crates/tov/src/std/http.tov`: the `ServeOptions` fields, `Server.openConnections`, `Bun.onStopSignal`,
  `Bun.fdLimit`.
- `docs/spec.md`: the serving paragraph.

**Measured in Raiju.** Before: SIGTERM cut a stream at chunk 5 of 23; 301 slow or idle connections were still
open after 45 s; out of descriptors the gateway answered 502 at full CPU. After: a stream in flight at
SIGTERM ends whole and the process exits 0 (one process and two workers); a silent connection closes after
the header timeout, a half-sent head or body is answered 408, an idle keep-alive connection closes after the
idle timeout; past the cap or out of descriptors a connection is answered 503.

**Not covered.** The timeouts have a 250 ms resolution. Upgraded (WebSocket) connections have no timeouts here
and are not counted by `openConnections`. The signals watched are SIGTERM and SIGINT. The test
(`tests/server_lifecycle.tov` driven by `tests/server_lifecycle_client.py`, 18 checks) is in `run.sh`.

## 0013 — fetch address policy: refuse private, loopback, link-local and metadata peers at connect time (`RequestInit.peer`)

**Problem.** A program that fetches URLs its users choose (webhooks, callbacks, OAuth endpoints, a provider's base
URL) must keep them off its own network and the cloud metadata service. It can resolve the host and check the
addresses before calling `fetch`, but `fetch` resolves the name again when it connects. A DNS server that answers
with a public address to the first lookup and with 127.0.0.1 or 169.254.169.254 to the second (DNS rebinding, a zero
TTL) gets the request through, and so does a redirect to such an address, or a pooled connection made earlier by an
unchecked request.

**API (Tov; not in Bun).**

```ts
const res = await fetch(url, {
  peer: {
    private: false,     // RFC 1918, 100.64/10, fc00::/7, fec0::/10, multicast, 240/4 and loopback (default: refused)
    loopback: true,     // 127.0.0.0/8 and ::1 only (default: refused)
    allow: ["10.1.0.0/16", "db.internal"],  // addresses, CIDR ranges, or the URL's host name, let through although private
  },
})
// a refused address rejects with FetchError code "AddressNotAllowed":
// "Connection to a private address 10.0.0.7 (host rebind.example) is not allowed"
```

**Design.**
- The check runs in `tv_fr_connect`, on the addresses the lookup returned (or the numeric host, or `localhost`),
  right before the socket is opened: for the first request, each redirect hop (which re-dials), and each new pooled or
  HTTP/2 connection. Every address must pass (the lookup keeps up to eight), not only the one connected to, so a name
  that mixes public and private answers is refused.
- Unspecified (0.0.0.0/8, ::), link-local (169.254.0.0/16, fe80::/10), Teredo (2001::/32) and the metadata addresses
  100.100.100.200 and fd00:ec2::254 are always refused, whatever `private`, `loopback` and `allow` say. IPv6 forms
  that carry an IPv4 address (IPv4-mapped, IPv4-compatible, 6to4, NAT64) are judged by that address, and so are
  `allow` ranges. The classes are those of Bifrost's `core/network/ssrf.go`.
- The policy is part of the pool key (`|peer:<bits>:<hash of allow>`), so a connection made without a policy, or
  under another one, is never reused by a request that has one.
- Through a proxy the proxy resolves the host, so nothing is checked (as Go's dialers do behind a proxy); a program
  checks a literal address in the URL itself. Unix sockets are not checked.
- `fetchStart` takes two more arguments (the policy bits and the comma-joined allow list); `node:http`'s fetch
  passes none.

**Files.**
- `runtime/tov.c`, `runtime/tov.h`: the classes, the allow list, the check in `tv_fr_connect`, the pool key and
  `fetchStart`'s arguments; `runtime/node.c`: its call.
- `crates/tov/src/check/builtins.rs`: the signature. `crates/tov/src/std/http.tov`: `RequestInit.peer` and `PeerPolicy`.
- `docs/spec.md`: the fetch paragraph.

**Not covered.** `Bun.connect` and `WebSocket` have no such option. The test (`tests/peer_policy.tov`, 21 checks:
the default refusal, each switch, address, range, mapped and name entries, a name resolved through `/etc/hosts`,
0.0.0.0, metadata, ::1, redirect hops and pooled connections) is in `run.sh`; it needs a name other than `localhost`
that `/etc/hosts` maps to 127.0.0.1 (`PEER_NAME` names one) and is skipped without it.

## 0015 — TLS client certificates, `Request.signal` on `Bun.serve`, `Bun.gunzipSync` and `Bun.inflateSync`

(Numbered 0015 by its ledger task, L190; 0014 is kept for the patch written alongside it. 0015 is written on top
of 0001-0010, 0012 and 0013: its `identity` argument follows 0013's `peer` and `peerAllow` in `fetchStart`.)

**Problem.** Three things a gateway needs were missing. `fetch` and `Bun.connect` could not present a client
certificate, so a server that requires mutual TLS (an A2A agent, in Bifrost's `agents[].*.tls`) could not be
reached. A request on `Bun.serve` had no signal: an async handler never learned that its client went away, so
the work it started (an upstream call, retries) ran on to the end. And there was no way to decompress gzip or
DEFLATE data in a program (only `fetch` bodies were decoded), which gRPC's `grpc-encoding: gzip` needs.

**API (as in Bun).**

```ts
await fetch(url, { tls: { ca, cert, key } })          // cert: PEM, the leaf first, then its chain; key: its PEM key
await Bun.connect({ hostname, port, tls: { ca, alpn: ["h2"], cert, key }, socket })
Bun.serve({ async fetch(req) { await fetch(up, { signal: req.signal }) } })  // aborts when the client goes away
Bun.gunzipSync(bytes, { maxOutputLength: 4 << 20 })   // gzip (every member); throws when corrupt or past the limit
Bun.inflateSync(bytes)                                // DEFLATE, raw or zlib-wrapped
```

**Design.**
- `tls.cert` and `tls.key` go to the runtime as one PEM text (the natives `fetchStart` and `netConnect` take one
  more string). `runtime/tls.c` keeps a context per (verify, CA, client certificate); the certificate chain and
  key are loaded into it with `SSL_CTX_use_certificate`, `SSL_CTX_add0_chain_cert` and `SSL_CTX_use_PrivateKey`
  and checked to match. Pooled fetch connections and resumed sessions are per certificate (the pool key holds a
  hash of it). A pair that is not a certificate and its key fails the request with `ERR_TLS_CLIENT_CERT`.
- `req.signal`: the runtime already noted deferred requests whose clients went away (`tv_http_on_gone`, used by
  the Node compatibility layer). `httpOnGone(fn)` hands those ids to `Bun.serve`, which keeps the async requests
  waiting for their answer by deferred id and aborts the signal of the one whose client left (an `AbortError`).
  The signal is made on first use; a request answered before its client left is forgotten when answered.
- `decompress(bytes, encoding, limit)` decodes with the codecs fetch already links (zlib), bounded by the limit
  (one byte past it tells a stream over it from one that ends at it). The error is read with `takeError`.

**Files.**
- `runtime/tls.c`, `runtime/tov.h`: the client certificate in the TLS contexts (`open` takes it).
- `runtime/tov.c`: the request's certificate and pool key, `httpOnGone`, `decompress`.
- `runtime/net.c`, `runtime/ws.c`, `runtime/node.c`: `netConnect`'s and `fetchStart`'s new argument.
- `crates/tov/src/check/builtins.rs`, `crates/tov/src/codegen/mod.rs`: the signatures; `decompress` links the codecs.
- `crates/tov/src/std/http.tov`: `TLSOptions` and `SocketTLSOptions` (`cert`, `key`), `Request.signal`,
  `Bun.gunzipSync`, `Bun.inflateSync`.
- `docs/spec.md`: the fetch, sockets and serving paragraphs.

**Measured in Raiju.** An A2A agent behind mutual TLS (JSON-RPC and gRPC) is reached with its client certificate
and refuses the gateway without it; a non-streamed request whose caller hangs up stops its upstream call at once
(no retry, no fallback, logged 499); gzip gRPC messages are read both ways (e2e `l190_e2e`).

**Not covered.** A client certificate's key must not be encrypted (no passphrase option). `Request.signal` covers
requests whose handler returned a promise (a synchronous answer has nothing to stop) and is not aborted once the
answer is given (a streamed body's cancel says that). The tests (`tests/client_cert.tov` with
`tests/client_cert_server.py`, 8 checks; `tests/server_gone.tov` with `tests/server_gone_client.py`, 4 checks;
`tests/decompress.tov`, 8 checks) are in `run.sh`.

## 0016 — a fetch connection's input buffer starts small

**Problem.** Each fetch connection's input buffer was allocated at 64 KB on the first read and kept while the
connection was busy. An LLM gateway holds one upstream connection per open stream, whose events are a few
hundred bytes, so 64 KB per stream was mostly unused memory: a third of what Raiju allocated per open stream.

**Design.** The buffer starts at 16 KB (`TV_FC_IN_START`) and a read wants 4 KB of room (`TV_FC_IN_ROOM`):
what is left unparsed is moved to the front and the buffer doubles only while it needs more room (a long
response head, a chunk size line split across reads). Bodies with a known length are still read straight into
their own buffer in 64 KB or larger steps, so large answers take no more reads than before. A connection that
goes back to the pool keeps a buffer of 16 KB at most, as before.

**Files.** `runtime/tov.c`: `tv_fc_ready`, `tv_fc_release`.

**Measured in Raiju.** 200 open streams through one gateway (`tests/soak/soak.py`'s slow streams): the bytes
allocated per open stream fell by 48 KB. The test (`tests/fetch_buffer.tov` with `tests/fetch_buffer_server.py`,
3 checks: a 40 KB response head, a 100 KB chunk with a split size line, 2,000 small events read as a stream) is
in `run.sh`. Written on top of 0001-0013 and 0015.

## 0017 — `server.requestIP(req)` on `Bun.serve`

**Problem.** A `Bun.serve` handler could not learn the client's address: Tov's `Server` had no `requestIP`, so a
program could not tell a forwarding header written by a trusted proxy from one written by the client, and could not
key a brute-force throttle or an audit record on the real peer. Raiju's own http1 server had the address (its
sockets' `remoteAddress`); the default server did not.

**API (as in Bun).** `server.requestIP(req)` returns `{ address, family, port }` (`family` is `"IPv4"` or
`"IPv6"`) for a request the server received, and `undefined` for a request the program built.

**Design.** The connection keeps the peer's address, read with `getpeername` the first time a request on it asks
(`tv_http_conn.peer`, `peer_port`); the native `httpPeer(which)` reads it for the request being handled. A request
from the wire records the address and port when it is filled in (`Request.wire`), so `requestIP` works after an
`await` too, and in `routes` handlers.

**Files.** `runtime/tov.c`, `runtime/tov.h`: `tv_native_httpPeer`, the connection fields.
`crates/tov/src/check/builtins.rs`: the native's signature. `crates/tov/src/std/http.tov`: `Request.peer`,
`Server.requestIP`, `SocketAddress`. `docs/spec.md`.

**Test.** `tests/request_ip.tov` (4 checks: the fetch handler after an await, the client's port, a request built in
the program, a routes handler) is in `run.sh`. Used by Raiju for `server.trusted_proxies` and the sign-in throttle
(L198).

## 0019 — a worker killed alone is respawned, with a crash-loop backoff; `Bun.plainAlloc()`

**Problem.** `Bun.serve({ workers })` replaced a worker that crashed by a trap, but treated a worker that died of
SIGKILL like SIGTERM: as a stop of the whole server. The kernel's OOM killer sends SIGKILL to the single largest
process, so one worker over its memory took down every other worker on the node, with their open streams, and the
container restarted. A worker that died within a second of starting was replaced after a fixed 1 s pause, so a
worker that crashed on every start was restarted once a second forever.

**Design.** SIGKILL of a worker is a crash: the slot is respawned and the other workers keep serving. (A SIGKILL
sent to the process group kills the supervisor too, so it never needs to read one as a stop.) SIGTERM and SIGINT
still count as a stop, as before. A worker that dies within 10 s of starting (`TV_HTTP_QUICK_DEATH`) is respawned
after a pause that starts at 1 s and doubles for each such death in a row, up to 30 s (`TV_HTTP_MAX_BACKOFF`); one
that ran longer is respawned at once and resets its slot's count. While a slot waits, the supervisor polls
`waitpid` every 100 ms, so other deaths, the respawn and a stop signal are all seen in time. Each respawn writes
one line to stderr: `worker 0 (pid 123) was killed by signal 9; restarting it in 2 s (2 quick exits in a row)`.

`Bun.plainAlloc()` (Tov) says whether the runtime was compiled with `TV_PLAIN_ALLOC`. The small-object free lists
are not thread-safe, and a program built without the flag that allocates off its loop thread (fetch, DNS) crashes
under concurrency; Raiju checks it at startup and refuses to serve without it.

**Files.** `runtime/tov.c`: `tv_http_supervise`, `tv_http_backoff`, `tv_native_httpPlainAlloc`; `runtime/tov.h`,
`crates/tov/src/check/builtins.rs`, `crates/tov/src/std/http.tov` (`Bun.plainAlloc`), `docs/spec.md`.

**Tested.** `tests/worker_respawn.tov` with `tests/worker_respawn_client.py` (10 checks, Linux): `Bun.plainAlloc()`
with and without the flag; a SIGKILLed worker
is replaced while the other keeps its pid and requests keep succeeding, a second early death waits 2 s, both pauses
are logged, and SIGTERM during a 4 s pause stops the supervisor and its workers within a second. Raiju's e2e kills
a gateway worker with `kill -9` (tests/e2e.py `l199_e2e`). Written on top of 0001-0017.
