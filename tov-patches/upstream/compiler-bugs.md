# Tov bugs found while building Raiju, as issue reports

Each section below is one issue, ready to paste: a title, a minimal program, what was expected,
what happens, and how Raiju works around it. Every repro was compiled on 2026-10-20 with:

- **unpatched Tov at c2048582** (`cargo build --release` of the pinned commit), and
- **Raiju's patched compiler** (`build/tov/target/release/tov`: c2048582 + `tov-patches/0001-0009`).

The results were the same on both, so none of these come from Raiju's patches. "Reproduces"
below means "reproduces on both". The programs are written to be compiled with `tov build x.tov`
and run as they are. They were not checked against Tov's current `main`, which may have fixed some
of them: search the issues first.

Sources: `docs/tov-notes.md`, `docs/agent-brief.md`, the workaround comments in `src/`, the
`tov-patches/README.md` notes on 0006, and the L160/L161 notes.

| # | Title | Kind | Status |
|---|---|---|---|
| C1 | Optional chaining into a method call: internal error C0003 | compiler | reproduces |
| C2 | A conditional `x > 0 ? x : 0` (x: int) passed as setTimeout's delay: internal error C0003 | compiler | reproduces |
| C3 | A closure capturing a record that is changed afterwards: generated C does not compile | compiler | reproduces |
| C4 | A class instance held only through an interface-typed field: segfault | compiler (codegen/refcounts) | reproduces |
| C5 | Recursive union types narrow wrongly at runtime (`typeof` of a string) | compiler | reproduces |
| C6 | `switch` on a string with `break` cases corrupts memory | compiler (codegen/refcounts) | reproduces |
| C7 | An inner closure capturing a class-typed parameter of the outer closure: generated C does not compile | compiler | reproduces |
| C8 | `tov check --json` positions are in code points; the unit is not documented | tooling | reproduces (behaviour) |
| C9 | `new ns.Class()` through a namespace import: misleading diagnostic | diagnostics | reproduces |
| R1 | The async slab allocator crashes with ~250 `fetch` calls in flight | runtime | reproduces |
| R2 | `timerUnref` scans every live timer; `AbortSignal.timeout` timers outlive their request | runtime (performance) | not re-measured |
| R3 | `Headers` lookups are linear case-insensitive scans | runtime (performance) | not re-measured |

Not bugs any more, or by design (listed so nobody files them): see the end of this file.

---

## C1. Optional chaining into a method call fails with internal error C0003

**Repro**

```ts
type Cfg = { providers?: Map<string, string> }

function lookup(c: Cfg, k: string): string {
  return c.providers?.get(k) ?? "none"
}

function lookup2(m: Map<string, int> | undefined, k: string): int | undefined {
  return m?.get(k)
}

function main(): void {
  const m: Map<string, string> = new Map()
  m.set("a", "x")
  console.log(lookup({ providers: m }, "a"))
  console.log(lookup({}, "a"))
  const n: Map<string, int> = new Map()
  n.set("k", 3)
  console.log(lookup2(n, "k") ?? -1)
  console.log(lookup2(undefined, "k") ?? -1)
}
main()
```

**Expected**: `tov check` accepts it (it does); `tov build` builds it, and it prints `x`, `none`,
`3`, `-1`.

**Actual**: `tov build` fails:

```
error[C0003] b01_optchain.tov:1:1: internal compiler error: no conversion from `undefined` to `int`
error[C0003] b01_optchain.tov:1:1: internal compiler error: no conversion from `undefined` to `string`
```

Both point at 1:1, so in a large program the failing expression has to be found by bisection. In
Raiju it sometimes appeared only once the function was reachable from `main`.

**Workaround in Raiju**: no `?.` before a method call. Explicit checks (`const ps = cfg.providers;
if (ps === undefined) return undefined; return ps.get(name)`), in helpers such as `providerOf()` and
`providerNames()` (`src/config.tov`).

---

## C2. A conditional mixing an int and a literal, passed as setTimeout's delay: internal error C0003

**Repro**

```ts
function arm(x: int): void {
  const t = setTimeout(() => { console.log("fired") }, x > 0 ? x : 0)
  clearTimeout(t)
}
function main(): void {
  arm(5)
  arm(0)
  console.log("ok")
}
main()
```

**Expected**: builds and prints `ok` (`setTimeout(f, x)` with `x: int` builds, and so does
`setTimeout(f, 0)`).

**Actual**:

