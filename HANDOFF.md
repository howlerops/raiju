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

Branch: `claude/affectionate-shannon-pjwi5z`, restarted from `main` after PR howlerops/raiju#2
(waves 14 to 17) merged. It carries wave 18 and wave 19 so far; not yet in a PR.

## Where things stand

- **In progress (waves 20 to 22, branch claude/affectionate-shannon-pjwi5z, not yet on main).**
  Merged on the branch: L156 (CI: `.github/workflows/ci.yml`, `scripts/ci.sh`), L157 (`make smoke`,
  and a use-after-free fix in tov-patches/0008), L158 (tov-patches/0009, atomic state writes), L159
  to L169, L171. A triage of every partial row is in the parity notes and LEDGER wave 21/22 rows.
  Still to merge (each worker left its change unstaged in its worktree under .claude/worktrees/,
  with its diff at /tmp/claude-0/<id>/mine.patch when it rebased): L168 (in verify), L170 (adds
  tov-patches/0010, a WASM wall-clock limit: rebuild the shared compiler after merging), L172,
  L173 (its rebase onto 642ff0f was cut off by the account's weekly usage limit; resume that
  worker or redo the rebase), and the upstream Tov material (tov-patches/upstream/: write-ups and
  format-patch series for 0005-0010, compiler-bugs.md, README.md). Behaviour changes to list in
  the PR: docs/behaviour-changes-waves-20-22.md.

- Waves 1 to 17 are on `main`. Wave 18 (L142 to L149) built the open items left after wave 17:
  the A2A gRPC binding (an h2c server, HPACK and gRPC framing written in Tov on raw sockets, a
  protobuf codec for lf.a2a.v1, the binding itself), transcription and speech billing, large
  Responses, Messages and embeddings converted as they stream, a replicated cluster state channel
  with a file lease (MCP renewals done once per cluster), and A2A push configs and cards shared
  across workers and nodes. Wave 19 (L150 to L155) built crew routing (task-level multi-model
  routing after "Pareto Crewing", docs/crew-routing.md): the math, the task classifier, offline
  priors and classifier training, the gateway wiring, outcomes with credibility learning, budget
  pacing and escalation, and the Crews tab with metrics. The price table was regenerated from the
  current Bifrost datasheet.
- docs/parity.md counts 565 parity rows: done 377, partial 164, missing 0, out of scope 15,
  n/a 9, plus 41 Raiju-only extras. Wave 18 narrowed "Open:" notes; no row changed status.
- Tests at handoff (compiler from tov-patches 0001 to 0008): `make unit` 1,949 passed, 0 failed,
  plus the Python tests (gen_pricing, the h2/gRPC interop suite with grpcio and h2, crew_priors);
  e2e "all passed" on Bun and http1; `make ui` all passed (333 checks); `make openapi-check` ok;
  `make web-check` up to date.
- Test tools now needed: `pip install grpcio h2 numpy scipy`, and Go with GOTOOLCHAIN=go1.26.9 for
  the A2A gRPC e2e client (tests/a2a_grpc_client; e2e skips it if go is missing).
- The Tov runtime carries eight patches (`tov-patches/`): 0001 to 0004, 0005 WAMR (WASM
  plugins), 0006 libdatachannel (WebRTC), 0007 fetch pool and upstream HTTP/2 (nghttp2), 0008
  streamed request bodies. They apply in order only; `make tov` rebuilds the compiler.
- Admin UI: SolidJS 2.0 RC in `web/`, embedded through the committed `src/ui_assets.tov`;
  charts with zoom and series toggles, MCP access and virtual MCP screens, role-aware actions
  (L132), and a Roles tab that edits custom roles (L141). `make web` after any
  spec change.
- Realtime and live sessions are metered, guarded and billed on every path (WebRTC, WebSocket,
  realtime calls on Raiju's own peer). Set `RAIJU_WEBRTC_BIND` and `RAIJU_WEBRTC_ICE_SERVERS`
  for deployment.
- Audio is billed (L144): transcriptions by audio tokens then seconds, speech by characters. The
  built-in price table (`src/pricing_data.tov`) was regenerated on 2026-10-19 from the current
  Bifrost datasheet (https://getbifrost.ai/datasheet, 4,765 priced entries, its audio, per-second and
  per-character rates included): `python3 scripts/gen_pricing.py <datasheet.json>`. Pricing sync at
  runtime overrides the table.

## What's next

No row is queued; the remainders are the "Open:" notes in LEDGER.md. The larger ones:

- Crew routing: fit real priors and a classifier from your own evaluation data
  (`scripts/crew_priors.py`; the built-in classifier and empty priors are placeholders);
  reasoning_effort is applied on chat completions only; per-role credit from a whole-task outcome is
  an approximation (L154, L155).
- Pricing: Gemini transcription carries no usage on its native path, so it costs 0 (L144).
- Large requests: completions to other formats and Titan embeddings buffer; Bedrock Messages
  streams are replayed (L136, L146).
- A2A gRPC: no TLS (as Bifrost), no ErrorInfo details, GRPC-only upstream agents are not dialed
  (L148).
- config.json writes are not atomic: Tov's node:fs has no rename (a runtime patch would add it;
  L147).
- Plugins: compiled-in plugins stay chat-only on the provider-format routes; embedContent,
  Bedrock rerank, count-tokens and batch routes are not hooked (L139).
- Realtime: transcription sessions and ephemeral ek_ tokens (L137).
- Streams under block-capable guards arrive after the answer ends (L131, by design).
- Upstream: the Tov patches and the compiler bugs found could be offered to Tov.

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
  - 18100–18189 is full (18171 is the only gap); openapi-check uses 18190–18199
  - 18200–18267: waves 16 to 19, handed out four per worker (L142 18220–18223 ... L155 18264–18267);
    a port listed in tests/e2e.py is taken
  - free for new workers: 18268 and up (check with `grep -oE '18[0-9]{3}' tests/e2e.py
    tests/ui_e2e.mjs | sort -u` first)
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
- **Workers that skip the lock break everyone's e2e.** One worker left 28 gateways and mocks running
  outside the lock (ppid 1) and every later e2e failed with "Address already in use". Before trusting
  a red e2e, list orphans: `ps -eo pid,ppid,cmd | awk '$2==1' | grep -E 'build/raiju|_mock'`.
- **Never run Python from the shared scratchpad.** A worker left a `bisect.py` there, which shadowed
  the standard library for every script run in that folder.
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
