# Tov patches

Raiju builds against [Tov](https://github.com/richiemcilroy/Tov) at commit
`c2048582de4e9468267f801313144d75c12e983f` plus the patches here, applied in
order by `scripts/build-tov.sh` (`make tov`). Each patch is written to be offered
upstream. `tests/run.sh` checks all five with the patched compiler:
`TOV=build/tov/target/release/tov tov-patches/tests/run.sh` (or `make tov-test`).
Patch 0004 is written on top of 0003 (its hunks include the ALPN signatures), so the
patches apply in order only. Patch 0005 adds a vendored C library (about 2.7 MB of text), which
the first four do not.

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
