# Upstream material for Tov

Everything here is meant for [Tov](https://github.com/richiemcilroy/Tov) itself: one pull request
per folder (a `git format-patch` series of one commit, in Tov's `feat: ...` style, with tests in
Tov's own harness and the `docs/spec.md` lines), its description (`<name>.md`: What, Why, API,
Design, Changes, Vendored code, Tests, Limits), and a file of bug reports to open as issues.

All of it is against Tov at `c2048582de4e9468267f801313144d75c12e983f`, the commit Raiju pins
(`scripts/build-tov.sh`). Tov's `AGENTS.md` asks that pull requests mention no coding agents and
carry no attribution trailers; the commits here have neither (author "Raiju contributors").

## Pull requests

| # | Upstream name (folder, description) | Branch | Applies on | Raiju patch | Vendored | Status |
|---|---|---|---|---|---|---|
| 1 | [stream-response-bodies](stream-response-bodies.md) | `feat/stream-response-bodies` | c2048582 | 0001 | none | ready; applies; its test passed again here inside branch 6 |
| 2 | [spawn-socket](spawn-socket.md) | `feat/spawn-socket` | c2048582 | 0002 | none | ready; applies (tests as checked when it was prepared) |
| 3 | [alpn](alpn.md) | `feat/alpn` | c2048582 | 0003 | none | ready; applies; its test passed again here inside branch 5 |
| 4 | [udp](udp.md) | `feat/udp` | `feat/alpn` | 0004 | none | ready; applies (tests as checked when it was prepared) |
| 5 | [fetch-pool-http2](fetch-pool-http2.md) | `feat/fetch-pool-http2` | `feat/alpn` | 0007 | nghttp2 1.64.0 (MIT) | applies, builds; its test passes with `-DTV_PLAIN_ALLOC` and is flaky with the default allocator because of bug R1 (unpatched Tov) |
| 6 | [request-body-streams](request-body-streams.md) | `feat/request-body-streams` | `feat/alpn` + `feat/fetch-pool-http2` + `feat/stream-response-bodies` | 0008 (with the L157 `httpBodyCancel` fix) | none | applies, builds, tests pass |
| 7 | [node-fs-rename-fsync](node-fs-rename-fsync.md) | `feat/node-fs-rename-fsync` | c2048582 | 0009 | none | applies, builds, tests pass |
| 8 | [wasm](wasm.md) | `feat/wasm` | c2048582 | 0005 | WAMR 2.4.5 (Apache-2.0 WITH LLVM-exception) | applies, builds, tests pass |
| 9 | [wasm-time-limit](wasm-time-limit.md) | `feat/wasm-time-limit` | `feat/wasm` | 0010 | changes one WAMR file | applies, builds, tests pass |
| 10 | [rtc](rtc.md) | `feat/rtc` | c2048582 | 0006 | libdatachannel 0.24.6, libjuice (MPL-2.0); usrsctp, libsrtp 2.8.0 (BSD-3-Clause); plog (MIT) | applies, builds, tests pass |

"Applies" means `git am --3way` of the folder's series (after the series of the branches it is
built on) onto a clean clone at c2048582. "Builds" means `cargo build --release` of that branch.
"Tests pass" means the tests the commit adds, run with that branch's compiler (details in each
description). In addition, Tov's whole `cargo test --release --test run` harness passes, every
program and the examples' tests, on `feat/node-fs-rename-fsync`, `feat/wasm-time-limit` (which
includes `feat/wasm`), `feat/request-body-streams` (which includes 1, 3 and 5) and `feat/rtc`
(42-44 programs, 0 failed each). For 1-4 see the checks recorded when they were prepared (`cargo test --release --test http` and `--test run`, the
latter failing only `npm_const_throws`, which fails the same way on unpatched Tov without
JavaScriptCore).

Raiju's own series (`tov-patches/0001-0010`, applied in order by `scripts/build-tov.sh`) is the
integrated version of all of this. It applies in order to c2048582, the compiler builds, and
`tov-patches/tests/run.sh` passes against it (spawnSocket, stream bodies, ALPN 3, UDP 8, dgram 8,
std/wasm 24, std/rtc 20, fetch pool 23, fetch stream bodies 36, Bun.serve body streams 19,
Socket.pause 2, node:fs 17).

### How the branches relate

