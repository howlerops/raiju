# Handoff

Raiju is a Bifrost-compatible LLM gateway written in Tov (TypeScript syntax compiled to
native code). Work runs as a ledger with a lead and workers: the lead keeps
[LEDGER.md](LEDGER.md), hands self-contained tasks to worker agents in their own git
worktrees, then merges, tests and commits. Bifrost parity is tracked row by row in
[docs/parity.md](docs/parity.md); scope and open product items are in [SCOPE.md](SCOPE.md).

Branch: `claude/great-dirac-d7na9k`. Last lead commit before this handoff: see `git log -3`.

## Where things stand

- Waves 8 to 11 are merged: SDK routes for OpenAI, Anthropic, GenAI, Bedrock and Cohere to
  any provider; governance, MCP, alerting and management APIs; metrics, OTel (HTTP and
  plaintext gRPC); vector stores; cloud batches and files; every Bifrost config key applied
  or reported; config encryption at rest; cluster discovery and auth proxies; guardrail
  breadth; log sinks (BigQuery, Pub/Sub, Kafka, Maxim, Parquet).
- Tests at handoff: `make unit` 1,063 passed; e2e "all passed" on the Bun server (last full
  run before the log-sink commit; that commit was also e2e-green in its worker on both servers).
- Wave 12 and two follow-ups were stopped by the weekly usage limit mid-task. Their unfinished
  work is saved as patches in [handoff/patches/](handoff/patches/), not merged:

| Ledger | Gap | Patch | State when stopped |
|---|---|---|---|
| L81 | G36, G38 | `L81-decisions-typesafe.patch` | built; e2e was about to run |
| L82 | G37 | `L82-compat.patch` | unit tests passed; e2e was about to run |
| L83 | G40 | `L83-ws-responses-live.patch` | built; unit tests running |
| L84 | G41 | `L84-projects-rbac.patch` | typecheck passed; unit tests running |
| L88 | G46 | `L88-prompts-webhooks-flags.patch` | in progress; least verified |
| L91 | G47, G22 | `L91-circuit-policies-mcp-oauth.patch` | built; e2e was about to run |
| L92 | G29, G44 | `L92-raiju-side.patch` + `L92-tov-runtime.diff` | Tov suite passed (ALPN 3 checks, UDP 8, dgram 8); splitting into patches 0003/0004 was next |

All patches except `L92-tov-runtime.diff` are against commit `ae6f1db`. Apply each in a fresh
worktree with `git apply -3 handoff/patches/<name>.patch`, resolve conflicts against current
HEAD (keep both sides' intent), then finish the task: typecheck, unit, e2e on both servers,
merge, commit. The original briefs are the ledger rows plus the shared worker brief below.
The worker report notes for earlier tasks are summarised in the ledger.

`L92-tov-runtime.diff` is the ALPN and UDP runtime work on top of patches 0001 and 0002 in a
Tov checkout (apply it in `build/tov` after `scripts/build-tov.sh` has applied 0001/0002).
To finish L92: split it into `tov-patches/0003-alpn.patch` and `tov-patches/0004-udp.patch`,
add them to `scripts/build-tov.sh` and `tov-patches/README.md`, add upstream-ready versions
under `tov-patches/upstream/` (Tov's AGENTS.md: no mention of AI tools, no attribution
trailers), rebuild the compiler, then use ALPN "h2" for TLS gRPC in `src/h2.tov`/`src/otel.tov`
and add udp/mdns discovery in `src/discovery.tov`.

## Still open after wave 12 (docs/parity.md "Remaining gaps")

- Gitleaks: 35 of 222 rules, written from memory; needs the real `gitleaks.toml`.
- Broker-mode clustering (a gRPC relay process); lock-based leader election.
- Models without a price cost 0 with a warning, as in Bifrost (owner may want a refuse switch).
- The exact-match response cache is shared across virtual keys (the semantic cache is now
  scoped per key, as Bifrost); owner's call.
- docs/parity.md needs a re-audit after wave 12 (the last full one was before wave 10);
  run it as its own task, counting rows by script.
- UI track (LEDGER.md): OpenAPI spec for the management API first, then a native client spike.

## How to work here

- Compiler: `export TOV=$PWD/build/tov/target/release/tov` (patched; `make tov` builds it).
  Always pass it: `make build TOV=$TOV`, `make unit TOV=$TOV`. Plain `tov` on PATH is unpatched.
- Typecheck: `TOV=$TOV python3 scripts/check.py --no-fix src/*.tov src/providers/*.tov tests/*.tov`.
- e2e uses fixed ports. Always: `flock /tmp/raiju-e2e.lock env TOV=$TOV python3 tests/e2e.py`
  and again with `RAIJU_SERVER=http1`. UI: `make ui`. Tov patches: `make tov-test`.
- Shared worker brief (rules that bit before): copied to
  [handoff/worker-brief.md](handoff/worker-brief.md). Key points: worktree per worker, no
  commits by workers, no scheduled tasks or reminders, fixtures must not look like real
  secrets (GitHub push protection), never leave mocks running outside the e2e lock.
- Merging a worker: `git -C <worktree> add -A && git -C <worktree> diff --cached HEAD --binary > x.patch`,
  then `git apply -3 x.patch` in the main tree, resolve, test, commit.
- Commit trailers on this repo: `Co-Authored-By` and `Claude-Session` lines as in `git log`.
  No model names in commits.
- Bifrost reference source: clone `maximhq/bifrost` at `6c84d7a` to compare behaviour.
