#!/bin/sh
# Checks the ported socket and fetch-client patches (0002, 0003, 0004, 0007, 0008 fetch half, 0013, 0015
# client half, 0016, 0022) with the compiler built from this tree:
#   TOV=target/release/tov raiju-tests/run-s2.sh [section ...]
# Sections: spawn alpn udp pool peer cert decompress buffer pause wsstall (default: all). Each program prints
# "ok" and "FAIL" lines; a section passes when no line fails and the expected number of "ok" lines appears.
set -eu
# (every server here is local: fetch must not go through an environment proxy)
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy || true
TOV=${TOV:-$(cd "$(dirname "$0")/.." && pwd)/target/release/tov}
DIR=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
PIDS=""
trap 'rm -rf "$OUT"; for p in $PIDS; do kill $p 2>/dev/null || true; done' EXIT
SECTIONS=${*:-spawn alpn udp pool peer cert decompress buffer pause wsstall}
want() { case " $SECTIONS " in *" $1 "*) return 0;; esac; return 1; }

expect() {
  if grep -q "^FAIL" "$1" || [ "$(grep -c "^ok" "$1")" -ne "$2" ]; then
    echo "FAILED: $3"
    cat "$1"
    exit 1
  fi
  echo "passed: $3 ($2 checks)"
}
build() { "$TOV" build "$DIR/$1.tov" -o "$OUT/$1" > "$OUT/build.log" 2>&1 || { echo "FAILED: build of $1.tov"; cat "$OUT/build.log"; exit 1; }; }

openssl req -x509 -newkey rsa:2048 -nodes -keyout "$OUT/key.pem" -out "$OUT/cert.pem" -days 2 \
  -subj /CN=localhost -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" 2>/dev/null

# a host name other than localhost that /etc/hosts maps to 127.0.0.1: the address policy tests resolve it
if [ -z "${PEER_NAME:-}" ]; then
  PEER_NAME=$(awk '$1 == "127.0.0.1" && $2 != "localhost" { print $2; exit }' /etc/hosts)
fi

if want spawn; then
  build spawn_socket
  "$OUT/spawn_socket" > "$OUT/spawn.out"
  expect "$OUT/spawn.out" 1 "Bun.spawnSocket (0002)"
fi

if want alpn; then
  python3 -u "$DIR/tls_server.py" "$OUT/cert.pem" "$OUT/key.pem" > "$OUT/tls.port" & PIDS="$PIDS $!"
  sleep 0.5
  build alpn
  ALPN_PORT=$(head -1 "$OUT/tls.port") "$OUT/alpn" > "$OUT/alpn.out"
  expect "$OUT/alpn.out" 3 "Socket ALPN (0003)"
fi

if want udp; then
  build udp
  "$OUT/udp" > "$OUT/udp.out"
  expect "$OUT/udp.out" 8 "Bun.udpSocket (0004)"
  # node:dgram runs on JavaScriptCore. When the JavaScriptCore at TOV_JSC_DIR is older than the compiler (its
  # TovAPI.h lacks TVHeapStatistics, which upstream's node.c calls), pass JS_CFLAGS='-DTVHeapStatistics(c,v)=((void)0)'.
  (cd "$DIR" && TOV_CFLAGS="${JS_CFLAGS:-}" "$TOV" run "$DIR/udp_dgram.tov") > "$OUT/dgram.out" 2>&1 || true
  expect "$OUT/dgram.out" 8 "node:dgram (0004)"
fi

