# Bun.spawnSocket: run a program with its stdin and stdout on a Socket

Branch `feat/spawn-socket` (one commit on c2048582).

## What

`Bun.spawnSocket(options)` runs a program with its stdin and stdout connected to a
`Socket`. The program's output arrives as `data` events, `write` goes to its input, and
`close` runs when it exits.

## Why

Tov had no way to start a process. A program that talks to a child over its stdin and
stdout (newline-delimited JSON, a common transport for tool servers) couldn't do so.
Bun's `Bun.spawn` returns a stream-based object that doesn't fit Tov's socket handlers,
so this is a Tov-specific API that reuses the `SocketHandler` of `Bun.connect`.

## API

```ts
const sock = await Bun.spawnSocket({
  cmd: ["python3", "server.py"],
  env: { API_KEY: "..." },   // added to the inherited environment
  cwd: "/srv",
  socket: { data(s, bytes) {}, close(s) {} },
})
sock.write("request\n")      // to the child's stdin
```

It resolves with the `Socket` once it is open. A program that can't be started closes
the socket at once, with the reason on stderr.

## Design

- `netSpawn(argv, env, cwd)` in `runtime/net.c` makes a `socketpair(AF_UNIX)`, forks,
  and execs with the child's stdin and stdout on one end. The other end goes into the
  existing socket table as an already-open socket, so reads, writes, backpressure,
  `end()` and close come from the code that serves TCP and Unix sockets.
- `argv` and `env` are passed as NUL-separated lists. `env` entries are added to the
  inherited environment.
- On Linux the child gets `PR_SET_PDEATHSIG(SIGTERM)`, so it dies with its parent.
- stderr is inherited.
- Changes: `runtime/net.c`, `runtime/tov.h`, `check/builtins.rs` (the signature),
  `std/http.tov` (`SpawnSocketOptions`, `spawnSocket`, `Bun.spawnSocket`),
  `docs/spec.md`.

## Tests

`tests/run/native_spawn.tov`: a shell loop that echoes each line with an env var in
front. It checks the echoed lines and the close event after `end()`, a `cwd`, and that a
missing executable closes its socket.

`cargo test --release --test run` passes except the npm case, which needs JavaScriptCore
installed; `cargo test --release --test http` passes.

## Limits

- No exit status yet. Exited children are reaped with `waitpid(pid, WNOHANG)` on each
  spawn and socket close, only for the pids spawned this way, so other code that waits
  for its own children is unaffected.
- No separate stderr pipe; stderr is inherited.
- The parent-death signal is Linux only, and there is no Windows support.
- A missing executable is reported as a closed socket, not as a rejected promise.
