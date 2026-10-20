# std/wasm: WebAssembly modules on a vendored interpreter (WAMR)

Branch `feat/wasm` (one commit on c2048582). Series: [wasm/](wasm/). Raiju patch: `0005-wamr.patch`.

Depends on: nothing; it applies to c2048582 on its own. `feat/wasm-time-limit` builds on it.

## What

`import { instantiate } from "std/wasm"` runs WebAssembly modules. `instantiate(bytes, limits)`
loads and instantiates a module from its bytes and returns a `WasmInstance`: call exports with
i32 and i64 values, read and write linear memory, read what the module printed, and close it.
Each instance has limits on its memory, its operand stack and the instructions one call may run.

## Why

Tov could not run WebAssembly. A program that loads plugins as WebAssembly modules (a gateway's
request hooks, for example) had no engine short of linking JavaScriptCore, which is tens of
megabytes and not available on every build host. A small interpreter linked only into the programs
that use it keeps a Tov binary self-contained.

## API

```ts
import { instantiate } from "std/wasm"

const m = try instantiate(bytes, { fuel: 5_000_000, stackBytes: 65536, maxPages: 256 })
m.has("add")                 // an export of that name
m.arity("add")               // its parameter count, -1 when there is none
try m.call("add", [40, 2])   // i32 and i64 arguments as int; the first result as int (42)
try m.write(ptr, bytes)      // linear memory, by offset (u8[])
const out = try m.read(ptr, len)
m.memorySize()               // bytes
m.output()                   // what the module wrote to fd 1 and 2 (64 KiB at most), then cleared
m.close()
```

A trap, a missing export, a wrong argument count or an offset outside memory throws an `Error`
with WAMR's message. `maxPages` is the most 64 KiB pages of linear memory (default 256): a module
whose initial memory is above it is refused, and `memory.grow` past it returns -1. `stackBytes`
is the operand stack (default 64 KiB). `fuel` is the most instructions one call may run (WAMR's
instruction metering; default none, at most 2^31 - 1); past it the call throws
"instruction limit exceeded".

A module sees nothing but its own memory and a WASI subset written for this change
(`runtime/wasm.c`): `fd_write` to fd 1 and 2 (captured), `fd_read` of an empty stdin,
`clock_time_get`, `clock_res_get`, `random_get`, an empty environment and argument list,
`sched_yield`, `proc_exit` (a trap) and refusals (`EBADF`, `ENOSYS`) for files and polling; plus
`env.abort`, which AssemblyScript imports. An import outside that set does not stop the module
from loading; calling it traps.

## Design

- WAMR 2.4.5 is vendored under `vendor/wamr`: the fast interpreter, the loader, the runtime, the
  `ems` allocator and the POSIX platform layer, with their headers (2.7 MB of text). AOT, JIT,
  WASI libc, threads, SIMD and GC code is left out. `vendor/wamr/TOV.md` records the release, the
  files and the flags.
- It is built with explicit bounds checks (`WASM_DISABLE_HW_BOUND_CHECK=1`): no signal handlers
  and no 8 GiB address reservation per memory. The flags are `WAMR_C` in
  `crates/tov/src/tls_flags.rs`.
- It is built the way BoringSSL is: into the vendored archive the compiler carries, linked only
  into programs that call the natives (codegen looks for the `tv_native_wasm` prefix).
  `runtime/wasm.c` is one more file of that archive.
- Linux on x86-64 and AArch64 only. Elsewhere `runtime/wasm.c` is compiled as stubs
  (`TV_NO_WASM`) that report "WebAssembly is not supported on this platform", and WAMR's files
  are left out of the archive, so other targets build as before.
- Instances live in a table of handles, like net.c's sockets (`wasmLoad` returns one; at most 1024
  at once). A trapped instance keeps the state it had at the trap (a module's own stack pointer is
  not restored), so a host that wants to go on after a trap makes a new instance.

## Changes

- `vendor/wamr/**`: WAMR 2.4.5 (the subset above), `vendor/wamr/LICENSE`, `vendor/wamr/TOV.md`.
- `runtime/wasm.c`, `runtime/tov.h`: the natives `wasmLoad`, `wasmHas`, `wasmArity`, `wasmCall`,
  `wasmRead`, `wasmWrite`, `wasmMemSize`, `wasmOutput`, `wasmFree`, `wasmError`, and the WASI subset.
- `crates/tov/src/std/wasm.tov`, `crates/tov/src/driver.rs`, `crates/tov/src/check/builtins.rs`:
  the module and the native signatures.
- `crates/tov/src/codegen/mod.rs`: a program that uses the natives links the TLS archives.
- `crates/tov/build.rs`, `crates/tov/src/tls_flags.rs`: WAMR's sources (and `.s` files), its flags,
  and the platform filter.
- `docs/spec.md`: the `std/wasm` line in §7a.

## Vendored code

| Library | Version | Licence | Where |
|---|---|---|---|
| [WAMR](https://github.com/bytecodealliance/wasm-micro-runtime) | 2.4.5, tag `WAMR-2.4.5` (commit `25bd7eb6`) | Apache-2.0 WITH LLVM-exception | `vendor/wamr/LICENSE`, `vendor/wamr/TOV.md` |

The Apache-2.0 licence asks that the licence text travel with the code (it does) and that changes
to its files be marked; this commit changes none of them (`feat/wasm-time-limit` changes one and
says so in `TOV.md`).

## Tests

`tests/run/native_wasm.tov` (22 checks; its module's C source is `tests/run/native_wasm_module.c`
and its 1,119 bytes are inlined in the test, so the harness needs no clang): i32 calls and sign
extension, i64 arguments and results, `has` and `arity`, the declared memory size, memory written
by each side and read by the other, a trap that leaves the instance usable, division by zero, an
unknown export, an import the host does not provide (traps when called, loads fine), a wrong
argument count, offsets outside memory, the instruction budget, stack exhaustion, memory growth up
to the page limit and not past it, captured output, a closed instance, bytes that are not a
module, and a module whose initial memory is over the limit. Checked by building the branch and
running the program with its compiler (output equal to `native_wasm.stdout`).

## Limits

- Only the interpreter: no AOT or JIT, so a module runs at an interpreter's speed.
- No WASI files, sockets or polling; no threads, SIMD or multi-memory; no floating-point
  arguments or results in `call`; no host functions a program could provide (a module is linked
  against the fixed set above). Memory is read and written by offset, not mapped into Tov.
- No wall-clock limit per call: a call runs on the thread that made it until it returns, traps or
  runs out of fuel. `feat/wasm-time-limit` adds one.
- The vendored files are stated to be WAMR 2.4.5's as released; they were not diffed against the
  tag again when this branch was prepared (no network access to the release here).
