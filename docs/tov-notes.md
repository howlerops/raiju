# Tov notes

Tov 0.0.1 is young. These are the problems this codebase works around, so
nobody rediscovers them. Each one is worth a report upstream
(github.com/richiemcilroy/Tov) with the repro described.

## Runtime

| Problem | Effect | Workaround here |
|---|---|---|
| The async slab allocator (`tv_async_alloc` free lists) corrupts once ~28+ `fetch` calls are in flight. | Segfault in `tv_task_new`; the gateway crashes at ~32 concurrent requests. Plain malloc never crashes, and valgrind finds nothing with it, so it looks like a size-class mismatch rather than a use-after-free. | Build with `TOV_CFLAGS=-DTV_PLAIN_ALLOC` (Makefile, e2e, bench). Measured at the same throughput. Repro: `bench/load.tov` at concurrency 32 against `tests/mock_upstream.tov`, built without the flag. |
| Built with GCC, a function returning a large record of optional fields can lose a reference to one of its strings: GCC's scalar replacement of aggregates drops some of the retains the generated C makes for the returned copy (GCC 13.3, `-O2` and `-O3`). | A use after free: `parseQuery` returned a `LogQuery` whose `virtual_key` was freed with the `URLSearchParams` it came from. It showed as one test failing in one test binary, with heap contents after the value. | `tov-patches/0027`: programs are compiled with `-fno-tree-sra` when the C compiler is GCC. Clang builds (the image and CI) are not affected. |
| `a ??= b` evaluates `b` and leaks its value whenever `a` is already set (valgrind: one lost block per assignment in a loop of 20,000). Fixed upstream after the pinned revision. | A slow leak wherever the operator runs on a hot path. | Not used in `src/`; `scripts/check.py` (through `scripts/fetch_lint.py`) refuses it. Write `if (a === undefined) a = b`. |
| `timerUnref` scans every live timer, and `AbortSignal.timeout(ms)` keeps its timer alive for `ms` after the request is done. | At thousands of req/s with 30 s timeouts the scan dominated CPU (single worker capped at ~7.8k rps). | `src/deadline.tov`: one interval sweeping FIFO deadline queues of `AbortController`s. |
| `Bun.serve` can't stream response bodies. | No incremental tokens. | Patched: `tov-patches/0001-stream-response-bodies.patch` adds `new ReadableStream({ start(controller) })`, `Response` with a stream body, and chunked sending in `Bun.serve` (natives `httpStreamStart`/`httpStreamWrite` on the runtime's `httpWriteRaw`; a client that leaves cancels the stream). Works in every `workers: n` process. `src/http1.tov` (our own server on `Bun.listen`) stays as a fallback. |
| Class instances held only through an interface value are freed while still in use. | Segfaults (garbage fields) in the stream converter and the WebSocket writer. | No interfaces for long-lived objects: concrete classes (`StreamConverter`, `WsSink` as a class of functions). |
| `workers: n` forking happens only for `Bun.serve`; a forked process can't serve a `Bun.listen` socket opened before the fork. | The http1 server is single-process. | `Bun.serve` (with the stream patch) is the default server. |
| Classes can't be instantiated through a namespace import (`new mod.Class()`), and imports can't be renamed (`import { a as b }`). | Name clashes between modules. | Distinct class names (`UiSessions` in `oidc.tov`). |
| `Headers` lookups are linear, case-insensitive scans (~84 per proxied request). | ~5% of CPU in `strncasecmp`. | Snapshot request headers into a `Map` once (`schemas.snapshot`); hand `fetch` a `Record`. |
| npm / `node:*` modules need JavaScriptCore installed at build time. | `node:crypto` isn't usable for a static binary. | SHA-256/HMAC written in Tov (`src/crypto.tov`). |

## Compiler

