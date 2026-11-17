#!/bin/sh
# Builds Tov v0.1.0 with the patches in tov-patches/ into build/tov/target/release/tov, applied in name
# order: 0001 is Raiju's runtime, standard-library and compiler changes (tov-patches/README.md lists them:
# streamed bodies, child processes as sockets, ALPN, UDP, WebAssembly on WAMR, WebRTC on libdatachannel, the
# fetch pool and HTTP/2, request body streams, the server lifecycle, the address policy checked at connect
# time, client certificates, worker supervision, flockSync, random seeding, GCC without scalar replacement,
# and two fixes for upstream bugs); 0002-0004 vendor C libraries, and 0005 fixes string-view cache lifetime.
# Raiju needs this build until the patches are upstream. Usage: scripts/build-tov.sh  (needs git and cargo)
set -eu
REV=${TOV_REV:-ca1e3d24c44eb0d81b27cfefd1c308912c1d9f19}
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