```
error[C0003] b02_ternary_timeout.tov:1:1: internal compiler error: no conversion from `int | f64` to `f64`
```

The literal branch is typed from the parameter (`f64`) and the other branch as `int`, and the
conditional's `int | f64` is not converted. It fails the same way under `tov test` and with any
literal (`0`, `100`, `2147483647`).

**Workaround in Raiju**: a typed local first (`let delay: int = 2147483647; if (timeoutMs > 0)
delay = timeoutMs; setTimeout(..., delay)`, `src/h2.tov`).

---

## C3. A closure that captures a record changed after the closure is made: the generated C does not compile

**Repro**

```ts
type Up = { url: string, headers: Map<string, string> }

function make(): Up {
  const h: Map<string, string> = new Map()
  h.set("api-key", "k")
  return { url: "http://x", headers: h }
}

function main(): void {
  const up = make()
  const send = (body: string): string => {
    const hs: Map<string, string> = new Map()
    for (const k of up.headers.keys()) hs.set(k, up.headers.get(k)!)
    return `${up.url} ${hs.size} ${body}`
  }
  up.headers.delete("api-key")
  up.headers.set("authorization", "Bearer t")
  console.log(send("b"))
}
main()
```

**Expected**: prints `http://x 1 b` (the closure sees the record as changed; or, if captured
records are meant to be copies, a type error saying so).

**Actual**:

```
error: internal error: the generated C failed to compile (this is a bug in tov)
.../f89df3fdb6abb229f5c108e69960c546.c:8:41: error: field has incomplete type 'R21_Up' (aka 'struct R21_Up')
    8 | typedef struct C21 { int64_t rc; R21_Up v; } C21;
.../f89df3fdb6abb229f5c108e69960c546.c:7:16: note: forward declaration of 'struct R21_Up'
```

The cell that boxes the captured, mutated record is emitted before the record's struct is
defined. Without the two lines that change `up.headers` it builds and runs; an `async` closure
fails the same way.

**Workaround in Raiju**: copy what the closure needs into locals that are not changed afterwards
(`upUrl`, a fresh `upHeaders` map) before making the closure (`src/realtimecalls.tov`).

---

## C4. A class instance held only through an interface-typed field is freed while in use

**Repro**

```ts
interface Sink {
  write(s: string): void
  count(): int
}

class Buf implements Sink {
  parts: string[] = []
  write(s: string): void { this.parts.push(s) }
  count(): int { return this.parts.length }
}

class Holder {
  sink: Sink
  constructor(s: Sink) { this.sink = s }
}

function main(): void {
  const h = new Holder(new Buf())
  h.sink.write("a")
  console.log(h.sink.count())
}
main()
```

**Expected**: prints `1`.

**Actual**: `Segmentation fault`. With the field and parameter typed `Buf` instead of `Sink`, the
same program prints `1` (and a larger version that writes 10,000 strings prints `10000`).

**Workaround in Raiju**: no interfaces for long-lived objects. Concrete classes instead
(`StreamConverter` over the per-provider converters in `src/gateway.tov`; `WsSink`, a class of two
functions, in `src/ws.tov`).

---

## C5. Recursive union types narrow wrongly at runtime

**Repro**

```ts
type Json = string | f64 | bool | Json[] | Map<string, Json>

function kind(j: Json): string {
  if (typeof j === "string") return "string:" + j
  if (typeof j === "number") return "number"
  if (typeof j === "boolean") return "bool"
  if (Array.isArray(j)) return `array(${j.length})`
  return "map"
}

function main(): void {
  const m: Map<string, Json> = new Map()
  m.set("a", "hello")
  const xs: Json[] = ["s", 1.5, true, m]
  const top: Json = xs
  console.log(kind("plain"))
  console.log(kind(top))
  for (const x of xs) console.log(kind(x))
  const v = m.get("a")
  if (v !== undefined) console.log(kind(v))
}
main()
```

**Expected**:

```
string:plain
array(4)
string:s
number
bool
map
string:hello
```

**Actual** (it type-checks and builds):

```
bool
array(4)
bool
number
bool
map
bool
```

Every string is narrowed as a boolean (Raiju first saw `typeof` report `object` for strings in a
larger tree type).

**Workaround in Raiju**: no recursive JSON union. A lazy scanner over the raw text (`src/json.tov`),
and typed `JSON.parse(text) as T` for known shapes.

---

## C6. `switch` on a string with `break` cases corrupts memory

**Repro**

