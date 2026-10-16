# Handoff

Raiju is a Bifrost-compatible LLM gateway written in Tov (TypeScript syntax compiled to
native code). Work runs as a ledger with a lead and workers: the lead keeps
[LEDGER.md](LEDGER.md), hands self-contained tasks to worker agents in their own git
worktrees, then merges, tests and commits. Bifrost parity is tracked row by row in
[docs/parity.md](docs/parity.md); scope and open product items are in [SCOPE.md](SCOPE.md).

Branch: `claude/affectionate-shannon-pjwi5z`. Last lead commit before this handoff: see `git log -3`.

## Where things stand

- Waves 8 to 13 and the L97 follow-ups are merged (LEDGER.md rows L81 to L102 and L97a to
  L97t). The saved wave-12 patches were all finished and merged, so `handoff/patches/` is gone
  (recover from git history if needed).
- docs/parity.md counts 560 parity rows (done 368, partial 144, missing 11, out of scope 28,
  n/a 9) plus 34 Raiju-only extras; `make parity-count` regenerates the Summary, and
  `python3 scripts/parity_count.py --check` fails when it is stale.
- Tests at handoff: `make unit` 1,381 passed, 0 failed; e2e "all passed" on both servers (Bun
  and http1); `make openapi-check` ok (docs/openapi/management.yaml).
- UI track: OpenAPI spec done (L98); native client spike done (L99, `clients/`): gpui and Slint
  both build and share a data layer checked headless; clients/README.md recommends Slint. No
  window was opened (no display in the container); the Slint licence choice is the owner's.

## Still open (docs/parity.md "Remaining gaps", and the "Open:" notes on LEDGER rows)

- Partial rows from the L97 waves: governance (rate-limit splits, profile role binding,
  archive manifest and gzip, adaptive refusal classification), providers (Replicate text and
  edits and polling, Bedrock Stability variations, usage.cost on streams), MCP OAuth (session
  and user consent modes, grant list/revoke, persisted grants, generated signing key),
  streamed guards (built-in guard on streams, replay pacing), observability (stream
  redaction and replay), log filter agent_names (no registered agents).
- G40 live sessions beyond OpenAI and WebRTC create; G36/G37 decision routes and streamed
  compat headers; G39, G41, G48, G47, G22, G14, G17 as listed in docs/parity.md.
- Needs a real cloud account or display, not buildable here: Vertex AWS workload identity,
  object-storage archive against a real bucket, launching the native client windows.
- Owner decisions: models without a price cost 0 with a warning (as Bifrost); the exact-match
  cache is shared across virtual keys; `ignore_provider_cost` is now honoured and OpenAI-format
  `usage.cost` (OpenRouter) is billed as reported; Slint vs gpui licensing.

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
