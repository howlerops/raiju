#!/bin/sh
# Builds Tov with the patches in tov-patches/ (streamed response bodies for
# Bun.serve, child processes as sockets, TLS ALPN, UDP sockets, WebAssembly on WAMR, WebRTC on libdatachannel,
# fetch pool options and HTTP/2, request body streams, node:fs rename and fsync, a WASM time limit, the
# server lifecycle: stop signals, timeouts and a connection cap, a fetch address policy checked at connect time,
# TLS client certificates, Request.signal and gunzip, a small fetch input buffer, server.requestIP, workers
# respawned after SIGKILL with a crash-loop backoff, node:fs flockSync, Math.random seeded from getrandom, the
# address policy on Bun.connect and WebSocket and a write-stall limit on upgraded sockets, `continue` releasing the
# loop body's locals) into
# build/tov/target/release/tov, applied in name order. Raiju needs this build
# until the patches are upstream. Usage: scripts/build-tov.sh  (needs git and cargo)
set -eu
REV=${TOV_REV:-c2048582de4e9468267f801313144d75c12e983f}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIR=$ROOT/build/tov
if [ ! -d "$DIR/.git" ]; then
  git clone --quiet https://github.com/richiemcilroy/Tov "$DIR"
fi
cd "$DIR"
git fetch --quiet origin "$REV" 2>/dev/null || true
git checkout --quiet --force "$REV"
git clean --quiet -fd
for p in "$ROOT"/tov-patches/*.patch; do
  git apply "$p"
done
cargo build --release --quiet
echo "$DIR/target/release/tov"
