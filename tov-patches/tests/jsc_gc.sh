#!/bin/sh
# Focused patch-0025 regression; no gateway/provider/configuration or credentials are used.
set -eu
TOV=${TOV:-tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
TOV_JSC=system TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/jsc_gc.tov" -o "$OUT/jsc-gc" >/dev/null
EXPECTED=1
if [ "$(uname -s)" = Linux ]; then
  # The same dynamically linked WebKitGTK path used by the production Linux image.
  ${CC:-cc} -shared -fPIC -std=c11 "$DIR/jsc_gc_probe.c" -o "$OUT/jsc-gc-probe.so" \
    $(pkg-config --cflags --libs javascriptcoregtk-4.1) -ldl
  LD_PRELOAD="$OUT/jsc-gc-probe.so" "$OUT/jsc-gc" > "$OUT/result"
  EXPECTED=2
else
  "$OUT/jsc-gc" > "$OUT/result"
fi
if grep -q '^FAIL' "$OUT/result" || [ "$(grep -c '^ok' "$OUT/result")" -ne "$EXPECTED" ]; then
  cat "$OUT/result"
  exit 1
fi
cat "$OUT/result"
