# Moving Raiju to Tov v0.1.0 (work in progress)

Raiju builds against Tov pinned at `c2048582` plus `tov-patches/`. This directory holds what is
needed to build it against upstream Tov **v0.1.0** (`ca1e3d24c44eb0d81b27cfefd1c308912c1d9f19`)
instead. Nothing here is used by the build yet: `scripts/build-tov.sh`, the Dockerfile and CI still
use the pinned compiler, and stay that way until every gate passes on the new one.

- `tov-0.1.0/patches/` — Raiju's compiler and runtime patches re-derived for v0.1.0, applied in
  order with `git apply` on a v0.1.0 checkout: `0001` is the runtime, standard library and compiler
  changes (every patch of `tov-patches/` except 0023, which upstream fixed itself); `0002`–`0004`
  are the vendored nghttp2, WAMR and libdatachannel trees. `PORT-NOTES-*.md` say, patch by patch,
  what was ported and how it was tested; `tests/` are the patch tests (`run.sh`, `run-s2.sh`,
  `run-s3.sh`).
- An upstream bug fixed in `0001` (present in v0.1.0 and in upstream at `1959aef`): an `async`
  function run as a task, or a generator, that reassigns a reference-counted parameter released the
  new value twice (a use-after-free; Raiju's `externalGuard` hit it). The frame now keeps what it
  was given in a slot of its own. `tests/upstream-bug/` holds the two small programs that show it on
  an unpatched compiler under AddressSanitizer; worth sending upstream.
- A second upstream bug fixed in `0001` (also in v0.1.0 and `1959aef`): awaiting a promise whose
  result is a record held as an object (one changed in place and shared) leaked the default object
  made for the result, one per await. Raiju's request path leaked about 385 bytes a request.
  `tests/upstream-bug/await_object_record_leak.tov` shows it under LeakSanitizer.
- JavaScriptCore: v0.1.0 pins the same WebKit release (`webkitgtk-2.54.1`), but its own patch set on
  top changed, so `scripts/build-jsc.sh` has to be run again with the new compiler's
  `scripts/jsc/build.sh`.
- `tov-0.1.0/*.tov` — the modules whose bodies differ between the compilers, to copy over `src/`
  when the build moves: `num.tov` (parseInt/parseFloat return NaN), `bits.tov` (bitwise operators on
  an `int` keep 32 bits) and `text.tov` (string positions are UTF-16 units; only `strLen`, `posSpan` and `isAscii` differ). Each has the same tests
  as its `src/` twin.
- `audit/` — the per-site verdicts of the review for shared arrays, maps and records.

Language differences that matter to Raiju, and how the source handles each so that one source is
right on both compilers:

| v0.1.0 | In Raiju |
|---|---|
| arrays, maps, sets and changed records are shared, as in JavaScript | copies are explicit (`slice()`, `copyX` helpers; `scripts/copy_lint.py`) |
| `parseInt`/`parseFloat`/`Number` return `NaN`, and a float | `strToInt`/`strToFloat` in `src/num.tov` |
| `number` is an `int` where only integers reach it | annotations say `f64` |
| `& \| ^ ~ << >>` on an `int` keep 32 bits | `src/bits.tov` |
| string positions are UTF-16 units, not bytes | `strLen` and the byte/position helpers in `src/text.tov`; byte-exact work is done on `u8[]` |
| `xs[i]` past either end traps unless the code around it expects `undefined` | `elemAt` in `src/arrays.tov` |
