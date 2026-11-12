# Handoff

Raiju is an LLM gateway written in Tov (TypeScript syntax compiled to
native code). Work runs as a ledger with a lead and workers: the lead keeps
[LEDGER.md](LEDGER.md), hands self-contained tasks to worker agents in their own git
worktrees, then merges, tests and commits. Bifrost parity is tracked row by row in
[docs/parity.md](docs/parity.md); scope is in [SCOPE.md](SCOPE.md).

Current owned names use `RAIJU_*`, `x-raiju-*`, `sk-raiju-*`, `ck-raiju-*`,
`rt-raiju-*` and `raiju_*` metrics, with no old-name aliases. Historical parity
evidence refers to the actual reference gateway, not current wire compatibility.

**Constrained Linux qualification (2026-11-12): PASS for the bounded mock workload, not production cutover.**
Measured ARM64 Linux image (before later PR-review validation fixes) `sha256:cc1132cf23094d2fe495cff1a0ca740593e488728dcc84409b640688a605656a`;
binary SHA256 `bb59e0743a0cf21bb863aa2c262b680c956df2243cb42e7b42a84ddc1b060860`.
Two workers, authentication and stdout request logging enabled, content logging off; cgroup limits 2 CPU,
2 GiB, no swap. Client, mock and gateway communicated only inside Linux on an internal Docker network,
with synthetic credentials and no external egress. No paid inference or cloud resource changes.

- **Demand basis:** read-only seven-day production-account CloudWatch data: eu-west-1 had 1,003,290
  accepted Bedrock Runtime requests plus 180,386 throttled attempts; client/server errors are already
  included in accepted requests, not additive. Highest observed minute averaged 43.95 requests/s,
  including throttles. Titan accounted for 530,122 accepted requests and Haiku 5.5 for 472,042.
  us-east-1 had 531 accepted requests. This is account-wide demand, not a gateway routing inventory.
- **Sustained proof:** dispatched 90 short delayed requests/s plus 10 streams/s for 600 seconds, then
  drained: 60,000/60,000 valid gateway responses, zero errors or client shedding; 236 peak upstream streams.
  Each stream had 360 content frames, 23,040 content bytes and about 21 s duration. All measured requests
  reached the mock; missing auth was rejected before upstream dispatch. 60,502 request logs cover measured
  traffic plus warmup/preflight/auth rejection. Direct controls before/after completed 12,000/12,000.
- **Observed cost:** mean 0.191 CPU cores; sampled cgroup memory peak 100.67 MiB; zero OOM kills or container
  restarts; normal shutdown. Anonymous-memory half-run means rose from 38.22 to 45.01 MiB: this is bounded
  ten-minute evidence, not proof of no leak. CPU throttled time was 0.794 s across the sustained interval.
- **Latency:** stream median TTFT 2702.90 ms versus direct 2701.67–2702.07 ms (aggregate difference
  0.83–1.23 ms). Gateway TTFT p99 2779.71 ms versus direct 2710.17–2740.30 ms; stream-completion scheduled
  p99 23.38 s versus direct 21.59–21.68 s. Different run lengths and shared VM scheduling preclude a strict
  per-request overhead or production tail-SLO claim.
- **Scope:** 100 requests/s is 2.28 times the highest observed minute-average Runtime demand; it is not
  sub-minute burst coverage, an actual AWS instance measurement, or a native Bedrock/embeddings CPU test.
  The AWS role expired before separate Mantle metrics could be read; those failed queries are not zero load.
- **Failed attempts remain:** `linux-capacity-results/` records denied Docker host-address routing;
  `linux-bridge-capacity-results/` and `linux-sustained-results/` record resets/timeouts or counter-isolation
  failures on host-to-Docker traffic, including overload-stage client shedding. These are not erased by the
  isolated success and do not establish a gateway capacity ceiling. Production code/security policy unchanged.

Evidence and reproducible drivers: local ignored `build/performance/linux-network-results/{results,summary}.json`,
`cgroup-samples.jsonl`, `gateway.log`, `linux-network-capacity.cjs`, `gateway-performance.cjs`,
`summarize-linux.cjs`; production queries and coverage notes are in `build/performance/production-demand/`.

