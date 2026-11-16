# Port notes — workstream s3 (vendored libraries and the small standalone patches)

Branch `port-s3`, on upstream Tov v0.1.0 (`ca1e3d2`). One commit per patch (or pair). Tests are in
`raiju-tests/`; `raiju-tests/run-s3.sh` runs them in the build container:

    M/tovbuild.sh M/s3 sh 'sh raiju-tests/run-s3.sh'            # all
    M/tovbuild.sh M/s3 sh 'sh raiju-tests/run-s3.sh wasm rtc'   # some of: env fs flock continue gcc wasm rtc

| Patch | Status | Commit subject |
|---|---|---|
| 0027 GCC `-fno-tree-sra` | PORT | `port 0027` |
| 0023 `continue` releases locals | DROP (fixed upstream) | `drop 0023` |
| 0024 `process.env[name]` | PORT | `port 0024` |
| 0025 WebKitGTK main run loop | PORT (applies as is) | `port 0025` |
| 0009 node:fs rename/descriptors/fsync | PORT (not a drop: see below) | `port 0009, 0020` |
| 0020 `flockSync` | PORT | `port 0009, 0020` |
| 0005 WAMR / `std/wasm` | PORT | `port 0005, 0010` |
| 0010 wasm wall-clock limit | PORT | `port 0005, 0010` |
| 0006 libdatachannel / `std/rtc` | PORT | `port 0006` |
| (not a patch) `-DTV_PLAIN_ALLOC` crash in v0.1.0 | s1's fix, cherry-picked | `port 0019 (prerequisite): TV_PLAIN_ALLOC ...` |

No Tov-level API of these patches changed: every call shape Raiju uses from them is as before.
`tov check /raiju/src` with this branch's compiler reports 250 errors in 42 of 229 files, none of them about
`node:fs`, `std/wasm`, `std/rtc` or `process.env`; what is left belongs to the other workstreams' patches
(`RequestInit.peer`/`pool`, `Bun.*`, request body streams, ...) and to language changes (`parseInt` now
returns a float, JSON conversions of `LogEntry`).

## Findings that concern all workstreams

1. **`TOV_CFLAGS=-DTV_PLAIN_ALLOC` is broken in unmodified v0.1.0.** Raiju's patch tests are all built with
   it. In v0.1.0 the flag reaches only the runtime (`tv_small_free` becomes `free`), while generated code
   (`tvg_alloc_small`, `TVG_ENV_SIZE` in `codegen/prelude.h`) and array buffers (`tov.h`) still take blocks
   from the small-object lists, switched to malloc only under AddressSanitizer. A closure environment made
   by generated code and released by the runtime is then passed to `free()` in the middle of a slab:
   `free(): invalid pointer`, abort. Reproduced on the untouched v0.1.0 build with eight lines
   (`queueMicrotask(() => { cb(...) })` twice, nested). s1 found the same and fixed it in its commit
   `c3105cd` ("port 0019 (prerequisite): TV_PLAIN_ALLOC as a coherent user flag"). This branch first had a
   fix of its own on the same two lines (`411074f`); it is reverted (`8eae71d`) and s1's commit is
   cherry-picked in its place (`6790fba`), so the two branches merge without a conflict there. All
   results below are from the compiler rebuilt after that.
2. **The build container's JavaScriptCore does not fit v0.1.0.** See "0025" below: `$TOV_JSC_DIR` holds
   the engine built from the *old* pin's `scripts/jsc` patches. Any program that imports an npm package or a
   JavaScript-backed `node:` module fails to compile with this compiler until the engine is rebuilt.
3. **`node:fs` in v0.1.0 has no rename/fsync for Tov code** (the brief assumed it had). They exist only in
   the JavaScript `node:fs` that npm packages get (`runtime/node/fs.js`, `runtime/node.c`); a `.tov`
   import of `node:fs` is always `std/fs.tov`, which has neither. 0009 is therefore a port, not a drop.

