#!/bin/sh
# Runs workstream s3's ported patch tests inside the build container:
#   M/tovbuild.sh M/s3 sh 'sh raiju-tests/run-s3.sh [name...]'
set -u
TOV=${TOV:-/tov/target/release/tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
RC=0
expect() {
  if grep -q "^FAIL" "$1" || [ "$(grep -c "^ok" "$1")" -ne "$2" ]; then
    echo "FAILED: $3"; cat "$1"; RC=1
  else
    echo "passed: $3 ($2 checks)"
  fi
}
want() { [ $# -eq 1 ] && return 0; n=$1; shift; for a in "$@"; do [ "$a" = "$n" ] && return 0; done; return 1; }
if want env "$@"; then
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/process_env.tov" -o "$OUT/process-env" >/dev/null
  RAIJU_PATCH_ENV=fixture RAIJU_PATCH_ENV_EMPTY= "$OUT/process-env" RAIJU_PATCH_ENV > "$OUT/process-env.out"
  expect "$OUT/process-env.out" 1 "dynamic process.env (0024)"
fi
if want fs "$@"; then
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/fs_atomic.tov" -o "$OUT/fs_atomic" >/dev/null
  "$OUT/fs_atomic" > "$OUT/fs_atomic.out"
  expect "$OUT/fs_atomic.out" 17 "node:fs rename and fsync (0009)"
fi
if want flock "$@"; then
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/flock.tov" -o "$OUT/flock" >/dev/null
  "$OUT/flock" "$OUT/flock-own.lck" > "$OUT/flock.out"
  python3 -I -c 'import fcntl, sys, time
f = open(sys.argv[1], "a"); fcntl.flock(f, fcntl.LOCK_EX); print("held", flush=True); time.sleep(30)' "$OUT/flock.lck" > "$OUT/flock_holder.out" & HOLDER=$!
  for i in $(seq 50); do grep -q held "$OUT/flock_holder.out" && break; sleep 0.1; done
  "$OUT/flock" "$OUT/flock.lck" held >> "$OUT/flock.out"
  kill -9 $HOLDER; wait $HOLDER 2>/dev/null || true
  "$OUT/flock" "$OUT/flock.lck" free >> "$OUT/flock.out"
  expect "$OUT/flock.out" 9 "node:fs flockSync (0020)"
fi
if want continue "$@"; then
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/continue_release.tov" -o "$OUT/continue_release" >/dev/null
  "$OUT/continue_release" > "$OUT/continue_release.out"
  expect "$OUT/continue_release.out" 6 "continue releases the loop body's locals (0023, upstream's fix)"
fi
if want gcc "$@" && command -v gcc >/dev/null && command -v valgrind >/dev/null; then
  # 0027: with GCC, a returned record of optional fields keeps every string (valgrind: no read of freed memory)
  TOV_CFLAGS=-DTV_PLAIN_ALLOC CC=gcc "$TOV" build -g "$DIR/gcc_sra.tov" -o "$OUT/gcc_sra" >/dev/null
  valgrind -q --error-exitcode=9 "$OUT/gcc_sra" > "$OUT/gcc_sra.out" 2>&1 || echo "FAIL valgrind reported errors" >> "$OUT/gcc_sra.out"
  expect "$OUT/gcc_sra.out" 1 "GCC build of a returned record (0027)"
fi
if want wasm "$@"; then
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/wasm.tov" -o "$OUT/wasm" >/dev/null
  (cd "$DIR" && "$OUT/wasm") > "$OUT/wasm.out"
  expect "$OUT/wasm.out" 24 "std/wasm (0005, 0010)"
fi
if want rtc "$@"; then
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/rtc.tov" -o "$OUT/rtc" >/dev/null
  "$OUT/rtc" > "$OUT/rtc.out"
  expect "$OUT/rtc.out" 20 "std/rtc (0006)"
fi
exit $RC
