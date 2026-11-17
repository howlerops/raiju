# The move to Tov v0.1.0

Raiju built against Tov at `c2048582` (2026-10-14) with 24 patches until this change; it now builds
against Tov **v0.1.0** (`ca1e3d24c44eb0d81b27cfefd1c308912c1d9f19`) with the patches in
`tov-patches/`. v0.1.0 is 580 commits later and changes the language in ways that matter to Raiju.
This page records what changed, how the source handles it, and what was checked.

## Language differences and how the source handles them

| Tov v0.1.0 | In Raiju |
|---|---|
| arrays, maps, sets and records changed in place are shared, as in JavaScript (they were values, copied on assignment) | copies are explicit: `slice()`, the `copyX` helpers next to each record type (`scripts/copy_lint.py` fails the check when one misses a field) |
| `parseInt`/`parseFloat`/`Number` return `NaN`, and a float (they returned `undefined`, and an `int`) | `strToInt`/`strToFloat` in `src/num.tov`: exact 64-bit integers, strict floats, `undefined` for text that is not a number |
| `number` is an `int` where only integers reach it | annotations say `f64` |
| `& \| ^ ~ << >>` on an `int` keep 32 bits (they kept 64) | `bitAnd`, `bitOr`, `bitXor`, `bitNot`, `bitShl`, `bitShr` in `src/bits.tov`; a mask with a constant up to `0x7fffffff` stays an operator |
| string positions are UTF-16 units (they were bytes); a slice cannot cut a character | `strLen` and the byte/position helpers in `src/text.tov`; byte-exact work is done on `u8[]` |
| `xs[i]` past either end traps unless the code around it expects `undefined` (it was `undefined`) | `elemAt` in `src/arrays.tov` |

New code should follow the right-hand column. `docs/tov-0.1.0-audit/` keeps the per-site verdicts of
the reviews for shared values and string positions.

The JSON scanner caches whether byte offsets already equal string positions and skips conversion on that
path. `asciiShape` returns ASCII input before constructing a character array. The process-local MCP
tool-name memo keeps at most 4,096 entries and 1 MiB of definition/name text, and does not retain entries
larger than 64 KiB; larger tool definitions still work but are parsed without memoization. These bounds
limit memo retention, not the size of tool definitions accepted from an MCP server.
When full, the memo keeps its warm entries and parses uncached definitions without admitting them;
walking a working set larger than the budget does not repeatedly evict the whole cache.

## The compiler patches

`tov-patches/` holds the patches re-derived for v0.1.0 (see its README and `PORT-NOTES-*.md`). Two of
the changes fix bugs in Tov itself that Raiju's tests found on v0.1.0:

- an `async` function run as a task, or a generator, that reassigns a reference-counted parameter
  released the new value twice: a use-after-free (a redacted prompt reached the provider as freed
  memory in the end-to-end suite);
- awaiting a promise whose result is a record held as an object leaked the default object made for
  the result (about 385 bytes a request in the memory soak).

Both are in v0.1.0 and in upstream at `1959aef`. JavaScriptCore is the same WebKit release as before
(`webkitgtk-2.54.1`), rebuilt with v0.1.0's own patch set by `scripts/build-jsc.sh`.

## What was checked

The source was changed first, in steps that leave behaviour on the old compiler unchanged, and each
step passed the unit and end-to-end suites there. On v0.1.0, x86-64 Linux:

- unit suite, both end-to-end suites (Bun server and the HTTP/1 server), the browser suite;
- the end-to-end suite under AddressSanitizer and LeakSanitizer (an unoptimised GCC build): no memory
  errors; what LeakSanitizer lists at exit is uncollected cycles, and the soaks show no growth;
- the memory soaks (chat, per-request slope, WebSocket sessions, request bodies);
- `bench/tokbench.py`, one worker, 16 clients, 200-token answers, against the old compiler:

| | old | v0.1.0 |
|---|---|---|
| streaming, logging off | 273k tokens/s, first token 11.1 ms, 25 MB | 348k tokens/s, 8.4 ms, 21 MB |
| streaming, logging on | 221k tokens/s, 13.7 ms, 42 MB | 266k tokens/s, 11.6 ms, 34 MB |
| plain, logging off | 9,702 requests/s, 24 MB | 11,358 requests/s, 19 MB |
| plain, logging on | 7,698 requests/s, 51 MB | 8,917 requests/s, 39 MB |

Behaviour that changed for callers, all for non-ASCII input: paths that trapped on a slice inside a
character (ending the worker) now answer; text cut to a byte cap ends on a character boundary;
`maskSecret` counts characters.

Not checked: macOS code paths of the patches, HTTP/2 against real servers.