# fetch pool options and HTTP/2 (0007), and fetch with a ReadableStream body (0008): three origins from
# h2_server.py (HTTP/2 over TLS, HTTP/1.1 over TLS, plain HTTP/1.1), which needs Python's `h2` package
if want pool; then
  if python3 -c 'import h2' 2>/dev/null; then
    for MODE in h2 h1tls h1; do
      python3 -u "$DIR/h2_server.py" $MODE "$OUT/cert.pem" "$OUT/key.pem" > "$OUT/pool-$MODE.port" & PIDS="$PIDS $!"
    done
    sleep 1.5
    export H2_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h2.port") H1TLS_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h1tls.port") \
      H1_PORT=$(sed -n 's/^listening //p' "$OUT/pool-h1.port")
    build fetch_pool
    "$OUT/fetch_pool" > "$OUT/fetch_pool.out"
    expect "$OUT/fetch_pool.out" 23 "fetch pool options and HTTP/2 (0007)"
    build request_body_fetch
    "$OUT/request_body_fetch" > "$OUT/request_body_fetch.out"
    expect "$OUT/request_body_fetch.out" 36 "fetch with a ReadableStream body: HTTP/1.1, TLS, HTTP/2 (0008)"
    # the address policy on TLS, HTTP/2, streamed bodies and proxies (0013), on the same origins
    if [ -n "$PEER_NAME" ]; then
      build peer_paths
      PEER_NAME=$PEER_NAME "$OUT/peer_paths" > "$OUT/peer_paths.out"
      expect "$OUT/peer_paths.out" 24 "fetch address policy on HTTPS, HTTP/2, streamed bodies and proxies (0013)"
      build socket_peer_tls
      PEER_NAME=$PEER_NAME "$OUT/socket_peer_tls" > "$OUT/socket_peer_tls.out"
      expect "$OUT/socket_peer_tls.out" 7 "Bun.connect (TLS) and wss: WebSocket address policy (0022)"
    else
      echo "skipped: fetch address policy on HTTPS and HTTP/2 (no PEER_NAME)"
    fi
  else
    echo "skipped: fetch pool options and HTTP/2 (needs Python's h2 package)"
  fi
fi

if want pause; then
  build socket_pause
  "$OUT/socket_pause" > "$OUT/socket_pause.out"
  expect "$OUT/socket_pause.out" 2 "Socket.pause (0008)"
fi

# fetch's address policy (0013): the peer option on the resolved addresses, redirects and pooled connections
if want peer; then
  if [ -n "$PEER_NAME" ]; then
    build peer_policy
    PEER_NAME=$PEER_NAME "$OUT/peer_policy" > "$OUT/peer_policy.out"
    expect "$OUT/peer_policy.out" 21 "fetch address policy (0013)"
    # the same policy on Bun.connect and the WebSocket client (0022)
    build socket_peer
    PEER_NAME=$PEER_NAME TMPDIR="$OUT" "$OUT/socket_peer" > "$OUT/socket_peer.out"
    expect "$OUT/socket_peer.out" 16 "Bun.connect and WebSocket address policy (0022)"
  else
    echo "skipped: address policy (no name but localhost maps to 127.0.0.1 in /etc/hosts; set PEER_NAME)"
  fi
fi

# TLS client certificates on fetch and Bun.connect (0015): a server that requires one and answers with its common name
if want cert; then
  for c in a b; do
    openssl req -x509 -newkey rsa:2048 -nodes -keyout "$OUT/client_$c.key" -out "$OUT/client_$c.pem" -days 2 -subj "/CN=client-$c" 2>/dev/null
  done
  cat "$OUT/client_a.pem" "$OUT/client_b.pem" > "$OUT/client_cas.pem"
  python3 -u "$DIR/client_cert_server.py" "$OUT/cert.pem" "$OUT/key.pem" "$OUT/client_cas.pem" > "$OUT/cc.port" & PIDS="$PIDS $!"
  sleep 0.5
  build client_cert
  CC_PORT=$(head -1 "$OUT/cc.port") CC_DIR="$OUT" "$OUT/client_cert" > "$OUT/client_cert.out"
  expect "$OUT/client_cert.out" 8 "TLS client certificates (0015)"
  # Request.signal on Bun.serve (0015): aborted when the client goes away before the answer
  build server_gone
  "$OUT/server_gone" > "$OUT/server_gone.out" & SG=$!
  PIDS="$PIDS $SG"
  sleep 0.5
  python3 "$DIR/server_gone_client.py" "$(sed -n 's/^listening //p' "$OUT/server_gone.out")" > "$OUT/server_gone_client.out" || true
  kill $SG 2>/dev/null || true
  expect "$OUT/server_gone_client.out" 4 "Request.signal on Bun.serve (0015)"
fi

# Bun.gunzipSync and Bun.inflateSync (0015)
if want decompress; then
  build decompress
  "$OUT/decompress" > "$OUT/decompress.out"
  expect "$OUT/decompress.out" 8 "Bun.gunzipSync and Bun.inflateSync (0015)"
fi

# a fetch connection's input buffer that starts small and grows (0016)
if want buffer; then
  python3 -u "$DIR/fetch_buffer_server.py" > "$OUT/fetch_buffer.port" & PIDS="$PIDS $!"
  sleep 0.5
  build fetch_buffer
  FB_PORT=$(sed -n 's/^listening //p' "$OUT/fetch_buffer.port") "$OUT/fetch_buffer" > "$OUT/fetch_buffer.out"
  expect "$OUT/fetch_buffer.out" 3 "fetch input buffer (0016)"
fi
