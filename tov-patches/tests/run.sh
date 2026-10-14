#!/bin/sh
# Checks both patches with the patched compiler: TOV=build/tov/target/release/tov tov-patches/tests/run.sh
set -eu
TOV=${TOV:-tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"; kill $SRV 2>/dev/null || true' EXIT
TOV_CFLAGS=-DTV_PLAIN_ALLOC "$TOV" build "$DIR/spawn_socket.tov" -o "$OUT/spawn" >/dev/null
"$OUT/spawn" | tee "$OUT/spawn.out"
grep -q "^ok" "$OUT/spawn.out"
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
sys.exit(0 if ok else 1)
PY
