# Tov notes

Tov 0.0.1 is young. These are the problems this codebase works around, so
nobody rediscovers them. Each one is worth a report upstream
(github.com/richiemcilroy/Tov) with the repro described.

## Runtime

| Problem | Effect | Workaround here |
|---|---|---|
| The async slab allocator (`tv_async_alloc` free lists) corrupts once ~28+ `fetch` calls are in flight. | Segfault in `tv_task_new`; the gateway crashes at ~32 concurrent requests. Plain malloc never crashes, and valgrind finds nothing with it, so it looks like a size-class mismatch rather than a use-after-free. | Build with `TOV_CFLAGS=-DTV_PLAIN_ALLOC` (Makefile, e2e, bench). Measured at the same throughput. Repro: `bench/load.tov` at concurrency 32 against `tests/mock_upstream.tov`, built without the flag. |
| `timerUnref` scans every live timer, and `AbortSignal.timeout(ms)` keeps its timer alive for `ms` after the request is done. | At thousands of req/s with 30 s timeouts the scan dominated CPU (single worker capped at ~7.8k rps). | `src/deadline.tov`: one interval sweeping FIFO deadline queues of `AbortController`s. |
| `Bun.serve` can't stream response bodies. | No incremental tokens. | `src/http1.tov`: our own HTTP/1.1 server (and WebSockets, `src/ws.tov`) on `Bun.listen`; it matched `Bun.serve`'s throughput. |
| Class instances held only through an interface value are freed while still in use. | Segfaults (garbage fields) in the stream converter and the WebSocket writer. | No interfaces for long-lived objects: concrete classes (`StreamConverter`, `WsSink` as a class of functions). |
| `workers: n` forking happens only for `Bun.serve`; a forked process can't serve a `Bun.listen` socket opened before the fork. | The http1 server is single-process. | One process per core behind a load balancer; `-workers N` falls back to `Bun.serve` (buffered streaming). |
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

`String.fromCharCode`, `lastIndexOf`, `number.toString(radix)`, `decodeURIComponent`
and dynamic `process.env[name]` don't exist. `parseFloat("5m")` is `undefined`
(strict). Replacements live next to their use (`schemas.hex`, `config.getEnv`
via `/proc/self/environ`, `URLSearchParams` for percent-decoding).
