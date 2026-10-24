#!/bin/sh
# Checks patches 0001-0010 and 0012 with the patched compiler: TOV=build/tov/target/release/tov tov-patches/tests/run.sh
# (or `make tov-test`). Each program prints "ok" lines and "FAIL" lines; a run passes when no line
# fails and the expected number of "ok" lines appears.
set -eu
TOV=${TOV:-tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
SRV=""
ASRV=""
POOLSRV=""
trap 'rm -rf "$OUT"; [ -n "$SRV" ] && kill $SRV 2>/dev/null || true; [ -n "$ASRV" ] && kill $ASRV 2>/dev/null || true; [ -n "$POOLSRV" ] && kill $POOLSRV 2>/dev/null || true' EXIT

# expect FILE N: no FAIL line, and exactly N ok lines
expect() {
  if grep -q "^FAIL" "$1" || [ "$(grep -c "^ok" "$1")" -ne "$2" ]; then
    echo "FAILED: $3"
    cat "$1"
    exit 1
  fi
  echo "passed: $3 ($2 checks)"
}

# spawn and stream (patches 0001, 0002)
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/spawn_socket.tov" -o "$OUT/spawn" >/dev/null
"$OUT/spawn" > "$OUT/spawn.out"
expect "$OUT/spawn.out" 1 "Bun.spawnSocket"

TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/stream_body.tov" -o "$OUT/stream" >/dev/null
"$OUT/stream" > "$OUT/stream.out" & SRV=$!
sleep 0.5
PORT=$(sed -n 's/^listening //p' "$OUT/stream.out")
python3 - "$PORT" <<'PY'
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
sys.exit(0 if ok and cut else 1)
PY
kill $SRV 2>/dev/null || true
SRV=""

# ALPN (patch 0003): a TLS server offering h2, with a throwaway certificate
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$OUT/key.pem" -out "$OUT/cert.pem" -days 2 \
  -subj /CN=localhost -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" 2>/dev/null
python3 -u "$DIR/tls_server.py" "$OUT/cert.pem" "$OUT/key.pem" > "$OUT/tls.port" & ASRV=$!
sleep 0.5
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/alpn.tov" -o "$OUT/alpn" >/dev/null
ALPN_PORT=$(head -1 "$OUT/tls.port") "$OUT/alpn" > "$OUT/alpn.out"
kill $ASRV 2>/dev/null || true
ASRV=""
expect "$OUT/alpn.out" 3 "Socket ALPN"

# UDP (patch 0004): Bun.udpSocket, and node:dgram over it (through tests/node_modules/dgram-check)
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/udp.tov" -o "$OUT/udp" >/dev/null
"$OUT/udp" > "$OUT/udp.out"
expect "$OUT/udp.out" 8 "Bun.udpSocket"

"$TOV" run "$DIR/udp_dgram.tov" > "$OUT/dgram.out"
expect "$OUT/dgram.out" 8 "node:dgram"

# WebAssembly (patches 0005 and 0010): std/wasm on WAMR, with its limits and a time limit per call (run from the tests directory: it reads wasm_mod.wasm)
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/wasm.tov" -o "$OUT/wasm" >/dev/null
(cd "$DIR" && "$OUT/wasm") > "$OUT/wasm.out"
expect "$OUT/wasm.out" 24 "std/wasm"
# WebRTC (patch 0006): two std/rtc peer connections in one program, on the loopback address (a data channel
# both ways, Opus RTP with rewritten headers, states, close). The first build compiles libdatachannel (cached).
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/rtc.tov" -o "$OUT/rtc" >/dev/null
"$OUT/rtc" > "$OUT/rtc.out"
expect "$OUT/rtc.out" 20 "std/rtc (WebRTC)"
# fetch pool options and HTTP/2 (patch 0007): three origins from h2_server.py (HTTP/2 over TLS, HTTP/1.1
# over TLS, plain HTTP/1.1), which needs Python's `h2` package: installed under $OUT if it is missing
if ! python3 -c 'import h2' 2>/dev/null; then
  pip install --quiet --target "$OUT/pylib" h2 >/dev/null 2>&1 || true
  [ -d "$OUT/pylib/h2" ] && export PYTHONPATH="$OUT/pylib${PYTHONPATH:+:$PYTHONPATH}"
fi
if python3 -c 'import h2' 2>/dev/null; then
  for MODE in h2 h1tls h1; do
    python3 -u "$DIR/h2_server.py" $MODE "$OUT/cert.pem" "$OUT/key.pem" > "$OUT/pool-$MODE.port" & POOLSRV="$POOLSRV $!"
  done
  sleep 1.5
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/fetch_pool.tov" -o "$OUT/fetch_pool" >/dev/null
  H2_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h2.port") H1TLS_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h1tls.port") \
    H1_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h1.port") "$OUT/fetch_pool" > "$OUT/fetch_pool.out"
  expect "$OUT/fetch_pool.out" 23 "fetch pool options and HTTP/2"
  # request bodies as streams (patch 0008): fetch with a ReadableStream body on the same three origins
  TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/request_body_fetch.tov" -o "$OUT/request_body_fetch" >/dev/null
  H2_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h2.port") H1TLS_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h1tls.port") \
    H1_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h1.port") "$OUT/request_body_fetch" > "$OUT/request_body_fetch.out"
  kill $POOLSRV 2>/dev/null || true
  POOLSRV=""
  expect "$OUT/request_body_fetch.out" 36 "fetch with a ReadableStream body (HTTP/1.1, TLS, HTTP/2)"
else
  echo "skipped: fetch pool options and HTTP/2 (needs Python's h2 package, and pip could not install it)"
fi

# Bun.serve request bodies as streams (patch 0008): a server that reads big bodies chunk by chunk, driven over raw sockets
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/request_body_server.tov" -o "$OUT/request_body_server" >/dev/null
"$OUT/request_body_server" > "$OUT/request_body_server.out" & SRV=$!
sleep 0.5
RB_PORT=$(sed -n 's/^listening //p' "$OUT/request_body_server.out")
python3 "$DIR/request_body_client.py" "$RB_PORT" "$SRV" > "$OUT/request_body_client.out" || true
kill $SRV 2>/dev/null || true
SRV=""
expect "$OUT/request_body_client.out" 19 "Bun.serve request body streams"

# Socket.pause() and resume() (patch 0008)
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/socket_pause.tov" -o "$OUT/socket_pause" >/dev/null
"$OUT/socket_pause" > "$OUT/socket_pause.out"
expect "$OUT/socket_pause.out" 2 "Socket.pause"

# node:fs rename, open/write/fsync/close, chmod, writeFileSync mode and flush (patch 0009)
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/fs_atomic.tov" -o "$OUT/fs_atomic" >/dev/null
"$OUT/fs_atomic" > "$OUT/fs_atomic.out"
expect "$OUT/fs_atomic.out" 17 "node:fs rename and fsync"

# Bun.serve's timeouts and connection cap, the spare descriptor, Bun.onStopSignal with and without workers (patch 0012)
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/server_lifecycle.tov" -o "$OUT/server_lifecycle" >/dev/null
python3 "$DIR/server_lifecycle_client.py" "$OUT/server_lifecycle" "$OUT" > "$OUT/server_lifecycle_client.out" || true
expect "$OUT/server_lifecycle_client.out" 18 "Bun.serve timeouts, connection cap and graceful stop"

echo "tov-patches tests passed"