```
c2048582 ─┬─ feat/stream-response-bodies ──────────────┐
          ├─ feat/spawn-socket                          │ (cherry-picked onto the pool branch)
          ├─ feat/alpn ─┬─ feat/udp                     ▼
          │             └─ feat/fetch-pool-http2 ── base/request-body-streams ── feat/request-body-streams
          ├─ feat/node-fs-rename-fsync
          ├─ feat/wasm ── feat/wasm-time-limit
          └─ feat/rtc
```

To recreate a branch: on a fork at c2048582, `git am` the series of every branch it is built on,
in the order of the "Applies on" column, then its own. For `feat/request-body-streams`:
`alpn`, `fetch-pool-http2`, `stream-response-bodies`, `request-body-streams`.

Branches that are independent of each other still touch the same lists (the native signature
table in `check/builtins.rs`, the declarations in `runtime/tov.h`, `STD_MODULES` in `driver.rs`,
lines of `docs/spec.md`). Once one is merged, the next needs a rebase that keeps both sides of
those lists; `git am --3way` of all ten in one go stops at the first such list (checked: `alpn`
after `stream-response-bodies` and `spawn-socket`, for one). Nothing else conflicts.

## Bug reports

[compiler-bugs.md](compiler-bugs.md): one section per issue, each with a minimal program, the
expected and actual result, and Raiju's workaround. All were reproduced on 2026-10-20 at c2048582
without Raiju's patches, and with them.

| # | Title | Kind |
|---|---|---|
| C1 | Optional chaining into a method call: internal error C0003 | compiler |
| C2 | A conditional `x > 0 ? x : 0` (x: int) passed as setTimeout's delay: internal error C0003 | compiler |
| C3 | A closure capturing a record that is changed afterwards: generated C does not compile | compiler |
| C4 | A class instance held only through an interface-typed field: segfault | compiler (memory safety) |
| C5 | Recursive union types narrow wrongly at runtime | compiler |
| C6 | `switch` on a string with `break` cases corrupts memory | compiler (memory safety) |
| C7 | An inner closure capturing the outer closure's class-typed parameter: generated C does not compile | compiler |
| C8 | `tov check --json` positions are code points; the unit is undocumented | tooling |
| C9 | `new ns.Class()` through a namespace import: misleading diagnostic | diagnostics |
| R1 | The async slab allocator crashes with ~250 `fetch` calls in flight | runtime (memory safety) |
| R2 | `timerUnref` scans every timer; `AbortSignal.timeout` timers outlive the request | runtime (performance) |
| R3 | `Headers` lookups are linear scans | runtime (performance) |

The file also lists what is not worth filing (by design now, or not reproduced).

## Suggested order upstream

1. **Issues first, all at once:** C1-C9 and R1-R3. They cost the maintainer nothing to read, they
   are independent of the pull requests, and the memory-safety ones (C4, C6, R1) matter most.
   R1 also blocks a clean test run of pull request 5.
2. **node-fs-rename-fsync** (7): small, Node's API exactly, no dependencies. A good first pull
   request to learn the maintainer's review style.
3. **alpn** (3), then **stream-response-bodies** (1) and **spawn-socket** (2): small runtime
   features with Bun's API (spawnSocket is Tov's own; say so).
4. **udp** (4), after alpn.
5. **fetch-pool-http2** (5), after alpn and once R1 is fixed (or with its 250-request check
   lowered; say which). It brings the first new vendored library (nghttp2, MIT, 1.2 MB of text):
   consider asking in an issue first whether HTTP/2 in `fetch` is wanted and whether vendoring is
   the preferred way.
6. **request-body-streams** (6), after 5 and 1.
7. **wasm** (8) and **wasm-time-limit** (9, or folded into 8 on request). Open an issue first: it
   vendors 2.7 MB of WAMR and adds a Tov-specific module, which is a direction for the maintainer
   to choose.
8. **rtc** (10) last, and only after an issue: 4.9 MB of vendored C and C++ (two MPL-2.0
   libraries in an MIT repository), a four-minute first build of the archive, and the narrowest
   audience. If the maintainer would rather not vendor it, the bridge (`runtime/rtc.c`, `std/rtc`)
   could link a system libdatachannel instead; that is not written.

## Files

- `<name>/0001-*.patch`: the series (`git format-patch`, one commit each).
- `<name>.md`: the pull request description, with what the branch depends on and, where a library
  is vendored, its version, commit and licence.
- `compiler-bugs.md`: the issue reports.

The first four folders were prepared earlier (Raiju L-ledger entries for 0001-0004); the other six,
`compiler-bugs.md` and this index were added on 2026-10-20 from Raiju's patches 0005-0010 as they
stand at that date.
