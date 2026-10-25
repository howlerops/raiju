#!/usr/bin/env bash
# Runs the checks a contributor runs before a merge, as .github/workflows/ci.yml runs them.
#
# Usage: scripts/ci.sh [stage...]     (no stage: all of them, in this order)
#   tov        build the patched compiler (scripts/build-tov.sh) unless $TOV is already there
#   check      tov check on every source file (never applies fixes)
#   unit       make unit (tov test plus the Python tests)
#   openapi    make openapi-check
#   web        make web-check (the UI bundle and API types are up to date)
#   parity     the docs/parity.md summary is up to date
#   configdoc  docs/config-reference.md is up to date (scripts/gen_config_doc.py --check)
#   deploy     the Dockerfile, compose file and Helm chart (tests/test_deploy.py; helm template needs helm)
#   e2e-bun    tests/e2e.py on the Bun.serve server
#   e2e-http1  tests/e2e.py on the HTTP/1.1 server
#   ui         make ui (headless Chromium through Playwright)
#   soak       optional, not in the default list: tests/soak/soak.py, a memory soak of one worker that fails
#              when RSS grows (about two minutes; make soak)
# scripts/ci.sh tov-key prints the compiler's cache key (Tov's revision, a hash of tov-patches/
# and scripts/build-tov.sh).
#
# Environment: TOV (compiler; default build/tov/target/release/tov), BUN (default: bun on PATH,
# else ~/.bun/bin/bun), CI_LOCK (a file; when set, the stages that bind fixed ports, openapi,
# e2e-* and ui, run under `flock $CI_LOCK`. Leave it unset when the whole script already runs
# under that lock). Stops at the first failing stage; each stage's output is in build/ci/<stage>.log.
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

ALL=(tov check unit openapi web parity configdoc deploy e2e-bun e2e-http1 ui)

export TOV=${TOV:-$ROOT/build/tov/target/release/tov}
export TOV_CFLAGS=${TOV_CFLAGS:--DTV_PLAIN_ALLOC}
if [ -z "${BUN:-}" ]; then
  BUN=$(command -v bun 2>/dev/null || echo "$HOME/.bun/bin/bun")
fi
export BUN

stage_cmd() {
  case "$1" in
    tov)       echo 'if [ -x "$TOV" ]; then echo "compiler present: $TOV"; else scripts/build-tov.sh; fi' ;;
    check)     echo 'python3 scripts/check.py --no-fix src/*.tov src/providers/*.tov tests/*.tov && echo "check: ok"' ;;
    unit)      echo 'make unit TOV="$TOV"' ;;
    openapi)   echo 'make openapi-check TOV="$TOV"' ;;
    web)       echo 'make web-check BUN="$BUN"' ;;
    parity)    echo 'python3 scripts/parity_count.py --check && echo "parity: up to date"' ;;
    configdoc) echo 'python3 scripts/gen_config_doc.py --check' ;;
    deploy)    echo 'python3 -m unittest -v tests/test_deploy.py' ;;
    # unset, not "bun": tests/e2e.py reads an unset RAIJU_SERVER as the default server in places
    e2e-bun)   echo 'env -u RAIJU_SERVER python3 tests/e2e.py' ;;
    e2e-http1) echo 'RAIJU_SERVER=http1 python3 tests/e2e.py' ;;
    ui)        echo 'make ui TOV="$TOV"' ;;
    soak)      echo 'make soak TOV="$TOV"' ;;
    *) return 1 ;;
  esac
}

# the stages that start gateways or mocks on fixed ports
locked() {
  case "$1" in openapi|e2e-bun|e2e-http1|ui|soak) return 0 ;; *) return 1 ;; esac
}

needs_tov() {
  case "$1" in tov|parity|web|configdoc|deploy) return 1 ;; *) return 0 ;; esac
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
  exit 0
fi

# the compiler's cache key in CI: Tov's revision and a hash of the patches and the build script
if [ "${1:-}" = "tov-key" ]; then
  rev=$(sed -n 's/^REV=\${TOV_REV:-\([0-9a-f]*\)}.*/\1/p' scripts/build-tov.sh)
  hash=$({ find tov-patches -type f | LC_ALL=C sort; echo scripts/build-tov.sh; } | xargs sha256sum | sha256sum | cut -c1-16)
  echo "tov-$(uname -s)-$(uname -m)-${TOV_REV:-$rev}-$hash"
  exit 0
fi

STAGES=("$@")
[ ${#STAGES[@]} -eq 0 ] && STAGES=("${ALL[@]}")
for s in "${STAGES[@]}"; do
  if ! stage_cmd "$s" >/dev/null; then
    echo "ci: unknown stage '$s' (stages: ${ALL[*]}, and the optional soak)" >&2
    exit 2
  fi
done

mkdir -p build/ci
RESULTS=()
FAILED=""

summary() {
  echo
  echo "== ci summary =="
  for r in "${RESULTS[@]}"; do echo "  $r"; done
  if [ -n "$FAILED" ]; then
    echo "ci: failed at $FAILED (log: build/ci/$FAILED.log)"
  else
    echo "ci: all stages passed"
  fi
}

for s in "${STAGES[@]}"; do
  if needs_tov "$s" && [ "$s" != tov ] && [ ! -x "$TOV" ]; then
    echo "ci: no compiler at $TOV (run scripts/ci.sh tov or set TOV)" >&2
    RESULTS+=("$(printf '%-10s FAIL  (no compiler)' "$s")")
    FAILED=$s
    break
  fi
  cmd=$(stage_cmd "$s")
  echo "== $s: $cmd"
  start=$(date +%s)
  if [ -n "${CI_LOCK:-}" ] && locked "$s"; then
    flock "$CI_LOCK" bash -c "$cmd" 2>&1 | tee "build/ci/$s.log"
  else
    bash -c "$cmd" 2>&1 | tee "build/ci/$s.log"
  fi
  rc=${PIPESTATUS[0]}
  secs=$(( $(date +%s) - start ))
  if [ "$rc" -eq 0 ]; then
    RESULTS+=("$(printf '%-10s ok    %4ds' "$s" "$secs")")
  else
    RESULTS+=("$(printf '%-10s FAIL  %4ds  (exit %d)' "$s" "$secs" "$rc")")
    FAILED=$s
    break
  fi
done

summary
[ -z "$FAILED" ]