## 0027 — GCC: no scalar replacement of aggregates — PORT

- v0.1.0 assembles the C flags in `crates/tov/src/rt_flags.rs` (`base_flags`), shared by `tov build`
  (`src/build.rs`, `Toolchain::new`) and the cargo build script, which precompiles the runtime with the same
  flags. Added `rt_flags::is_gcc(cc)` (the patch's test: `cc --version`, never on Apple) and
  `rt_flags::compiler_flags(cc)`, appended after `base_flags` in both places, so the flag is in the runtime's
  cache key and a GCC-built prebuilt runtime still matches.
- Files: `crates/tov/src/rt_flags.rs`, `crates/tov/src/build.rs`, `crates/tov/build.rs`.
- Tested: with `CC` set to a wrapper around gcc 13.3 that logs its arguments, all 4 compile/link commands
  carry `-fno-tree-sra`; with clang (the default: v0.1.0 picks a clang before `cc`) none does and builds work.
  `raiju-tests/gcc_sra.tov` (1 check, `run-s3.sh gcc`: built with `CC=gcc`, run under valgrind) passes.
- **Is it still needed? Not shown either way.** v0.1.0 now prefers clang on Linux, so GCC is used only when
  `CC` says so or no clang is installed. I could not reproduce the miscompile on v0.1.0: `gcc_sra.tov` has
  Raiju's `parseQuery` shape (fifteen optional fields, filled from a `URLSearchParams`, returned), and GCC
  13.3 at `-O2` and `-O3` runs it clean under valgrind **with and without** the flag (the flag stripped by a
  wrapper). The reason is visible in the generated C: that record is now a counted heap object
  (`O33_Q*`, one pointer retained on return), not a 312-byte struct copied field by field. I did not
  establish that no by-value record copy of the miscompiled shape remains anywhere in generated code
  (smaller records and unions may still be structs), so the flag is kept, as the brief's default says.
- Note: with `CC` set to a compiler whose file name does not contain "clang", v0.1.0 itself passes
  GCC-only flags (`-fno-tree-loop-distribute-patterns`); a clang behind another name fails. Upstream's, not ours.

## 0023 — `continue` releases the loop body's locals — DROP

- Upstream has the same fix: `loop_body_with_binding` in `crates/tov/src/codegen/body.rs` pushes the
  continue target at `depth - 1`, with a comment naming the leak.
- Tested: `raiju-tests/continue_release.tov` unchanged, 6/6 (each loop kind, async, kept values). Under
  valgrind: 0 bytes definitely or indirectly lost, no invalid access. (Under valgrind the first RSS check
  reads +26 MB, below the 64 MB a leak would give and above the test's 16 MB bound: valgrind's allocator
  keeps freed memory. Run natively it passes.)
- Raiju: nothing to adapt.

## 0024 — dynamic `process.env[name]` — PORT

- Upstream compiles only `process.env.NAME` (`MemberFact::Env`). Ported as the patch has it: a string index
  on the `env` namespace type-checks to `string | undefined` (`check/expr.rs`, before the array/record index
  cases) and lowers to the same `tv_process_env` call (`codegen/body.rs`, top of `index`); the runtime
  refuses names with a NUL byte.
- Files: `crates/tov/src/check/expr.rs`, `crates/tov/src/codegen/body.rs`, `runtime/tov.c`.
- Tested: `raiju-tests/process_env.tov` unchanged, 1/1 (inherited, empty, missing, literal parity, three NUL
  cases); clean under valgrind.
- Raiju: nothing to adapt. Assignment to `process.env[...]` remains unsupported, as before.

## 0025 — WebKitGTK main thread and run loop — PORT (applies textually)

- The patch concerns only the *system* WebKitGTK path of `runtime/js.c` (`!__APPLE__ && !TV_JSC_OWN`).
  v0.1.0 still creates its GLib context there without `WTF::initializeMainThread()`.
- Still needed: in an image with Ubuntu 24.04's `libjavascriptcoregtk-4.1-dev` (2.52.6) added,
  `raiju-tests/jsc_gc.sh` (built with `TOV_JSC=system`) **segfaults on unmodified v0.1.0** in the probe that
  constructs the memory-pressure singleton and runs a full collection, and prints its 2 `ok` lines with the
  patch. (The image is `raiju:dev4-s3sysjsc`, made locally from `raiju:dev4` with apt; `raiju:dev4` itself
  has no system JavaScriptCore, so `run-s3.sh` does not run this test.)
- Files: `runtime/js.c`. Test: `raiju-tests/jsc_gc.{sh,tov}`, `jsc_gc_probe.c`, `node_modules/jsc-gc-check`.
- Tov's own engine (`TV_JSC_OWN`, what Raiju ships) does not take this path: `TVInitialize()` in
  `scripts/jsc/patches/TovAPI.cpp` calls `JSC::initialize()` and `RunLoop::initializeMain()` itself.
  **Not run**: the own-engine path, because the container's engine is the old pin's (next paragraph).

### Which JavaScriptCore v0.1.0 expects

- `scripts/jsc/build.sh` pins `TAG=webkitgtk-2.54.1` (WebKit's JSCOnly port), the same release as the old
  pin and as Raiju's `scripts/build-jsc.sh` (`WEBKIT_TAG=webkitgtk-2.54.1`, commit `628d6ce`). The Tov
  patches on top of it changed: `scripts/jsc/patches/{tov.patch, TovAPI.cpp, TovAPI.h}` differ (tov.patch by
  316 diff lines), and `TovAPI.h` gained `TVGetPropertyCached`, `TVHasImminentWork`, `TVHeapStatistics`,
  `TVMakeString`, `TVReadCached`. The engine's `VERSION` is `<tag> <cksum of tag + patches>`:
  v0.1.0 expects `webkitgtk-2.54.1 3218338362`; the container's `$TOV_JSC_DIR/VERSION` says
  `webkitgtk-2.54.1 678799261`, which is the old pin's checksum.
- Effect, observed: `tov build` of any program with npm/JavaScript warns "Tov's JavaScriptCore in
  /src/build/jsc/current is older than this compiler (its TovAPI.h differs)" and then fails to compile
  `node.c` (`call to undeclared function 'TVHeapStatistics'`). The engine must be rebuilt from v0.1.0's
  `scripts/jsc` (Raiju: `make jsc` / `scripts/build-jsc.sh` after `build/tov` is the new Tov; its tag check
  still passes; about 15 minutes on four cores by that script's own comment, and it clones WebKit).
- **What Raiju's `scripts/build-jsc.sh` has to change: nothing.** `WEBKIT_TAG=webkitgtk-2.54.1` and
  `WEBKIT_COMMIT=628d6ce1850e17225185a5807a9d0aa375bae2be` are still right: v0.1.0's `TAG` is the same, and
  `git ls-remote` today gives `628d6ce1850e…` for `refs/tags/webkitgtk-2.54.1^{}`. The script runs
  `build/tov/scripts/jsc/build.sh`, so once `build/tov` is v0.1.0 (plus patches) the same command builds
  the right engine; what must happen is a rebuild (`make jsc`, and the image layer that holds
  `/src/build/jsc`), because the patch set under the tag changed. The build flags are upstream's and
  unchanged in kind: `-DPORT=JSCOnly -DENABLE_STATIC_JSC=ON -DENABLE_FTL_JIT=ON -DUSE_THIN_ARCHIVES=OFF
  -DDEVELOPER_MODE=OFF -DENABLE_API_TESTS=OFF -DENABLE_TOOLS=OFF`, clang, ICU from `libicu-dev`.
  One thing to decide: v0.1.0 also writes `order.txt` beside the engine on Linux and links with it when it
  is there; `build-jsc.sh` deletes nothing of it, so it comes along.
- **What the runtime needs of the engine.** `runtime/js.c`, `node.c` and `napi.c` call 17 `TV*` functions
  of `TovAPI.h`; the container's engine lacks five of them: `TVGetPropertyCached`, `TVHasImminentWork`,
  `TVHeapStatistics`, `TVMakeString`, `TVReadCached`. They are Tov's own additions
  (`scripts/jsc/patches/TovAPI.cpp`), in no WebKit release, so no stock WebKit version supplies them: the
  own-engine path needs exactly tag `webkitgtk-2.54.1` with v0.1.0's `scripts/jsc/patches`. The runtime
  also names three C++ symbols directly: `JSC::VM::deleteAllCode`, `WTF::releaseFastMallocFreeMemory`, and
  (0025, system path) `WTF::initializeMainThread`. The system path (`TOV_JSC=system`) needs only the public
  C API of `javascriptcoregtk-4.1` or `6.0`; it built and ran here with Ubuntu 24.04's 2.52.6.
- **Recipe verified as far as configure, not built.** In `raiju:dev4` (which has cmake, ninja, ruby, perl,
  python3, clang, lld, libicu-dev) I ran v0.1.0's `scripts/jsc/build.sh` cut off before `cmake --build`:
  the sparse clone of the tag succeeds through the proxy (`GIT_SSL_CAINFO` set to the proxy CA; 278 MB),
  HEAD is `628d6ce1850e17225185a5807a9d0aa375bae2be`, `patches/tov.patch` applies cleanly, the version
  comes out `3218338362`, and CMake configures (`ENABLE_STATIC_JSC ON`, "Build files have been written").
  The compile itself (`cmake --build … --target JavaScriptCore JavaScriptCoreJIT`, then the packaging into
  `libtovjsc.a`) was **not** started: it is the long step and would have taken the cores the three
  workstreams share. Until it is run, nothing JavaScript-backed is verified on the own-engine path with
  v0.1.0 (0025's fixture, s1's 0026, the 10 `run` cases below).
- New in v0.1.0's script: `linux-release` (an engine built on Ubuntu 22.04 with ICU, libstdc++ and
  libatomic bundled in `lib/`, linked statically and `-no-pie`), `order.txt` (a function order for lld,
  from `scripts/jsc/order-linux.txt`), optional PGO (`TOV_JSC_PGO`). Without bundled ICU the link uses
  static ICU if the system has `libicu*.a` (the container does), else dynamic.
- Pins: the WebKit tag in `scripts/jsc/build.sh`; base images in `scripts/jsc/Dockerfile.linux`
  (`debian:trixie`) and `Dockerfile.linux-release` (`ubuntu:22.04`); `scripts/release/package.sh` ships the
  engine as `tov-jsc-<os>-<arch>.tar.gz`. The repository has no CI configuration (`.github` is absent), so
  nothing there pins or tests an engine. The tag is not pinned to a commit by upstream (Raiju's script is).
- The system fallback is unchanged: pkg-config `javascriptcoregtk-4.1`, then `6.0`, any version.

## 0009 — `node:fs` rename, descriptors, fsync — PORT

- Upstream's `std/fs.tov` has `readFileSync, readFileBytesSync, writeFileSync(path, data), appendFileSync,
  existsSync, readdirSync, mkdirSync, unlinkSync, rmSync, statSync (size, mtimeMs, isFile, isDirectory),
  accessSync` and nothing else. Everything the patch added was missing, including what Raiju fails to
  type-check on plain v0.1.0: `closeSync`, `openSync`, `chmodSync`, `writeFileSync`'s third argument
  (`{ mode, flush }`) and `Stats.mode` — all five come from this patch (0009), none from another.
- Ported unchanged in API and behaviour: `renameSync`, `rename(from, to, cb)`, `chmodSync`,
  `openSync(path, flags?, mode?)` (`O_CLOEXEC`; `r` opens a directory), `writeSync`, `fsyncSync`,
  `fdatasyncSync` (`F_FULLFSYNC` on macOS), `closeSync`, `writeFileSync(path, data, { mode, flush })`,
  `Stats.mode`; Node's messages for two-path and descriptor errors; EBADF, EXDEV, EINVAL in the error table.
  The natives are the patch's C, placed after `tv_native_access`. `statSync` parses the mode with
  upstream's NaN-aware idiom (`Math.trunc(parseInt(..) || 0)`).
- Files: `runtime/tov.c`, `runtime/tov.h`, `crates/tov/src/check/builtins.rs`,
  `crates/tov/src/std/fs.tov`, `docs/spec.md`.
- Tested: `raiju-tests/fs_atomic.tov` unchanged, 17/17, with and without `-DTV_PLAIN_ALLOC`, with clang and
  with gcc; clean under valgrind. (It was this test that showed the `TV_PLAIN_ALLOC` crash above: `rename`'s
  callback runs from `queueMicrotask`.)
- Raiju: nothing to adapt.

## 0020 — `flockSync` — PORT

- Ported unchanged: `flockSync(fd, "ex" | "sh" | "un", waitMs?)` → `bool`, the native `flock` with the
  patch's retry (1 ms doubling to 16 ms), `EBADF: bad file descriptor, flock` on a bad descriptor.
- Files: the same five as 0009 (one commit with it: the natives share helpers and sit together).
- Tested: `raiju-tests/flock.tov` unchanged with `run.sh`'s three phases (own descriptors; a lock held by a
  Python process; that process killed with SIGKILL): 9/9.
- Raiju: nothing to adapt.

## 0005 — WebAssembly (`std/wasm` on WAMR) — PORT

- **What upstream did with WebAssembly: nothing native.** `std/wasm.tov` was never upstream's (the patch
  added it); v0.1.0 has no WebAssembly engine of its own and no `std/wasm`. The only WebAssembly in v0.1.0
  is JavaScriptCore's, reachable from JavaScript in npm packages (the bundler copies `.wasm` assets;
  `runtime/js.c` pumps the engine's off-thread compilation). Using that from Raiju would mean linking the
  engine into the plugin path and writing the limits (fuel, pages, stack, time) in JavaScript, which
  JavaScriptCore does not offer per instance. So WAMR is ported.
- What Raiju needs (`src/wasmplugin.tov`): `instantiate(bytes, { stackBytes, maxPages, fuel, timeMs })`,
  `WasmInstance.{has, arity, call, read, write, memorySize, output, close}`, the types `WasmInstance` and
  `WasmLimits`. All present with the same signatures; `wasmplugin.tov` type-checks against this branch.
- Carried over as they were: `vendor/wamr` (WAMR 2.4.5, 112 files, with 0010's change), `runtime/wasm.c`,
  `crates/tov/src/std/wasm.tov`, the natives' signatures and declarations.
- Re-derived for v0.1.0:
  - `crates/tov/src/tls_flags.rs`: WAMR's include directories, `WASM_SUPPORTED`, `WAMR_C`, `wanted`, the
    language flags and WAMR's flags in the vendored archive's key. `crates/tov/build.rs`: the `wamr`
    directory, `.s` files, `runtime/wasm.c`, the `wanted` filter. New in v0.1.0 is `compile_archive` (the
    build script precompiles the vendored archive the compiler embeds): it called `tls_flags::lang` with an
    absolute path, now with the repository-relative one, which `lang` needs to tell WAMR's files.
    So WAMR is now precompiled into the compiler; a program's first build does not compile it.
  - `crates/tov/src/codegen/mod.rs`: a program calling `tv_native_wasm*` links the TLS archives.
    `crates/tov/src/driver.rs`: `std/wasm`.
  - `runtime/wasm.c`: arrays are shared references in v0.1.0 with the length in the buffer
    (`tv_arr_len`, `a.p->len`), and an empty result is a fresh array, not the shared empty one.
  - **Native stack check (new problem).** v0.1.0 runs a program on a 1 GiB stack it maps itself on the main
    thread (`tv_run_on_stack`). WAMR finds its stack limit with `pthread_getattr_np`, which describes the
    thread's original stack, so every `instantiate` failed with "native stack overflow". Now the runtime
    records that stack (`tv_stack_lo`, `tv_stack_hi` in `runtime/tov.c`/`tov.h`), and WAMR's
    `os_thread_get_stack_boundary` (`vendor/wamr/core/shared/platform/common/posix/posix_thread.c`, a
    second local change to the vendored tree, marked "Tov:") first asks `tv_wasm_stack_boundary()` in
    `runtime/wasm.c`: on the runtime's stack, 64 KiB above its guard page and at most 8 MiB below the
    caller; elsewhere NULL and WAMR does as before. (Written with integer comparisons: GCC folded the
    pointer comparisons of the first version and the check failed again in GCC builds.)
- Limits are as in the patch and enforced (tests below): `maxPages`, `stackBytes`, `fuel`, the WASI subset,
  no host imports. Security behaviour is unchanged.
- Tested: `raiju-tests/wasm.tov` with `wasm_mod.wasm` unchanged, 24/24 (with 0010's two), with
  `-DTV_PLAIN_ALLOC` and without, with clang and with gcc; valgrind: 0 errors, nothing lost.
- Not covered / open: Linux x86-64 and AArch64 only, as before (elsewhere the `TV_NO_WASM` stubs; not built
  here). AArch64 not built here (x86-64 container). Under a sanitizer build v0.1.0 does not switch stacks,
  so WAMR uses the thread's stack as before (not run).

## 0010 — a wall-clock limit per WebAssembly call — PORT (with 0005)

- Preserved exactly: `WasmLimits.timeMs`, `WasmInstance.setTimeLimit(ms)`, the `wasmTimeLimit` native, the
  deadline around `wasm_runtime_call_wasm_a` (a nested call keeps the earlier deadline), the clock check
  every 65536 instructions in WAMR's fast interpreter (`CHECK_INSTRUCTION_LIMIT`), the one-day cap, the
  "time limit exceeded" trap. Same commit as 0005 (the files are the same).
- Tested: the two checks in `wasm.tov`: a loop with no instruction budget and `timeMs: 150` ends with
  "time limit exceeded" after at least 140 ms and under 5 s; and the instance's limit is changed with
  `setTimeLimit`. Both pass (part of the 24).
- Limits as before: the clock is read between instructions only, so one blocking host call is not cut short.

## 0006 — WebRTC (`std/rtc` on libdatachannel) — PORT

- Upstream has no WebRTC. Carried over byte for byte: `vendor/rtc` (libdatachannel v0.24.6, libjuice,
  usrsctp, libsrtp 2.8.0, plog; 318 files, identical to the patched tree), `runtime/rtc.c`.
- Re-derived for v0.1.0:
  - `runtime/net.c`: the `rtc*` natives and the wake pipe, before "the loop's hooks"; arrays the new way
    (`tv_arr_fresh`, `bytes.p->len`, `tv_arr_len`). `runtime/tov.h`: the operations table and declarations.
  - `crates/tov/src/check/builtins.rs`: signatures. `driver.rs`: `std/rtc`. `codegen/mod.rs`:
    `tv_rtc_install(); tv_tls_install();` for programs that call `rtcPeer`.
  - `crates/tov/build.rs`: `rtc_files` (the sources embedded, `RTC_KEY`). `crates/tov/src/build/rtc.rs`:
    the archive, as it was, with upstream's `tmp_tag()` for temporary names. `crates/tov/src/build.rs`:
    the archive built before the parallel compile, linked in front of the TLS archives, its key in the
    binary's key, and no `_ZdlPvm` stub for these programs (libdatachannel brings libstdc++'s). v0.1.0 also
    defines `_ZSt24__throw_out_of_range_fmtPKcz` in that same block, so it is skipped with it.
  - `crates/tov/src/std/rtc.tov`: one language adaptation — `parseInt` returns a float that may be NaN, so
    `RTCTrack.payloadType` and `remoteMaxMessageSize` convert explicitly (same results: -1 and 0 when unknown).
- Tov-level API unchanged: `RTCPeerConnection`, `RTCDataChannel`, `RTCTrack`, `RTCConfig` and every member
  Raiju's `src/webrtc.tov` uses.
- Tested: `raiju-tests/rtc.tov` unchanged, 20/20 (two peers on loopback: offer/answer, text and bytes both
  ways, Opus RTP with rewritten SSRC and payload type, states, selected pair, close). The first build
  compiles the archive (a few minutes; cached by key afterwards).
- Also built with `CC=gcc` (GCC 13.3 compiles the whole archive): 20/20.
- Not covered / open: x86-64
  only; macOS flags untested, as in the patch; Raiju's aiortc end-to-end tests not run (they need the whole
  gateway). The compiler binary grows by the embedded sources (76 MB → 85 MB with WAMR precompiled too).

## Test results

Compiler: this branch at its head, built in `raiju:dev4` (x86-64, clang 18.1.3; gcc 13.3 where said).

`raiju-tests/run-s3.sh` (expected counts are `run.sh`'s):

| Test | Checks | Result |
|---|---|---|
| `process_env.tov` (0024) | 1 | pass |
| `fs_atomic.tov` (0009) | 17 | pass |
| `flock.tov` (0020), three phases | 9 | pass |
| `continue_release.tov` (0023, upstream's fix) | 6 | pass |
| `gcc_sra.tov` (0027; `CC=gcc`, valgrind) | 1 | pass |
| `wasm.tov` (0005, 0010) | 24 | pass (also without `-DTV_PLAIN_ALLOC`, and with `CC=gcc`) |
| `rtc.tov` (0006) | 20 | pass (also with `CC=gcc`) |
| `jsc_gc.sh` (0025; needs the system WebKitGTK, image `raiju:dev4-s3sysjsc`) | 2 | pass; segfault without the patch |

The test programs are the ones in `/home/user/raiju/tov-patches/tests`, unchanged (none needed adapting to
the new language); `gcc_sra.tov` is new.

Upstream suites (`cargo test --release --test <name>`):

| Suite | Result |
|---|---|
| `run` | 375 programs, 10 failed: `js_callback_trap`, `js_fused_read_uncaught`, `js_read_errors`, `js_read_uncaught`, `native_js_loop_overflow`, `native_js_loop_remainder_zero`, `native_trap_js_int8array_u8s`, `native_trap_js_object_u8s`, `npm_const_throws`, `stdin` — all ten with the engine error above (`TVHeapStatistics` undeclared). Three of them (`stdin`, `js_read_errors`, `npm_const_throws`) were built with the unmodified v0.1.0 compiler and fail the same way; the other seven were not checked against it one by one. |
| `ui` | 25 cases, 0 failed, after updating `tests/ui/imports.out`: the "available:" list of standard modules now ends `std/crypto, std/wasm, std/rtc` (commit `tests: the list of standard modules ...`). |
| `cli` | 5 passed |
| `async` | 12 programs, 0 failed |
| `robustness` | 22010 mangled inputs, no panics |
| `http` | 0 failed on a run of its own. A first run, in parallel with `fetch` and while the other workstreams' containers were testing on the same host network, reported 1 failure; I did not capture which case, and it did not recur. |
| `fetch` | 5 programs, 0 failed on a run of its own; 1 failure in that same parallel run, likewise not captured. |

`npm`, `parity` were not run (they need the engine, or Node/Bun).
