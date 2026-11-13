#!/bin/sh
# Real native console/gateways in internal-only Docker networks. Takes an already-built image.
set -eu
cd "$(dirname "$0")/.."
if [ "$#" != 1 ]; then
  echo 'usage: scripts/check_console.sh <already-built-image>' >&2
  exit 2
fi
if [ -e build/console-preview-access.json ]; then
  echo 'An interactive preview is running; run node tests/console_e2e.mjs directly or stop it first.' >&2
  exit 2
fi
python3 -m unittest discover -s tests -p test_preview_publish.py
mkdir -p build
image=$1
server=${RAIJU_PREVIEW_SERVER:-bun}
set --
if [ "$server" = http1 ]; then
  # Some desktop engines withdraw published ports asynchronously after container removal.
  # Independent test cases must not depend on that teardown timing.
  set -- --console-port 4174 --europe-port 18131 --america-port 18132
fi
python3 scripts/preview_console.py --image "$image" --server "$server" "$@" > build/console-preview.log 2>&1 &
preview=$!
cleanup() {
  kill -TERM "$preview" 2>/dev/null || true
  wait "$preview" || true
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
if ! NODE_PATH="${NODE_PATH:-$(npm root -g)}" node tests/console_e2e.mjs; then
  cat build/console-preview.log
  exit 1
fi
