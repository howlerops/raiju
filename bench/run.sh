#!/usr/bin/env bash
# Measures the latency the gateway adds: the same load straight at the mock
# upstream, then through raiju. Run from the repository root.
set -euo pipefail
export TOV_CFLAGS="${TOV_CFLAGS:--DTV_PLAIN_ALLOC}"
C=${C:-32}; D=${D:-5}
mkdir -p build
tov build src/main.tov -o build/raiju >/dev/null
tov build tests/mock_upstream.tov -o build/mock_upstream >/dev/null
tov build bench/load.tov -o build/load >/dev/null
MOCK_PORT=18099 build/mock_upstream >/dev/null & MOCK=$!
build/raiju -port 18098 -host 127.0.0.1 -config bench/bench.config.json 2>/dev/null & GW=$!
trap 'kill $MOCK $GW' EXIT
sleep 0.5
RATE=${RATE:-0}   # >0: open loop at RATE requests/second
build/load http://127.0.0.1:18099/v1/chat/completions "$C" 1 >/dev/null   # warm up
echo "direct:  $(build/load http://127.0.0.1:18099/v1/chat/completions "$C" "$D" "$RATE")"
build/load http://127.0.0.1:18098/v1/chat/completions "$C" 1 >/dev/null
before=$(curl -s http://127.0.0.1:18098/metrics | awk '/^bifrost_overhead_latency_microseconds_(sum|count)/ {print $2}' | paste -sd' ')
echo "gateway: $(build/load http://127.0.0.1:18098/v1/chat/completions "$C" "$D" "$RATE")"
after=$(curl -s http://127.0.0.1:18098/metrics | awk '/^bifrost_overhead_latency_microseconds_(sum|count)/ {print $2}' | paste -sd' ')
echo "$before $after" | awk '{ printf "gateway internal overhead (handler time minus upstream): mean %.1f us over %d requests\n", ($3-$1)/($4-$2), $4-$2 }'
