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

- Waves 1 to 14 are merged on the branch above. Wave 14 (L103 to L120, L112a/b) closed every
  row: done or partial with its "Open:" remainder written in LEDGER.md.
- docs/parity.md counts 562 parity rows: done 374, partial 159, missing 5, out of scope 15,
  n/a 9, plus 35 Raiju-only extras. `make parity-count` regenerates the Summary;
  `python3 scripts/parity_count.py --check` fails when it is stale.
- Tests at handoff: `make unit` 1,544 passed, 0 failed; e2e "all passed" on both servers (Bun
  and http1); `make ui` all passed (about 160 browser checks); `make openapi-check` ok
  (336 operations); `make web-check` up to date.
- Admin UI: SolidJS 2.0 RC in `web/` (Vite on Bun, types generated from the OpenAPI spec),
  embedded in the binary through the committed `src/ui_assets.tov` and served by
  `src/uiserve.tov`; `RAIJU_UI_DIR` serves a directory instead. Building the gateway needs no
  Node or Bun; changing the UI does (`make web`, then commit). `clients/` (gpui and Slint
  spikes) is parked. The live feed is cluster-wide and resumable (L119).

## What's next

No row is queued. The remainders are the "Open:" notes in LEDGER.md (L103 to L120) and the 5
"missing" rows of docs/parity.md (dynamic plugins, `large_payload_optimization`,
`retain_content_in_object_storage`, MCP `max_instructions_length`, the agent CLI headers
`x-bf-agent-vk-id` / `x-bf-agent-auth`). The larger ones:

- Streams: Bifrost holds and replays live block-capable streams; Raiju cuts them (G43).
- WebRTC create is a pass-through with no gateway peer, so media and events after the create
  are not metered or guarded (G40, L108).
- MCP: token_exchange clients are not connected at runtime (L112b); code mode lacks while,
  try, lambda and is not on the Responses API (L117); A2A lacks REST/gRPC bindings, push and
  upstream OAuth (L116).
- UI: dashboard charts, MCP OAuth consent screens, virtual MCP and tool group editors,
  role-aware hiding of actions (L113).
- Identity-aware proxy in full mode does not consult governance for disabled users (L120).

## Open questions for the owner

1. **Dynamic plugins.** Go `.so` plugins need the Go runtime, so they are out. WASM plugins are
   possible only by linking JavaScriptCore into the gateway (about 34 MB, a 10-minute JSC build).
   Link it, or leave dynamic plugins unbuilt?
2. **WebRTC create (L108).** Keep the create-time pass-through, or build a real relay (a WebRTC
   stack in Tov or a sidecar) so media and events are metered and guarded?
3. **Key holds with breakers off (L104).** Refusals now hold a key (a 429 holds the model on that
   key for 10 s to 2 min) even when circuit breakers and adaptive routing are off. Keep, or make
   it opt-in?
4. **Held access profiles (L103).** A user's held profiles now govern all their keys, and every
   held profile is charged (Bifrost charges one paying profile). Keep the stricter rule?
5. **Accepted-but-not-applied config (L112a).** `large_payload_optimization` and
   `retain_content_in_object_storage` are buildable (a streaming request-body path, a second
   object-storage write path); the HTTP/2 and pool knobs need Tov runtime changes. Build which?

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