**Local performance qualification (2026-11-12):** current-source native ARM64 build completed 120 synthetic
cases with 915,100 valid responses and zero response errors; fixed-rate overload also shed 10,908 requests
at the load generator, so this is not an all-offered-traffic pass. No provider credentials or cloud resources used.
At 32 concurrent streams, minimal Raiju added 1.04 ms median first-token delay versus direct; authenticated
request logging added 16.67 ms. At 128 streams the logged profile added 31.99 ms and completed 485 streams/s.
The logged fixed-rate profile shed 2,874/4,500 offered requests at 1,500 requests/s; production capacity is
not qualified. Short windows and host/generator variability prevent treating these numbers as stable limits.
Evidence: `build/performance/current-native-results/{results,summary}.json` and
`build/performance/current-native-environment.json` (local ignored artifacts).
Binary SHA256: `684a9f99c55e9422fd460e3a25212021feb0b5a0026d8899826fcf059539f2de`.
Native Langfuse integration remains optional, not a product gate;
the [Langfuse implementation handoff](docs/langfuse-handoff.md) remains available for that separate decision.

**Performance diagnosis update:** a separate 30-case isolation run split authentication and stdout logging
into independent profiles. All 517,289 measured responses were valid and every measured request reached
the mock provider. At 32 concurrent streams, added median first-token delay was 0.87 ms for minimal Raiju,
1.07 ms for auth only, 0.85 ms for logging only, and 1.03 ms for both. The earlier 16.67 ms result is
preserved but was not reproduced; it does not establish logging as the bottleneck. The combined profile
emitted 83,904 valid success log records, covering its 80,313 measured responses plus warmup.
Evidence: `build/performance/isolation/{results,summary}.json`. Do not patch out authentication/logging
or claim a product performance fix from this comparison. Local host variability remains unresolved.
A reversed-order run then placed authenticated/logged Raiju first: at 3,000 offered requests/s it completed
the short fixed-rate window with zero errors, zero client shedding and 3.51 ms scheduled p99 latency.
At 32 concurrent streams it added 0.82 ms median first-token delay versus direct. Evidence:
`build/performance/reversed-overload/{results,summary}.json`. The earlier overload was not reproduced.
These conflicting short local runs establish neither a stable capacity ceiling nor an AWS production SLO.
The owner's Langfuse UI screenshot reports **4.77.0 OSS**; the infrastructure repository's 4.3.1 pin is
checked-in intent, not the observed running version. Neither is evidence that the cluster runs 4.79.0.
The owner identified roughly $800 potential exposure for a successful paid soak; that is not a verified invoice.
Future live checks require an explicit aggregate spend/request cap, not merely remaining provider credits.

**To pick this up:** paste [handoff/leader-prompt.md](handoff/leader-prompt.md) into a new
session. It sets up the machine, explains the lead/worker loop and points at the queued wave.
Worker briefs start from [handoff/worker-prompt-template.md](handoff/worker-prompt-template.md);
the rules all workers follow are in [handoff/worker-brief.md](handoff/worker-brief.md).

