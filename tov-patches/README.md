# Tov patches

Raiju builds against [Tov](https://github.com/richiemcilroy/Tov) at commit
`c2048582de4e9468267f801313144d75c12e983f` plus the patches here, applied in
order by `scripts/build-tov.sh` (`make tov`). Each patch is self-contained and
written to be offered upstream. `tests/run.sh` checks both with the patched
compiler: `TOV=build/tov/target/release/tov tov-patches/tests/run.sh` (or
`make tov-test`).

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
  source's `cancel`.

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
  parent (a `Bun.serve` worker, say). `SIGCHLD` is ignored, so exits are reaped
  by the kernel.
- stderr is inherited. A missing executable prints to stderr and shows up as
  the socket closing.

**Files.**
- `runtime/net.c`, `runtime/tov.h`: `netSpawn`, and opening a spawned socket in
  `tv_ns_start`.
- `crates/tov/src/check/builtins.rs`: the signature.
- `crates/tov/src/std/http.tov`: `SpawnSocketOptions` and `Bun.spawnSocket`.

**Not covered.** There is no exit status (exits are reaped by the kernel), no
separate stderr pipe and no Windows support. A Bun-compatible `Bun.spawn` with
`stdout: "pipe"` could be built on the same native later.
