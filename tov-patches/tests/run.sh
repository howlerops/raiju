#!/bin/sh
# Checks patches 0001-0005 with the patched compiler: TOV=build/tov/target/release/tov tov-patches/tests/run.sh
# (or `make tov-test`). Each program prints "ok" lines and "FAIL" lines; a run passes when no line
# fails and the expected number of "ok" lines appears.
set -eu
TOV=${TOV:-tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
SRV=""
ASRV=""
trap 'rm -rf "$OUT"; [ -n "$SRV" ] && kill $SRV 2>/dev/null || true; [ -n "$ASRV" ] && kill $ASRV 2>/dev/null || true' EXIT

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

# WebAssembly (patch 0005): std/wasm on WAMR, with its limits (run from the tests directory: it reads wasm_mod.wasm)
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/wasm.tov" -o "$OUT/wasm" >/dev/null
(cd "$DIR" && "$OUT/wasm") > "$OUT/wasm.out"
expect "$OUT/wasm.out" 22 "std/wasm"

echo "tov-patches tests passed"
