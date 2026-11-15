#!/bin/sh
# Raiju's patch tests for workstream s1 (HTTP server and workers), ported from
# /raiju/tov-patches/tests/run.sh. Run inside the build container:
#   TOV=/tov/target/release/tov sh raiju-tests/run.sh [name ...]
# Each section prints "passed: ..." or "FAILED: ..." (and exits 1).
set -eu
TOV=${TOV:-tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
SRV=""
trap 'rm -rf "$OUT"; [ -n "$SRV" ] && kill $SRV 2>/dev/null || true' EXIT
want() { [ $# -eq 0 ] && return 0; t=$1; shift; for a in $ONLY; do [ "$a" = "$t" ] && return 0; done; [ -z "$ONLY" ]; }
ONLY="$*"

# expect FILE N NAME: no FAIL line, and exactly N ok lines
expect() {
  if grep -q "^FAIL" "$1" || [ "$(grep -c "^ok" "$1")" -ne "$2" ]; then
    echo "FAILED: $3"
    cat "$1"
    exit 1
  fi
  echo "passed: $3 ($2 checks)"
}
build() { TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/$1.tov" -o "$OUT/$1" >/dev/null; }

# streamed response bodies (patch 0001)
if want stream; then
build stream_body
"$OUT/stream_body" > "$OUT/stream.out" & SRV=$!
sleep 0.5
PORT=$(sed -n 's/^listening //p' "$OUT/stream.out")
python3 - "$PORT" > "$OUT/stream_client.out" <<'PY' || true
import socket, sys, time
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5)
s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
t0, times, data = time.time(), [], b""
while b"0\r\n\r\n" not in data:
    c = s.recv(4096)
    if not c:
        break
    data += c
    if b"chunk" in c:
        times.append(time.time() - t0)
ok = b"transfer-encoding: chunked" in data.lower() and data.count(b"chunk ") == 3 and len(times) == 3 and times[-1] - times[0] > 0.15
print("ok stream body arrives in chunks" if ok else f"FAIL {times} {data[:300]!r}")
f = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5)
f.sendall(b"GET /fail HTTP/1.1\r\nHost: x\r\n\r\n")
got = b""
while True:
    c = f.recv(4096)
    if not c:
        break
    got += c
cut = b"partial" in got and not got.endswith(b"0\r\n\r\n")
print("ok a failed stream cuts the connection without the last chunk" if cut else f"FAIL {got[-200:]!r}")
PY
kill $SRV 2>/dev/null || true
SRV=""
expect "$OUT/stream_client.out" 2 "Bun.serve streamed response bodies"
fi

# Bun.serve's timeouts and connection cap, the spare descriptor, Bun.onStopSignal with and without workers (patch 0012)
if want lifecycle; then
build server_lifecycle
python3 "$DIR/server_lifecycle_client.py" "$OUT/server_lifecycle" "$OUT" > "$OUT/server_lifecycle_client.out" || true
expect "$OUT/server_lifecycle_client.out" 18 "Bun.serve timeouts, connection cap and graceful stop"
fi

# a worker killed alone (SIGKILL) is replaced, with a growing pause for one that keeps dying; Bun.plainAlloc (patch 0019; Linux /proc)
if want respawn; then
if [ -d /proc/self/task ]; then
  build worker_respawn
  "$TOV" build "$DIR/worker_respawn.tov" -o "$OUT/worker_respawn_fast" >/dev/null
  python3 "$DIR/worker_respawn_client.py" "$OUT/worker_respawn" "$OUT" "$OUT/worker_respawn_fast" > "$OUT/worker_respawn_client.out" || true
  expect "$OUT/worker_respawn_client.out" 10 "Bun.serve workers respawned after SIGKILL, Bun.plainAlloc"
else
  echo "skipped: worker respawn (needs /proc)"
fi
fi

# Math.random seeded from getrandom(2) and again in each forked worker; TOV_SEED=<n> still fixes it (patch 0021)
if want random; then
build random_seed
python3 "$DIR/random_seed_client.py" "$OUT/random_seed" > "$OUT/random_seed.out" || true
expect "$OUT/random_seed.out" 5 "Math.random seeded per process and per worker"
fi

# clean (re-executed) workers after JavaScript-backed startup (patch 0026; Linux)
# Needs the system WebKitGTK engine (pkg-config javascriptcoregtk-4.1): the build container's static engine is too old for v0.1.0.
if want clean; then
if [ "$(uname -s)" = Linux ]; then
  TOV="$TOV" sh "$DIR/clean_workers.sh"
  echo "passed: clean workers (see clean_workers_client.py for its checks)"
fi
fi

# server.requestIP on Bun.serve (patch 0017)
if want ip; then
build request_ip
"$OUT/request_ip" > "$OUT/request_ip.out"
expect "$OUT/request_ip.out" 4 "server.requestIP"
fi

# the write-stall limit of upgraded (WebSocket) sockets on Bun.serve: a client that stops reading is dropped after
# idleTimeout, one that keeps reading slowly stays (patch 0022, server part)
if want stall; then
build ws_stall
python3 "$DIR/ws_stall_client.py" "$OUT/ws_stall" "$OUT" > "$OUT/ws_stall_client.out" || true
expect "$OUT/ws_stall_client.out" 5 "Bun.serve write-stall limit on WebSockets"
fi

# Socket.pause() and resume() (patch 0008)
if want pause; then
build socket_pause
"$OUT/socket_pause" > "$OUT/socket_pause.out"
expect "$OUT/socket_pause.out" 2 "Socket.pause"
fi

# Bun.serve request bodies as streams (patch 0008, server half): a server that reads big bodies chunk by chunk, driven over raw sockets.
# Last on purpose: 18 of its 19 checks pass until the fetch-client half of 0008 (workstream s2) is merged; the relay check needs it.
if want body; then
build request_body_server
"$OUT/request_body_server" > "$OUT/request_body_server.out" & SRV=$!
sleep 0.5
RB_PORT=$(sed -n 's/^listening //p' "$OUT/request_body_server.out")
python3 "$DIR/request_body_client.py" "$RB_PORT" "$SRV" > "$OUT/request_body_client.out" || true
kill $SRV 2>/dev/null || true
SRV=""
expect "$OUT/request_body_client.out" 19 "Bun.serve request body streams"
fi

echo "s1 raiju tests passed"