Qualification PR branch: `codex/raiju-production-qualification`, based on `a930011`. Waves 1 to 32 are on
`main` (PRs howlerops/raiju#11 and howlerops/raiju#13). This batch adds the documented clean name cutover,
qualification fixes and evidence; it does not authorize production deployment.

## Where things stand

- **Disposable dev qualification is complete, with a failed sustained-traffic gate; production cutover is not approved.**
  The owner approved the full dev stack, a full 24-hour soak and teardown in account `537124952465`, `eu-west-1`,
  prefix `raiju-proof-20261110`. Fresh cryptographic state and exact external source/history names are approved.
  Baseline: `a93001198b52189a6e1f1eb9f24a1c3f2fde1faa`; current immutable ARM64 image:
  `sha256:841d6666a762061920744092c51f5d03f635f90c4e86d4307762a8f385d67ca5`.
  Builder/runtime executable SHA256: `bb59e0743a0cf21bb863aa2c262b680c956df2243cb42e7b42a84ddc1b060860`.

  | Exercised gate on the current image | Result |
  |---|---|
  | Linux units / typecheck | 2,544 passed, zero failed / passed |
  | Complete E2E / independent embedding wire oracle | Bun and http1 passed |
  | Hardened image boot / CI-policy vulnerability scan | 20 checks passed / passed |
  | Real dev IRSA models / Mantle installed SDKs | 22/22 / 17/17 |
  | Real STS lifetime, two unchanged processes | Passed after 3,600 + 30 s; zero restarts; default SDK/native Titan vectors identical at 1,024 dimensions |
  | Baseline-to-current rolling, unencrypted config and OAuth off | 1,160 creates and 1,160 updates including mixed-version bridge; zero loss; 447 good readiness samples |
  | Node-pinned OAuth stop-first / enabled-backend DCR and trickle | Passed; grant, refresh and pending consent survive |
  | Three-node preflight | 20 passed, zero failed, one explicit MCP-off skip |
  | EFS concurrent writes / legacy-lock bridge | 120 creates and updates, zero loss; ages 0, 6 and -8 s passed |
  | Live config flock holder killed with SIGKILL | 40 queued writes acknowledged/persisted, zero early completions or loss |
  | Actual NFS isolation and lease expiry | Eight writes recover after 62.71 s while holder is alive; zero loss, read on all three nodes |
  | Partition/rejoin and primed cluster counter | Passed; all nodes remain 429 within the same window; listener, sync and nine log rows pass |
  | Actual ALB audit attribution | Independent caller IP matched; forged X-Forwarded-For rejected |

  **The installed consumer SDK matrix is not all green:** 13 passes, one strict counterexample:
  `finish_reason:stop` accompanies valid forced `tool_calls`. A fresh direct `api.openai.com` matched
  request reproduces it; no gateway normalization was added. Explicit tool-call parsing and LangChain
  tool/result continuation pass. Whole customer graphs, independent billing and provider-side billing cessation
  are not proved. Current evidence and original failures: ignored `build/proof/2026-11-10/final-artifact.json`,
  `renewal-infrastructure-final.json`, `consumer-sdk-cloud/`, `eks-irsa-renewal/`, and `eks-mantle-renewal/`.
  Superseded images and their failures remain separate; do not attribute their results to the current image.

  **The full 24-hour run completed and failed.** Run `20261110-attempt5` started
  `2026-11-11T06:10:16.856Z`, with 172,800 completed requests and 1,412/1,412 valid samples spanning 86,401 s.
  There were 60,220 accepted inferences, 60,198 intentional discard-body responses, 165 recognized refusals
  and 52,217 errors (30.22%, above the 1% gate). Every counted error was HTTP 429; the retained terminal
  provider message says **“You have no credits remaining.”** Accepted inference stopped increasing at about
  12.86 h. Individual earlier 429 bodies are not retained, so do not attribute every historical response
  independently. No extra provider spend or rerun is approved.

  Memory met its numeric bounds: 168 MiB peak, 8.23 MiB growth over the second half, 140 MiB at the end,
  zero memory-inferred restarts; the exact same sole gateway task was healthy at completion. Source:
  ECS/ContainerInsights service `MemoryUtilized`, **not process RSS**. This does not pass the full real-traffic
  gate: successful upstream inference did not continue for 24 h. The original failed verdict is preserved.
  Runner `ee068f4dbed64e728865e7fdc37d249e`; gateway task `3a76fc30913a40be8164e036dafadde6`.
  Evidence: `completed-soak-disposition.json`, `completed-soak-evidence-index.json`, and
  `cloud-evidence/ee068f4dbed64e728865e7fdc37d249e/` under the ignored proof directory.
  Operator MFA expiries interrupted only local collection; normal refresh resumed the same run, without
  restarting the gateway or shortening the measurement. Candidate smoke before the run passed OpenAI 8/8
  and Anthropic 7/7, with one unsupported-embedding skip.

  Real Okta/Entra is explicitly unproven and accepted: no disposable tenants are available. The owner excluded
  `/mcp` from Totango cutover: process-local transport sessions return HTTP 400 across nodes. Node-pinned
  OAuth continuity is not transparent multi-node MCP support. Native macOS is not qualified: the prior adapter
  run had 713 passes/36 failures, including Linux `/proc` dependence. Earlier contextual HTTP timeouts did not
  recur in complete current-image runs; their root cause remains unproven.

  The current build also fixes awaited MCP credential persistence before releasing its renewal lease; its
  existing two-worker expiry/401 regression passes nine checks. Earlier fixes cover SDK float32LE/base64
  embeddings, shared signing-state initialization and compiler patch 0025's real Linux JSC GC initialization.
  Future OAuth state fails startup. Obsolete key-length, directory-snapshot and buffered-output wording tests
  were deleted rather than repinned. No crash-atomic provider/disk transaction is claimed.

  **Approved teardown is complete:** `teardown-result.json` reports PASS; Terraform state is empty.
  ECS/ALB/EFS/CloudMap, owned roles/security groups, manual DNS and ECR are removed; provider-secret
  deletion was requested without a recovery window. AWS may retain asynchronously deleting secret records
  and task-definition tombstones. EKS leaves/namespace/network policy and dedicated IRSA role/policy were
  already removed; the source Mantle credential/version and existing releases stayed unchanged.
  Existing VPC, NATs, certificate, cluster/node roles and source AWS credentials were not teardown targets.
  Sensitive local plan/state-backup/credential copies and the generated proof overlay were removed after destroy;
  the empty current Terraform state, source `.env`, local image and safe evidence are retained.
  The private EFS state and cores were not exported; their filesystem was destroyed.

  UI at `http://127.0.0.1:18480` was visually verified as `proof-ui-viewer · viewer`, then its owned
  forward stopped for teardown. It is no longer running; do not reuse its removed credential copy.
  Setup help uses `RAIJU_SETUP_TOKEN` / `X-Raiju-Setup-Token`.
  [Gateway comparison](docs/gateway-evaluation.md): Langfuse 4.78.0 is not a drop-in for required IRSA/SigV4,
  Mantle and cross-format contracts. Existing OSS Langfuse is 4.3.1; no shared upgrade or live benchmark was done.
  Next: restore provider credit/quota with owner approval, then explicitly authorize any replacement
  sustained successful-traffic run and associated spend. Keep the failed run unchanged. Before production
  promotion, exercise the actual application graphs and cutover/privacy/policy/tracing plan; retain accepted
  identity/MCP limitations and the upstream terminal-reason compatibility risk. No rerun or production change is authorized.

- Waves 31 and 32 (L212 to L219): L212 to L214 closed the gaps listed after wave 30 (connect-time address checks on
  raw sockets and a write-stall limit on Bun.serve WebSockets through Tov patch 0022; async and provisioning jobs that
  survive restarts and cross nodes, cluster-wide sign-in throttling; the AWS default chain and ~/.aws/config
  profiles and the parity tail). L215 runs the Docker image job on pull requests: build, a boot smoke as the chart
  runs it (tests/image_smoke.py) and a trivy scan, green. The seventh re-audit
  (docs/audits/production-reaudit-7-2026-10-31.md) found two leaks and four P1s, all fixed: about 50 bytes per
  keyed inference request (a Tov compiler bug, `continue` not releasing loop locals, fixed by patch 0023; L216),
  2 to 16 KB per closed WebSocket session (L217), reservation cuts (L218) and uncapped MCP sessions (L219). CI's
  memory soak job now runs four soaks (`soak`, `soak-bodies`, `soak-websockets`, `soak-slope`). Behaviour changes
  are in docs/behaviour-changes-wave-31.md.
- Wave 30 (L210, L211): the sixth re-audit (docs/audits/production-reaudit-6-2026-10-26.md) found a memory leak since
  wave 26 (every body over 64 KB stayed resident); it is fixed and `make soak-bodies` in the CI soak job fails on RSS
  growth. Declared-length reservations are cut when behind pace, and small requests no longer block a lone big body.
  The auditor knew of no other code blocker for multi-tenant production once these were fixed. L211 adds the staging
  validation kit for what only real infrastructure can confirm: docs/staging-validation.md, tests/staging, a manual
  staging workflow and deploy/terraform/examples/staging. Behaviour changes are in docs/behaviour-changes-wave-30.md.
- Wave 29 (L208, L209) fixed the fifth re-audit (docs/audits/production-reaudit-5-2026-10-26.md): the request-body
  cap is a hard memory bound again with a per-tenant share and a reserve for idle tenants, declared lengths are
  reserved at admission, and name uniqueness accepts updates that keep their name. Behaviour changes are in
  docs/behaviour-changes-wave-29.md.
- Wave 28 (L205 to L207) fixed the fourth re-audit (docs/audits/production-reaudit-4-2026-10-25.md): checked
  bodies keep a minimum rate over a sliding window with a ceiling and a per-credential share, and the broker checks
  signed heads; MCP OAuth registration is stateless (sealed client_ids); Math.random is seeded from getrandom per
  worker (tov-patches 0021) and entity ids come from secureHex; concurrent config writes on a worker are group
  committed, and key, team and customer names are unique. Behaviour changes are in docs/behaviour-changes-wave-28.md.
- Wave 27 (L202 to L204) fixed the third re-audit (docs/audits/production-reaudit-3-2026-10-25.md): the config
  lock is held only around reread-merge-save with network I/O outside it and a bridge to the wave 25 lock for
  rolling upgrades; MCP OAuth registration is bounded and authorize stores nothing; the OIDC state is bound to
  the browser and its key comes from cluster.secret when clustered; /mcp is judged from the headers, unchecked
  bodies get a small budget share and a short deadline, checked bodies a minimum rate, and peer POSTs a signed
  head. Behaviour changes are in docs/behaviour-changes-wave-27.md.
- Wave 26 (L200, L201) fixed the second re-audit (docs/audits/production-reaudit-2-2026-10-25.md): file
  locks are flock(2) with async waits (tov-patches 0020), OIDC login stores nothing per request, cluster
  peer routes refuse unsigned bodies before reading and cap them, and the body budget counts bytes as they
  arrive with a deadline. Behaviour changes are in docs/behaviour-changes-wave-26.md.
- Wave 25 (L195 to L199) fixed the production re-audit (docs/audits/production-reaudit-2026-10-25.md):
  the cluster secret is resolved from env and enforced (32 bytes or more) with an optional cluster
  listener and a /metrics token (L195); credentials are checked before large bodies are read and a
  per-process cap bounds buffered bodies (L196); config saves from several workers are merged under a
  file lock, and sessions, agent tokens and jobs are shared by a node's workers (L197); bcrypt
  passwords, sign-in throttling and trusted proxies (L198, tov-patches 0017); a worker killed by the
  OOM killer is respawned (tov-patches 0019), a workable ECS module, versioned state files and an
  upgrade notice (L199). Behaviour changes are in docs/behaviour-changes-wave-25.md.
- Wave 24 (L188 to L194): the runtime checks each connection's resolved address (tov-patches 0013,
  DNS rebinding closed for fetch; every provider connection checked as Bifrost's ConfigureDialer);
  WebSocket and WebRTC sessions drain at a stop, broker mode stops gracefully, http1 drops stalled
  readers, per-stream memory is lower (tov-patches 0016) and the UI has a setup-token screen (L189);
  TLS client certificates, a client-disconnect signal, gRPC gzip and the AWS credential chain
  (tov-patches 0015; L190); SCIM directory sync for five IdPs against mocks (L191); realtime turn
  hooks, per-fallback hooks, Maxim tracing and Bifrost's MCP identity order (L192); cross-node log
  reads, payload offload to object storage and guardrail logs_only (L193); Hugging Face
  multi-backend routing, agent sign-in tokens and the A2A v0.3 REST client (L194). Behaviour
  changes are in docs/behaviour-changes-wave-24.md.
- Wave 23 (L174 to L187) paired a production-readiness audit with the parity work packages.
  Production: secure defaults (/api locked, loopback bind, MCP deny-by-default, WebRTC off,
  bounded metric labels, 0600/0700 files; L184), the streaming memory leak (reference cycles;
  per-stream memory 324 KB to 169 KB, soak growth +23 MB to +2.7 MB; L182, `make soak`), graceful
  stop, server timeouts, a connection cap and /ready (L183, tov-patches 0012), config changes
  reaching every worker and node (L185, cluster.config_sync), the netguard rewrite with
  connect-time DNS checks and pinned plugin downloads (L186, SECURITY.md), and deployment (helm
  persistence and probes, a setup-token Secret, `raiju -healthcheck`, pinned images, trivy and a
  generated docs/config-reference.md checked in CI; L187). Parity: extra params and the stop
  reason (L174), API remainders (L175), plugin pipeline completeness (L176), MCP remainders
  (L177), virtual-key ownership of provider files and batches, the logs_only reveal mapping and
  earlier-day log reads (L179), config keys, JWT algorithms and adaptive ranking (L180), and
  provider long-tail items, SCIM claim sync and Vertex workload identity (L181). Behaviour changes
  are in docs/behaviour-changes-wave-23.md; read it before upgrading a deployment.
- Waves 20 to 22 (L156 to L173) followed a triage of every partial parity row: CI
  (`.github/workflows/ci.yml`, `scripts/ci.sh`), an opt-in real-provider smoke suite (`make smoke`),
  tov-patches 0009 (node:fs rename/fsync, atomic state writes) and 0010 (a WASM wall-clock limit),
  a use-after-free fix in 0008, native decisions and text completions, provider operation gaps,
  governance and RBAC API remainders, MCP OpenAPI import, library, user mode and persisted OAuth
  flows, logs and audit remainders, realtime client tokens and transcription sessions, plugin
  hooks on every route, A2A versions, failover and gRPC-only agents, stream idle timeouts and
  oauth_key_config, and the provider leftovers. 40 rows were closed as already built or matching
  Bifrost. Behaviour changes are listed in docs/behaviour-changes-waves-20-22.md.
- Upstream: tov-patches/upstream/ holds write-ups and format-patch series for every patch, and
  compiler-bugs.md (issue-ready reports; C6, a string `switch` with `break` cases corrupting
  memory, matters for anyone writing Tov). Offering them to Tov is the owner's call.
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
- docs/parity.md counts 567 parity rows: done 532, partial 11, missing 0, out of scope 15,
  n/a 9, plus 42 Raiju-only extras.
- Tests at handoff (compiler from tov-patches 0001 to 0010, 0012, 0013, 0015 to 0017, 0019 to 0023): `make unit` 2,535 passed,
  0 failed, plus the Python tests (gen_pricing, the h2/gRPC interop suite, crew_priors,
  test_deploy, test_gen_config_doc); e2e "all passed" on Bun and http1; `make ui` all passed;
  `make openapi-check` ok; `make web-check` and `make config-doc-check` up to date; the four memory soaks pass
  (slope 5 B/request on Bun, 4 on http1). Helm lint and terraform validate pass; the Docker image is built, boot-tested
  and scanned in CI (no Docker daemon here).
- Test tools now needed: `pip install grpcio protobuf h2 numpy scipy`, and Go with GOTOOLCHAIN=go1.26.9 for
  the A2A gRPC e2e client (tests/a2a_grpc_client; e2e skips it if go is missing).
- The Tov runtime carries sixteen patches (`tov-patches/`): 0001 to 0004, 0005 WAMR (WASM
  plugins), 0006 libdatachannel (WebRTC), 0007 fetch pool and upstream HTTP/2 (nghttp2), 0008
  streamed request bodies, 0009 node:fs rename and fsync, 0010 a WASM wall-clock limit, 0012
  server lifecycle (graceful stop, timeouts, connection cap), 0013 the fetch peer address policy,
  0015 TLS client certificates, Request.signal and gunzip, 0016 a small fetch input buffer, 0017
  server.requestIP, 0019 worker respawn after SIGKILL and Bun.plainAlloc, 0020 flockSync, 0021 random seeding, 0022 the raw-socket address policy and the WebSocket write-stall
  limit, 0023 `continue` releasing loop locals (a compiler fix). 0011, 0014 and 0018 are
  unused. They apply in order only; `make tov` rebuilds the compiler.
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

Real tests on real infrastructure, from another machine: run the staging validation kit (docs/staging-validation.md,
tests/staging, the manual staging workflow, deploy/terraform/examples/staging). It needs an AWS sandbox account,
provider API keys and an Okta or Entra developer tenant, and covers what no test here can: flock on EFS/NFS, real
rolling upgrades, memory under real traffic, real identity providers, multi-node networking and the ECS module
applied on AWS. Then re-audit against what it finds.

- Real providers: `make smoke` has never run against real keys (none in this environment).
- Crew routing: fit real priors and a classifier from your own evaluation data.
- Upstream: offer tov-patches/upstream to Tov (0013, 0015, 0016, 0017, 0019 to 0022 have no write-up yet; 0023 is
  compiler-bugs C10).

## Owner decisions after wave 22 (2026-10-24)

1. /api is locked by default like Bifrost: with no admin user and no setup_token it answers 403 (reverses the L97g choice to keep it open).
2. MCP is denied by default for a virtual key with no mcp_configs, as Bifrost does.
3. Realtime WebRTC calls are off by default (explicit enable); WebSocket realtime is unaffected.
4. Built-in role permissions (admin, editor, viewer, auditor) are editable, as in Bifrost.
5. Kept as Raiju's design (rows close as "differs by design"): the JSON config file and JSONL log store (no sqlite, postgres or clickhouse stores); CEL routing rules, complexity_router settings and its heuristic scorer; reporting 4 of Bifrost's 10 latency overhead components.
6. Production hardening and the remaining parity work run interleaved.

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
