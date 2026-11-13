#!/bin/sh
# Focused patch-0026 native Linux regression; no gateway, provider, credentials or external DNS.
set -eu
TOV=${TOV:-tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
TOV_JSC=system TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/clean_workers.tov" -o "$OUT/clean-workers" >/dev/null
${CC:-cc} -shared -fPIC -std=c11 "$DIR/clean_workers_probe.c" -o "$OUT/clean-workers-probe.so" \
  $(pkg-config --cflags --libs javascriptcoregtk-4.1) -ldl
if ! python3 "$DIR/clean_workers_client.py" "$OUT/clean-workers" "$OUT/clean-workers-probe.so" "$OUT/runtime.log"; then
  cat "$OUT/runtime.log"
  exit 1
fi
if ! DNS_BEFORE_LISTENERS=1 python3 "$DIR/clean_workers_client.py" "$OUT/clean-workers" "$OUT/clean-workers-probe.so" "$OUT/async-runtime.log"; then
  cat "$OUT/async-runtime.log"
  exit 1
fi