| Problem | Workaround |
|---|---|
| `a?.b?.get(k) ?? x` and `m?.get(k)` (optional chain into a method call) can hit internal error C0003 "no conversion from `undefined` to ...", sometimes only when the code is reachable from `main`. | `providerOf()` / `providerNames()` in `config.tov`; explicit `if` checks. |
| Recursive union types (`type Json = string \| f64 \| ... \| Json[] \| Map<string, Json>`) type-check but narrow wrongly at runtime (`typeof` reports `object` for strings). | The lazy raw-text scanner in `src/json.tov`; typed `JSON.parse` for known shapes. |
| Top-level statements in an imported module are silently not run. | Initialize module tables with a function (`const T = makeTable()`). |
| `await` inside `test(...)` isn't supported by the native backend. | Keep tests synchronous. |
| `tov check --json` reports fix columns in characters (code points), not bytes. | `scripts/check.py` applies them by character. |

## Library gaps

`String.fromCharCode`, `lastIndexOf`, `number.toString(radix)` and `decodeURIComponent`
don't exist. `parseFloat("5m")` is `undefined` (strict). Replacements live next to
their use (`schemas.hex`, `URLSearchParams` for percent-decoding).

Dynamic `process.env[name]` reads are supplied by patch 0024, using the same native
environment API as `process.env.NAME`. `config.getEnv` no longer reads Linux's
`/proc/self/environ`: config-supplied `env.NAME` secrets resolve on macOS too,
including the distinction between an unset variable and a present empty value.
Config reloads do not change the inherited environment; rotate environment-backed
secrets by restarting the process with the new value.

The native macOS provider matrix is not a full platform qualification. Management key creation and dependent
random/session tests still hit Linux's `/proc/sys/kernel/random/uuid`; an observed native adapter/transitive run
had 713 passes and 36 failures. Use the Linux container for infrastructure and management acceptance until that
entropy path is ported; do not weaken secure identifier generation to make native tests pass.

## Upstream status (checked 2026-11-15)

The pinned revision is `c2048582` (2026-10-14). Upstream `main` was 580 commits ahead (`1959aef`, 2026-10-30) and had
tagged v0.1.0. Moving the pin was assessed and not done, for these reasons:

- **The patches do not carry over.** Applied in order to `1959aef`, 3 of the 24 files in `tov-patches/` apply
  (0001, 0002, 0025); the rest fail on files upstream rewrote or removed (`runtime/tov.c` went from 7,689 to
  14,623 lines; `runtime/h2.c` and `std/wasm.tov` are gone). Upstream now has its own ALPN, UDP, HTTP/2,
  `requestIP`, `fsync`/`rename` and gunzip, with its own interfaces; it has no libdatachannel (WebRTC), no
  `flockSync`, no connect-time address policy (patches 0013 and 0022, which the outbound request guard in
  SECURITY.md depends on) and no clean worker re-execution (0026). Each patch has to be re-derived against the
  new internals, or its callers in `src/` moved to upstream's interface.
- **The language changed.** Upstream commit `3d5ecbf` ("Make records changed in place objects, shared as
  JavaScript's are, unless nothing shares them") and the commits around it change when a record is copied. The
  gateway is written for copies on assignment (docs/agent-brief.md), so every place that changes a record after
  assigning it would have to be re-read.
- **Upstream's memory fixes are for features added after the pin.** Its fixes for leaks and use-after-frees
  ("Stop leaking the values of `||`, `&&` and `??=`", the splice and regex-match leaks, "Fix use-after-frees of
  taken fields…") do not cherry-pick onto the pin: `||` on non-booleans, `splice` and regex literals do not
  exist here, and the taken-field moves were introduced later. The one that does exist here is `??=`, which
  leaks (see the table above); the sources do not use it and the lint refuses it.
- **Nothing measured says the pin is hurting.** The memory soak is flat, valgrind is silent on the test binary
  with patch 0027, and throughput rose with the last round of changes.

What an upgrade would need: a branch that re-derives the patches one by one (the address policy and the worker
supervisor first, with their tests in `tov-patches/tests`), a pass over record mutation in `src/` under the new
sharing rule, then the same gates as any release: `make unit`, both e2e runs, the browser suite, the memory soak,
valgrind on the test binary, and the throughput comparison against the pinned build. Upstream's "Build every
program with gcc" should be read first: with GCC, patch 0027's `-fno-tree-sra` (or an upstream equivalent) is
required.