```ts
function name(kind: string): string {
  let r = ""
  switch (kind) {
    case "open":
      r = "o"
      break
    default:
      r = "?"
  }
  return r
}

function main(): void {
  const parts = "open,other".split(",")
  let out = ""
  for (let i = 0; i < 6; i++) out += name(parts[i % 2]!)
  console.log(out)
  console.log(parts.join(","))
}
main()
```

**Expected**:

```
o?o?o?
open,other
```

**Actual**: the first call matches, every later one falls to `default`, and the strings in `parts`
are garbage afterwards:

```
o?????
o????   p @�  o?????        (then hundreds of bytes of garbage)
```

The switched-on string is released once more than it is retained, so its storage is reused while
`parts` still points at it. The same switch with `return` in each case instead of `break` works,
and so does an `if`/`else if` chain. Seen in Raiju as "switch on a string variable releases the
string twice" while writing `std/rtc`; a larger program showed it as wrong totals and garbage
output.

**Workaround in Raiju**: no `switch` on strings: `if`/`else` chains, or integer kinds (`std/rtc`
routes its events by an `int` kind).

---

## C7. An inner closure that captures a class-typed parameter of the outer closure: the generated C does not compile

**Repro**

```ts
class Channel {
  label: string
  onmessage: ((m: string) => void) | undefined = undefined
  constructor(label: string) { this.label = label }
  send(m: string): void { console.log(`${this.label} <- ${m}`) }
}

class Peer {
  ondatachannel: ((ch: Channel) => void) | undefined = undefined
}

function main(): void {
  const p = new Peer()
  p.ondatachannel = (ch) => {
    ch.onmessage = (m) => { ch.send("echo:" + m) }
  }
  const c = new Channel("x")
  const f = p.ondatachannel
  if (f !== undefined) f(c)
  const g = c.onmessage
  if (g !== undefined) g("hi")
}
main()
```

**Expected**: prints `x <- echo:hi`.

**Actual**:

```
error: internal error: the generated C failed to compile (this is a bug in tov)
.../f07490c4b90918c90fa78878104ac1d4.c:241:24: error: no member named 'rc' in 'struct K20_Channel'
  241 |     env8->c0 = p0; p0->rc++;
```

The capture is emitted as a retain on the struct itself, not through the instance's header.

**Workaround in Raiju**: copy the parameter into a local first (`const ch = incoming`), and capture
the local (`tov-patches/tests/rtc.tov`, `tests/run/native_rtc.tov` in the `std/rtc` branch).

---

## C8. `tov check --json` positions are in code points, and the unit is not documented

**Repro** (`tov check --json x.tov`):

```ts
function main(): void {
  const s = "héllo wörld ✓"; const n = s.length
  console.log(n)
}
main()
```

**Actual**: the X0010 diagnostic and its fix give `"line":3,"col":42`. `length` starts at code
point 42 of that line, at byte 46 (and UTF-16 unit 42).

**Expected**: a documented unit. Tov strings index by byte everywhere else, and LSP clients count
UTF-16 units, so a tool applying fixes has to guess. Either document "columns are Unicode scalar
values" or offer bytes.

**Workaround in Raiju**: `scripts/check.py` applies fixes by character offset.

---

## C9. `new ns.Class()` through a namespace import: the diagnostic calls the namespace a type

**Repro** (two files):

```ts
// lib.tov
export class Counter {
  n: int = 0
  inc(): int { this.n++; return this.n }
}
export function one(): int { return 1 }
```

```ts
// main.tov
import * as lib from "./lib"
const c = new lib.Counter()
console.log(c.inc() + lib.one())
```

**Expected**: prints `2`, or, if classes cannot be reached through a namespace import, an error
saying that.

**Actual**:

```
error[N0001] main.tov:2:15: unknown class `lib`
  note: `lib` is a type; records are created with object literals: `{ ... }`
```

`lib` is a namespace, not a type, and the note sends the reader the wrong way.

**Workaround in Raiju**: named imports of classes, distinct class names across modules, and
factory functions for importers that only have the namespace (`src/cloud_auth.tov`).

---

## R1. The async slab allocator crashes with many `fetch` calls in flight

**Repro**: an HTTP/1.1 server whose `/slow` answers after 0.4 s (any slow server; Raiju used
`tov-patches/tests/h2_server.py h1`), and:

