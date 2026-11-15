#!/bin/sh
# Builds the JavaScriptCore the gateway links statically: WebKit's JSCOnly port at the release Tov pins
# (build/tov/scripts/jsc/build.sh: the engine alone, with no browser code such as WebCore or Skia), as
#   build/jsc/linux-<arch>/{lib/libtovjsc.a, include/, VERSION}     and the link build/jsc/current
# `tov build` uses it when TOV_JSC_DIR names it (the Makefile, the Dockerfile and CI set that), so the
# binary needs no libjavascriptcoregtk from the distribution: the image then carries no WebKitGTK package,
# and the engine is updated here, by moving Tov's pin, not by the distribution's schedule.
# Usage: scripts/build-jsc.sh  (after scripts/build-tov.sh; needs git, cmake, ninja, clang, lld, ruby, perl,
# python3 and libicu-dev; about 15 minutes on four cores)
set -eu
# The commit the release tag must name: a moved tag fails the build instead of changing the engine.
# When TOV_REV moves to a Tov with another WebKit release, set the new release's commit here.
WEBKIT_TAG=webkitgtk-2.54.1
WEBKIT_COMMIT=628d6ce1850e17225185a5807a9d0aa375bae2be
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TOVDIR=$ROOT/build/tov
OUT=${JSC_OUT:-$ROOT/build/jsc}
if [ ! -f "$TOVDIR/scripts/jsc/build.sh" ]; then
  echo "build-jsc: $TOVDIR has no scripts/jsc/build.sh; run scripts/build-tov.sh first" >&2
  exit 1
fi
if ! grep -q "^TAG=$WEBKIT_TAG\$" "$TOVDIR/scripts/jsc/build.sh"; then
  echo "build-jsc: Tov pins another WebKit release than $WEBKIT_TAG; update WEBKIT_TAG and WEBKIT_COMMIT" >&2
  exit 1
fi
mkdir -p "$OUT"
CC=${CC:-clang} CXX=${CXX:-clang++} TOV_JSC_CACHE=$OUT sh "$TOVDIR/scripts/jsc/build.sh"
got=$(git -C "$OUT/src-$WEBKIT_TAG" rev-parse HEAD)
if [ "$got" != "$WEBKIT_COMMIT" ]; then
  echo "build-jsc: $WEBKIT_TAG is commit $got, expected $WEBKIT_COMMIT" >&2
  rm -rf "$OUT"/linux-*
  exit 1
fi
# the sources and objects are not needed to link (several GB)
rm -rf "$OUT"/src-* "$OUT"/build-* "$OUT"/lto-cache-*
dir=$(ls -d "$OUT"/linux-* | head -1)
ln -sfn "$(basename "$dir")" "$OUT/current"
echo "$OUT/current"
