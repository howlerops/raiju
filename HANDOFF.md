# Handoff

Raiju is a Bifrost-compatible LLM gateway written in Tov (TypeScript syntax compiled to
native code). Work runs as a ledger with a lead and workers: the lead keeps
[LEDGER.md](LEDGER.md), hands self-contained tasks to worker agents in their own git
worktrees, then merges, tests and commits. Bifrost parity is tracked row by row in
[docs/parity.md](docs/parity.md); scope is in [SCOPE.md](SCOPE.md).

**To pick this up:** paste [handoff/leader-prompt.md](handoff/leader-prompt.md) into a new
session. It sets up the machine, explains the lead/worker loop and points at the queued wave.
Worker briefs start from [handoff/worker-prompt-template.md](handoff/worker-prompt-template.md);
the rules all workers follow are in [handoff/worker-brief.md](handoff/worker-brief.md).

Branch: wave 14 is on `claude/affectionate-shannon-pjwi5z` (not yet merged to `main`; `main`
still holds waves 12, 13 and L97 from PR howlerops/raiju#1). Merge or PR that branch first, then
start new work on a fresh branch from `main`.

## Where things stand

- Waves 1 to 15 are merged on the branch above. Wave 14 (L103 to L120) and wave 15 (L121 to
  L127, the owner's "build it the correct way" decisions) closed every row: done or partial with
  its "Open:" remainder written in LEDGER.md.
- docs/parity.md counts 563 parity rows: done 376, partial 161, missing 2, out of scope 15,
  n/a 9, plus 36 Raiju-only extras. `make parity-count` regenerates the Summary;
  `python3 scripts/parity_count.py --check` fails when it is stale.
- Tests at handoff (compiler from tov-patches 0001 to 0008): `make unit` 1,620 passed, 0 failed;
  e2e "all passed" on both servers (Bun and http1); `make ui` all passed; `make openapi-check`
  ok; `make web-check` up to date; `tov-patches/tests/run.sh` passed (including std/wasm 22,
  std/rtc 20, fetch pool and HTTP/2 23, request body streams 55 checks).
- The Tov runtime carries eight patches (`tov-patches/`): 0001 to 0004 as before, 0005 WAMR
  (WASM plugins), 0006 libdatachannel (WebRTC), 0007 fetch pool and upstream HTTP/2 (nghttp2),
  0008 streamed request bodies. 0005 to 0007 vendor C libraries (several MB each). They apply in
  order only; `make tov` rebuilds the compiler (a few minutes; the first build of Raiju after it
  compiles the vendored archives once).
- Admin UI: SolidJS 2.0 RC in `web/` (Vite on Bun, types generated from the OpenAPI spec),
  embedded in the binary through the committed `src/ui_assets.tov` and served by
  `src/uiserve.tov`; `RAIJU_UI_DIR` serves a directory instead. Building the gateway needs no
  Node or Bun; changing the UI does (`make web`, then commit). The live feed is cluster-wide and
  resumable (L119).
- WebRTC live sessions terminate in Raiju (L122): set `RAIJU_WEBRTC_BIND` to bind the media
  sockets to one address and `RAIJU_WEBRTC_ICE_SERVERS` for STUN/TURN behind NAT; a session stays
  on the node that took it.

## What's next

No row is queued. The remainders are the "Open:" notes in LEDGER.md and the 2 "missing" rows
of docs/parity.md (MCP `max_instructions_length`; the agent CLI headers `x-bf-agent-vk-id` /
`x-bf-agent-auth`). The larger ones:

- Live sessions cost 0 (no per-second audio price in the datasheet); the WebSocket live path and
  the /v1/realtime SDP calls are still unmetered relays (L122).
- Large payloads stream for chat, completions and embeddings to OpenAI-format providers only;
  streamed requests count 0 tokens for budgets (L124).
- WASM plugins cover non-streaming chat (the HTTP transport hooks are not called) (L121).
- Streams: Bifrost holds and replays live block-capable streams; Raiju cuts them (G43).
- MCP: token_exchange clients are not connected at runtime (L112b); code mode lacks while, try,
  lambda and the Responses API (L117); A2A lacks REST/gRPC bindings, push and upstream OAuth (L116).
- UI: dashboard charts, MCP OAuth consent screens, virtual MCP and tool group editors,
  role-aware hiding of actions (L113).
- Upstream: the Tov patches (and the two compiler bugs found, in tov-patches/README.md) could be
  offered to Tov; only 0001 to 0004 have upstream format-patches.

## Owner decisions after wave 14 (2026-10-17)

1. **Dynamic plugins:** WASM plugins on WAMR, added to the Tov runtime as a patch (L121). No
   JavaScriptCore. Go `.so` plugins stay impossible.
2. **WebRTC:** terminated in Raiju with libdatachannel through a Tov patch (L122), as Bifrost
   terminates it with Pion.
3. **Key holds:** only under adaptive load balancing, shared across the cluster (L123).
4. **Held access profiles:** keep Raiju's stricter rule (every held profile is charged); not
   changed to Bifrost's one-payer rule.
5. **Config keys:** build large_payload_optimization (L124), retain_content_in_object_storage
   (L125), the pool and HTTP/2 knobs (L126) and beta_header_overrides (L127).

## Owner decisions (2026-10-17)

The open questions from the last handoff are answered:

1. **Client toolkit.** Neither Slint nor gpui: the admin client is the web UI the gateway
   serves from its image (L113), and `clients/` is parked. Framework: SolidJS 2.0 RC (no React),
   built with Vite on Bun, embedded in the binary as hashed assets (`RAIJU_UI_DIR` overrides).
   Tov has no browser target; the link between UI and gateway is the OpenAPI spec, from which
   the UI's types are generated. HA: the live feed must be cluster-wide with resume (L119).
   Tauri 2 around the web UI only if desktop or mobile apps are asked for later.
2. **Models without a price.** Keep the warning (cost 0). `client.refuse_unpriced_models`
   stays off by default.
3. **Exact-match cache.** Scope it per virtual key (L114).
4. **Provider-reported cost.** Keep billing `usage.cost` as reported unless
   `ignore_provider_cost` is set; extend it to streamed answers (L105).
5. **MCP OAuth signing key.** Generate one at first start and persist it; a configured key
   still wins (L106).
6. **Bedrock Stability variations.** Leave refused.
7. **Missing rows.** Build all 11 (L112, split against L110).
8. **Out of scope.** SCIM (L115), A2A agents (L116) and MCP code mode (L117) move in to P2.
   The rest stay Out: videos and containers, edge device agent, media providers, Runware, Warp,
   skills marketplace, Sidekiq.

## Can't be done in the cloud container

- Opening the native client windows (no display). Data paths are tested headless.
- The audit archive against a real object-storage bucket (covered by config and request
  builder tests only).
- Vertex with AWS workload identity, and anything else needing a real cloud account.
- Docker image builds (no Docker daemon).

## Gotchas that bit during the last waves

- **Ports.** Every e2e gateway has a fixed port. Give each worker two free ones and never
  reuse. `tests/e2e.py` refuses to start on a duplicate. Port registry:
  - used by e2e and the UI tests: 18100–18157, 18159–18161, 18163–18170, 18173–18178, 18180,
    18181, 18183, 18185, 18187, 18188, 18193
  - openapi-check: 18190–18199
  - free for new workers: 18158, 18162, 18171, 18172, 18179, 18182, 18184, 18186, 18189
    (check with `grep -oE '181[0-9][0-9]' tests/e2e.py tests/ui_e2e.mjs | sort -u` first)
- **Shared mock.** Background senders (bulk, export, alert hooks, log posts) hit the same mock;
  `background()` in tests/e2e.py filters them. A test that asserts on `/_seen` must filter too.
- **MCP tool lists change request bodies.** e2e waits for the MCP tools at startup
  (`wait_mcp_tools`); a cache-hit test that starts before that flakes.
- **http1 server.** It reads whole bodies. Use the raw `bytes` for binary uploads (a string
  round trip corrupted multipart), and `declared_post` for checks that send a too-large
  Content-Length (the server closes before reading, so a normal client gets a broken pipe).
- **Merges duplicate things.** Two workers adding the same config field or import is common;
  after every `git apply -3`, grep for duplicated fields and functions before typechecking.
- **Push protection.** Fixtures that look like AWS keys, Slack webhooks or Linear keys are
  rejected on push. Build them from string parts. Throwaway PEM keys in unit tests passed.
- **Workers.** One edited the main tree instead of its worktree; restate the rule in every
  launch line. Two created reminders and deleted them; check `list_triggers` at the end. A
  container restart kills background workers but not their worktrees; resume them with
  SendMessage. Workers sometimes report twice; compare the worktree diff before re-merging.
- **Worker worktrees start from `main`**, not from the branch tip. A worker that needs merged
  work must be told to run `git merge --ff-only <commit>` as its first step (allow it explicitly
  in the launch line). Patches are diffs against each worker's own base, so they still apply
  with `git apply -3`.
- **`git apply -3` stages what it applies.** Run `git reset -q` right after, or a later
  "ledger only" commit picks up unverified merges.
- **Keeping both sides of a conflict breaks code.** It dropped a closing brace between two new
  methods (pricing.tov, store.tov) and split an e2e function from its `finally`. After every
  union: typecheck, `python3 -m py_compile tests/e2e.py`, and check that each e2e function
  that starts a gateway still stops it.
- **docs/parity.md conflicts** need line-by-line merging of both sides' facts, then
  `python3 scripts/parity_count.py --write`; never take one side of a row blindly.
- **Generated UI files.** When the OpenAPI spec changes, run `make web` and commit
  `web/src/api/schema.d.ts` (and `src/ui_assets.tov` if the bundle changed); `make web-check`
  fails otherwise.
- **Tov runtime patches written in parallel collide.** Each worker writes its patch against
  0001 to 0004, so later ones conflict in the compiler's shared lists (check/builtins.rs,
  codegen/mod.rs, driver.rs STD_MODULES, tov.h, build.rs library list, tls_flags.rs includes).
  Rebase: in a Tov clone commit 0001-0004 as one base and the earlier patches as another, apply
  the new patch on the first base, cherry-pick it onto the second, keep both sides, then
  `git diff` the result as the new patch and prove the whole set applies from a clean checkout.
- **Verify a runtime patch with its own compiler.** Build a compiler inside the scratch worktree
  (copy build/tov there and run scripts/build-tov.sh, about 2 minutes incrementally) and run
  every check with it; rebuild the shared compiler only after the merge.
- **Workers' cleanup can kill your runs.** A worker's `pkill` matched the lead's e2e gateways and
  cut an http1 run short ("connection refused" mid-run). Rerun before blaming the code; tell
  workers to kill only processes they started.
- **After a container restart**, worker reports that were not delivered are in
  `~/.claude/projects/-home-user-raiju/<session>/subagents/agent-<id>.jsonl`: search the
  strings for the "FILES:" report.
- **e2e while merging.** e2e builds from the working tree, so don't apply a patch to the main
  tree while a run is going. Verify in a scratch worktree instead.

## How to work here

- Compiler: `make tov`, then `export TOV=$PWD/build/tov/target/release/tov` (patched).
  Always pass it: `make build TOV=$TOV`, `make unit TOV=$TOV`. Plain `tov` on PATH is unpatched.
- Unit tests need JavaScriptCore: `apt-get install -y libjavascriptcoregtk-4.1-dev`.
- Typecheck: `TOV=$TOV python3 scripts/check.py --no-fix src/main.tov tests/mock_upstream.tov`.
- e2e uses fixed ports. Always: `flock /tmp/raiju-e2e.lock env TOV=$TOV python3 tests/e2e.py`
  and again with `RAIJU_SERVER=http1`. UI: `make ui`. Tov patches: `make tov-test`.
- OpenAPI: `make openapi-check TOV=$TOV` after any /api, /mcp, /health or /metrics change.
- UI: `make web` (Bun at /root/.bun/bin) rebuilds `web/` and re-embeds it; `make web-check` must
  say up to date; `flock /tmp/raiju-e2e.lock env TOV=$TOV make ui` runs the browser checks.
  Develop with `cd web && bun run dev` against a running gateway.
- Merging a worker: `git -C <worktree> add -A && git -C <worktree> diff --cached HEAD --binary -- . ':!LEDGER.md' ':!build' > x.patch`,
  then `git apply -3 x.patch` in the main tree, resolve, test, write the ledger row, commit.
- Commit trailers on this repo: `Co-Authored-By` and `Claude-Session` lines as in `git log`.
  No model names in commits or code.
- Bifrost reference source: clone `maximhq/bifrost` at `6c84d7a` into
  `/tmp/claude-0/bifrost-src` (the worker brief points there).