```ts
async function pause(ms: int): Promise<void, Error> {
  const p = new Promise<void, Error>((resolve, reject) => { setTimeout(() => resolve(), ms) })
  try await p
}

async function get(url: string): Promise<string, Error> {
  const res = try await fetch(url)
  return try await res.text()
}

async function main(): Promise<int> {
  const base = process.env.BASE ?? "http://127.0.0.1:8080"
  try {
    for (let round = 0; round < 6; round++) {
      const ps: Promise<string, Error>[] = []
      for (let i = 0; i < 250; i++) ps.push(get(`${base}/slow?r=${round}&i=${i}`))
      const bodies = try await Promise.all(ps)
      let ok = 0
      for (const b of bodies) if (b === "slow") ok += 1
      const ac = new AbortController()
      const doomed = fetch(base + "/slow", { signal: ac.signal })
      await pause(50)
      ac.abort()
      try { await doomed } catch (e) {}
      await pause(20)
      console.log(`round ${round}: ${ok} of 250`)
    }
  } catch (e) {
    console.log("FAIL " + e.message)
  }
  return 0
}

await main()
```

**Expected**: six `round N: 250 of 250` lines, every run.

**Actual**: unpatched c2048582 crashed with SIGSEGV in 8 of 30 runs (`BASE=http://127.0.0.1:PORT
./prog`); built with `TOV_CFLAGS=-DTV_PLAIN_ALLOC` it crashed in 0 of 15. Under gdb the crash is
in `tv_promise_new` (`memset(p, 0, sizeof(tv_promise))`, called from the program's `pause`), i.e.
the allocator handed out a corrupt block; in Raiju's gateway it showed as a crash in
`tv_task_new` at about 32 concurrent requests. Valgrind with plain malloc finds nothing, which
points at the slab free lists (a size-class mismatch between allocation and free, perhaps) rather
than a use-after-free in the program.

**Workaround in Raiju**: every build uses `TOV_CFLAGS=-DTV_PLAIN_ALLOC` (Makefile, e2e, bench);
throughput was the same. The fetch-pool test in the `feat/fetch-pool-http2` branch trips this
fault in Tov's own harness (see `fetch-pool-http2.md`), so this report should go first.

---

## R2. `timerUnref` scans every live timer, and `AbortSignal.timeout` keeps its timer for the whole timeout

**Report** (from Raiju's profiling; not re-measured for this file): with a 30 s
`AbortSignal.timeout(ms)` per request, each signal's timer lives 30 s after its request is done,
and `timerUnref` walks every live timer. At thousands of requests per second that scan dominated
CPU (one worker capped at about 7.8k requests/s). Expected: unref in constant time (a flag on the
timer, or a heap keyed by deadline), and a timeout signal whose timer can be cleared once the
request completes.

**Workaround in Raiju**: `src/deadline.tov`, one interval sweeping FIFO deadline queues of
`AbortController`s.

---

## R3. `Headers` lookups are linear, case-insensitive scans

**Report** (from Raiju's profiling; not re-measured): a proxied request made about 84 header
lookups, about 5% of CPU in `strncasecmp`. Expected: a lower-cased index built once per `Headers`.

**Workaround in Raiju**: request headers are copied into a `Map` once (`schemas.snapshot`), and
`fetch` is given a `Record`.

---

## Not filed: by design, already diagnosed, or not reproduced

- **Top-level statements in an imported module.** Raiju's notes say they were "silently not run".
  At c2048582 they are an error (`P0201 only the program's entry file can have top-level
  statements`, with the advice to export a function), which is by design. Nothing to file.
- **Renamed imports** (`import { a as b }`): rejected on purpose (`X0012 renaming imports is not
  supported`, "every name has one spelling"). Nothing to file.
- **`await` inside `test(...)`**: `C0001 await here is not supported by the native backend yet`,
  a known gap the message states. Nothing to file.
- **`split` on NUL separators** (a comment in `src/semcache.tov`): `"a\0b\0c".split("\0")`, a NUL
  that came from decoded bytes, and `join`/`split` with `"\u0000"` all work at c2048582. Not
  reproduced; not filed.
- **Library gaps** (feature requests, not bugs): `String.fromCharCode`, `lastIndexOf`,
  `number.toString(radix)`, `decodeURIComponent`, `atob`/`btoa`, `process.env[name]` with a computed
  name, `RegExp`, `Date` parsing, and `parseFloat("5m")` being `undefined` (strict on purpose).
  Raiju has replacements next to their use.
- **`node:*` modules need JavaScriptCore at build time**: a documented property of Tov's npm
  support, not a bug.
