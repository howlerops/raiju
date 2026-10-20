# std/wasm: a wall-clock limit per call

Branch `feat/wasm-time-limit`, one commit on top of `feat/wasm`. Series: [wasm-time-limit/](wasm-time-limit/).
Raiju patch: `0010-wasm-time-limit.patch`.

Depends on: `feat/wasm` (it changes `std/wasm`, `runtime/wasm.c` and the vendored WAMR that
branch adds). Open it after the std/wasm pull request, or fold it into that one.

## What

`instantiate`'s limits take `timeMs`, the most wall-clock milliseconds one call may take, and
`WasmInstance.setTimeLimit(ms)` changes it later (0: no limit). A call past it throws
"time limit exceeded", as a call out of fuel throws "instruction limit exceeded", and the
instance can be called again.

## Why

The instruction budget bounds a call by what it executes, but a call can be slow for other reasons
(a budget set high for a heavy module, an import that takes long), and it holds the thread that
made it. A host that runs module code on a request path needs a time bound per call as well.

## API

```ts
import { instantiate } from "std/wasm"

const m = try instantiate(bytes, { fuel: 200000000, timeMs: 5000 })
m.setTimeLimit(250)                 // changes it (0: no limit)
try m.call("pre_hook", [ptr, len])  // past 250 ms: Error("time limit exceeded")
```

## Design

- `runtime/wasm.c` keeps the deadline of the call in progress (`CLOCK_MONOTONIC` nanoseconds) in
  a global around `wasm_runtime_call_wasm_a`. A call made while another is in progress keeps the
  earlier deadline. The limit is capped at one day.
- WAMR's fast interpreter runs `CHECK_INSTRUCTION_LIMIT` on every instruction when instruction
  metering is on (`feat/wasm` turns it on). The macro now also counts a tick and, every 65536
  instructions while a deadline is set, compares the clock with it and raises
  "time limit exceeded". With no deadline the added cost is one compare.
- This is the one change to WAMR's own files; `vendor/wamr/TOV.md` records it so that an update
  of the library reapplies it.

## Changes

- `runtime/wasm.c`, `runtime/tov.h`: the deadline, `tv_wasm_now_ns`, the `wasmTimeLimit` native
  (and its stub when WAMR is not built).
- `vendor/wamr/core/iwasm/interpreter/wasm_interp_fast.c`: the clock check in
  `CHECK_INSTRUCTION_LIMIT`. `vendor/wamr/TOV.md`: the change noted.
- `crates/tov/src/check/builtins.rs`: the signature.
- `crates/tov/src/std/wasm.tov`: `WasmLimits.timeMs`, `WasmInstance.setTimeLimit`.
- `docs/spec.md`: `timeMs` and `setTimeLimit` in the `std/wasm` line.

## Vendored code

No new library. It modifies one file of WAMR 2.4.5 (Apache-2.0 WITH LLVM-exception); the
change is marked in a comment at the macro and in `vendor/wamr/TOV.md`, as the licence's §4(b)
asks of modified files.

## Tests

`tests/run/native_wasm.tov` gains two checks (24 in all): a loop with no instruction budget ends
with "time limit exceeded" after its 150 ms (between 140 ms and 5 s), and the instance runs again
once the limit is lifted. Checked by building the branch and running the program (output equal to
`native_wasm.stdout`).

## Limits

- The clock is read between instructions only: one host call that blocks is not cut short (the
  call ends at the next check after it returns). The WASI subset has no blocking calls.
- Only the fast interpreter has the check, and it is the only engine built.
- The deadline is a process global: calls are assumed to run one at a time on one thread, as they
  do in Tov today.
