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

Branch: `main` holds everything (PR howlerops/raiju#1 merged waves 12, 13 and L97). Start new
work on a fresh branch from `main`.

## Where things stand

- Waves 1 to 13 and L97a to L97t are merged. The saved wave-12 patches were all finished, so
  `handoff/patches/` is gone (recover from git history if needed).
- docs/parity.md counts 560 parity rows: done 368, partial 144, missing 11, out of scope 28,
  n/a 9, plus 34 Raiju-only extras. `make parity-count` regenerates the Summary;
  `python3 scripts/parity_count.py --check` fails when it is stale.
- Tests at handoff: `make unit` 1,381 passed, 0 failed; e2e "all passed" on both servers (Bun
  and http1); `make openapi-check` ok (docs/openapi/management.yaml, 300 operations).
- UI track: OpenAPI spec done (L98); native client spike done (L99, `clients/`): gpui and Slint
  both build and share a data layer checked headless against a gateway. clients/README.md
  recommends Slint. No window was opened (no display in the container).

## What's next

Wave 14 in LEDGER.md (L103 to L117) collects every open remainder: governance (rate-limit
splits, profile role binding), audit archive and adaptive LB, providers (Replicate text and
edits, streamed usage.cost, Cohere/Azure model retrieve), MCP OAuth (consent modes, grant
revoke, persisted grants, generated signing key), streams (built-in guard, replay pacing,
streamed compat headers), live sessions beyond OpenAI, decision routes, the config keys and
histograms left, `gitleaks:allow`, building the 11 "missing" parity rows, the web admin client
(L113), the per-key exact cache (L114), and SCIM, A2A and MCP code mode (L115 to L117).

## Owner decisions (2026-10-17)

The open questions from the last handoff are answered:

1. **Client toolkit.** Neither Slint nor gpui. The gateway ships as an image and already serves
   the web UI, so that is the admin client: grow `ui/` (L113). `clients/` spikes are parked.
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
  - used by e2e: 18100–18105, 18110–18112, 18114–18128, 18130–18144, 18146–18151,
    18153–18156, 18159, 18161, 18163, 18165–18168, 18193
  - openapi-check: 18190–18199; native client spike checks: 18171–18172
  - free for new workers: 18173–18189 (and the gaps above, after checking)
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
- Merging a worker: `git -C <worktree> add -A && git -C <worktree> diff --cached HEAD --binary -- . ':!LEDGER.md' ':!build' > x.patch`,
  then `git apply -3 x.patch` in the main tree, resolve, test, write the ledger row, commit.
- Commit trailers on this repo: `Co-Authored-By` and `Claude-Session` lines as in `git log`.
  No model names in commits or code.
- Bifrost reference source: clone `maximhq/bifrost` at `6c84d7a` into
  `/tmp/claude-0/bifrost-src` (the worker brief points there).
