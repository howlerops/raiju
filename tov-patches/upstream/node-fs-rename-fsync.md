# node:fs: rename, file descriptors and fsync, for files replaced atomically

Branch `feat/node-fs-rename-fsync` (one commit on c2048582). Series: [node-fs-rename-fsync/](node-fs-rename-fsync/).
Raiju patch: `0009-fs-rename-fsync.patch`.

Depends on: nothing; it applies to c2048582 on its own. (In Raiju's series it comes last only
because it adds lines to the shared native table and `tov.h`.)

## What

`node:fs` gains `renameSync`, `rename` (callback), `openSync`, `writeSync`, `fsyncSync`,
`fdatasyncSync`, `closeSync` and `chmodSync`; `writeFileSync` takes `{ mode, flush }`; and
`Stats` has `mode`.

## Why

`node:fs` could write a file only in place (`writeFileSync` truncates, then writes) and had no
rename or fsync. A program that rewrites a state file leaves it truncated or half-written if it dies
mid-write, and a reader at that moment sees the same. The usual cure, write a temporary file, fsync
it, rename it over the target and fsync the directory, needs these calls.

## API

Node's:

```ts
import { renameSync, rename, openSync, writeSync, fsyncSync, fdatasyncSync, closeSync, chmodSync, writeFileSync, statSync } from "node:fs"

writeFileSync(dir + "/.state.json.tmp", text, { mode: 0o600, flush: true })  // mode of a created file; fsync before returning
renameSync(dir + "/.state.json.tmp", dir + "/state.json")    // POSIX rename: replaces the target in one step
const fd = openSync(dir, "r")                                 // "r" opens a directory too
fsyncSync(fd)                                                 // the rename itself survives a power cut
closeSync(fd)

const f = openSync(path, "wx", 0o644)  // r, r+, w, wx, w+, wx+, a, ax, a+, ax+
writeSync(f, "text or bytes")          // writes all of it; returns the bytes written
fdatasyncSync(f)
closeSync(f)
rename(a, b, (err) => {})              // the callback form (runs as a microtask)
chmodSync(path, 0o600)
statSync(path).mode                    // st_mode: type and permission bits
```

Errors carry Node's messages: `ENOENT: no such file or directory, rename 'a' -> 'b'`,
`EBADF: bad file descriptor, fsync`, `EEXIST: file already exists, open 'x'`.

## Design

- New natives in `runtime/tov.c`: `rename`, `chmod`, `open`, `writeFd`, `fsync`, `close`.
- `open` maps Node's flag strings to `open(2)` flags with `O_CLOEXEC`; an unknown string is
  `EINVAL`. `writeFd` retries short writes and `EINTR`. `fsync` takes a data-only flag for
  `fdatasync`, and uses `F_FULLFSYNC` on macOS, where plain `fsync` stops at the drive's cache.
- `writeFileSync` keeps its old path (`fopen`) when no option is given, and goes through
  open/write/fsync/close when `mode` or `flush` is.
- The `statSync` payload gains `st_mode`. The error table learns `EBADF`, `EXDEV` and `EINVAL`, and
  messages name both paths for rename and the call for descriptor errors, as Node's do.

## Changes

- `runtime/tov.c`, `runtime/tov.h`: the natives, two-path and descriptor error messages, `st_mode`.
- `crates/tov/src/check/builtins.rs`: the signatures.
- `crates/tov/src/std/fs.tov`: the functions, `writeFileSync`'s options, `Stats.mode`.
- `docs/spec.md`: the `node:fs` line.
- `tests/run/native_fs_atomic.tov` (+ `.stdout`).

## Vendored code

None.

## Tests

`tests/run/native_fs_atomic.tov` (17 checks, in a directory of its own under `/tmp`): rename over
an existing file, the two-path ENOENT message, a file onto a directory (EISDIR, both left alone),
open/write/fsync/fdatasync/close and the created file's mode, `wx` on an existing file, `a`
appending, unknown flags (EINVAL), a directory opened and fsynced, fsync and close on a closed
descriptor (EBADF), `writeFileSync` with mode and flush, `chmodSync`, `writeFileSync` without
options keeping the mode, a flush to a missing directory, and the callback form with and without
an error. Checked by building the branch and running the program (output equal to
`native_fs_atomic.stdout`; `fs_bytes` still passes).

## Limits

- POSIX only, as the rest of Tov's file API (Windows' rename does not replace an existing file).
- No `fs.promises`, no `readSync` or positioned writes, no `encoding` or `flag` options on
  `writeFileSync`.
