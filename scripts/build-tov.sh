#!/bin/sh
# Builds Tov with the patches in tov-patches/ (streamed response bodies for
# Bun.serve) into build/tov/target/release/tov. Raiju needs this build until
# the patch is upstream. Usage: scripts/build-tov.sh  (needs git and cargo)
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
