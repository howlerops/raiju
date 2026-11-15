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
- JavaScriptCore: v0.1.0 pins the same WebKit release (`webkitgtk-2.54.1`), but its own patch set on
  top changed, so `scripts/build-jsc.sh` has to be run again with the new compiler's
  `scripts/jsc/build.sh`.
- `tov-0.1.0/*.tov` — the modules whose bodies differ between the compilers, to copy over `src/`
  when the build moves: `num.tov` (parseInt/parseFloat return NaN), `bits.tov` (bitwise operators on
  an `int` keep 32 bits) and `text.tov` (string positions are UTF-16 units). Each has the same tests
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
| string positions are UTF-16 units, not bytes | `strLen` in `src/text.tov`; in progress |
