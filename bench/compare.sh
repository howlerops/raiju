#!/usr/bin/env bash
# Raiju vs Bifrost on the same machine, same mock upstream, same load.
#   core 0: load generator (vegeta)   core 1: mock upstream   cores 2-3: the gateway
# Each gateway runs alone. Results: bench/results/<timestamp>.jsonl, summary on stdout.
# Needs: BIFROST (path to bifrost-http), VEGETA (path to vegeta); optional BIFROST_V1.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${BIFROST:?set BIFROST to the bifrost-http binary}"
: "${VEGETA:?set VEGETA to the vegeta binary}"
RATES=${RATES:-"1000 5000 10000"}
DUR=${DUR:-15s}
export TOV_CFLAGS="${TOV_CFLAGS:--DTV_PLAIN_ALLOC}"
mkdir -p build bench/results
"${TOV:-tov}" build src/main.tov -o build/raiju >/dev/null
"${TOV:-tov}" build tests/mock_upstream.tov -o build/mock_upstream >/dev/null
OUT=bench/results/$(date +%Y%m%d-%H%M%S).jsonl
TMP=$(mktemp -d)
cp bench/bifrost/config.json "$TMP/config.json"
printf '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"Say hello in one short sentence."}],"max_tokens":16}' > "$TMP/body.json"

MOCK_PORT=18099 taskset -c 1 build/mock_upstream >/dev/null 2>&1 & MOCK=$!
trap 'kill $MOCK 2>/dev/null; kill $GW 2>/dev/null || true; rm -rf "$TMP"' EXIT
GW=""
sleep 0.5

# Waits (up to 60 s) for TIME_WAIT sockets from the previous run to clear.
drain() {
  local tw
  for _ in $(seq 120); do
    tw=$( (awk '$4 == "06"' /proc/net/tcp /proc/net/tcp6 2>/dev/null || true) | wc -l)
    if [ "$tw" -lt 2000 ]; then return 0; fi
    sleep 0.5
  done
  return 0
}

targets() { printf 'POST %s/v1/chat/completions\nContent-Type: application/json\n@%s\n' "$1" "$TMP/body.json"; }

attack() {   # name base rate(0 = max) extra-args...
  local name=$1 base=$2 rate=$3; shift 3
  local args=(-duration="$DUR" -keepalive=true -timeout=10s)
  # a bounded connection pool, so latency spikes can't exhaust local ports
  if [ "$rate" = 0 ]; then args+=(-rate=0 -max-workers=128 -connections=128); else args+=(-rate="$rate"/s -workers=64 -max-workers=512 -connections=512); fi
  drain
  targets "$base" | taskset -c 0 "$VEGETA" attack "${args[@]}" | "$VEGETA" report -type=json > "$TMP/r.json"
  python3 - "$name" "$rate" "$TMP/r.json" "$GWPID" >> "$OUT" <<'PY'
import json, sys, subprocess
name, rate, path, pid = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
r = json.load(open(path)); l = r["latencies"]
rss = 0
if pid != "-":
    for p in subprocess.run(["sh", "-c", f"echo {pid}; pgrep -P {pid}"], capture_output=True, text=True).stdout.split():
        try:
            rss += int(open(f"/proc/{p}/status").read().split("VmRSS:")[1].split()[0])
        except Exception:
            pass
print(json.dumps({"target": name, "rate": rate, "achieved_rps": round(r["throughput"]), "success": r["success"],
    "mean_us": l["mean"] / 1000, "p50_us": l["50th"] / 1000, "p90_us": l["90th"] / 1000, "p99_us": l["99th"] / 1000,
    "max_us": l["max"] / 1000, "rss_mb": round(rss / 1024, 1), "errors": r.get("errors", [])[:3]}))
PY
}

run_all() {   # name base
  targets "$2" | taskset -c 0 "$VEGETA" attack -duration=3s -rate=2000/s >/dev/null   # warm up
  for rate in $RATES; do attack "$1" "$2" "$rate"; done
  attack "$1" "$2" 0
}

GWPID=-; run_all direct http://127.0.0.1:18099

taskset -c 2,3 build/raiju -port 18098 -host 127.0.0.1 -config bench/bench.config.json -workers 2 2>/dev/null & GW=$!; GWPID=$GW
sleep 1; run_all raiju http://127.0.0.1:18098; kill $GW; wait $GW 2>/dev/null || true

GOMAXPROCS=2 taskset -c 2,3 "$BIFROST" -app-dir "$TMP" -port 18097 -host 127.0.0.1 -log-level error >/dev/null 2>&1 & GW=$!; GWPID=$GW
for _ in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:18097/health && break; sleep 0.5; done
run_all bifrost http://127.0.0.1:18097; kill $GW; wait $GW 2>/dev/null || true
GW=""

# Optionally an older release (BIFROST_V1), closer to when Bifrost's published numbers were measured.
if [ -n "${BIFROST_V1:-}" ]; then
  V1=$(mktemp -d); cp bench/bifrost/config.v1.json "$V1/config.json"
  GOMAXPROCS=2 taskset -c 2,3 "$BIFROST_V1" -app-dir "$V1" -port 18096 -host 127.0.0.1 -log-level error >/dev/null 2>&1 & GW=$!; GWPID=$GW
  for _ in $(seq 60); do curl -s -o /dev/null http://127.0.0.1:18096/health && break; sleep 0.5; done
  run_all bifrost-v1 http://127.0.0.1:18096; kill $GW; wait $GW 2>/dev/null || true
  GW=""; rm -rf "$V1"
fi

python3 - "$OUT" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
base = {r["rate"]: r for r in rows if r["target"] == "direct"}
print(f"{'target':10} {'rate':>7} {'got rps':>8} {'ok':>6} {'mean us':>8} {'p50 us':>8} {'p99 us':>8} {'added p50':>9} {'rss MB':>7}")
for r in rows:
    added = r["p50_us"] - base[r["rate"]]["p50_us"] if r["target"] != "direct" and r["rate"] else float("nan")
    rate = "max" if r["rate"] == 0 else r["rate"]
    print(f"{r['target']:10} {rate:>7} {r['achieved_rps']:>8} {r['success']*100:>5.1f}% {r['mean_us']:>8.0f} {r['p50_us']:>8.0f} {r['p99_us']:>8.0f} {added:>9.0f} {r['rss_mb']:>7}")
print(f"\nraw: {sys.argv[1]}")
PY
