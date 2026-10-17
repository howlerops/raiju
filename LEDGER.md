# Work ledger

The lead keeps this file current. Workers build one self-contained module each
(in its own worktree, against `docs/agent-brief.md`); the lead reviews, tests,
integrates and commits. Priorities come from [SCOPE.md](SCOPE.md).

Status: `todo` → `assigned` → `review` → `done` (or `blocked`, `rework`).

## Waves 1–3 (all done)

| ID | Work | Pri | Files | Status | Verified by |
|---|---|---|---|---|---|
| L01 | Streaming HTTP/1.1 server on raw sockets | P0 | `src/http1.tov` | done | unit + e2e (slow upstream proves incremental chunks) |
| L19 | WebSocket server for http1 | P0 | `src/ws.tov` | done | unit (RFC vectors) + e2e realtime relay |
| L20 | Incremental stream converters | P0 | `src/streams.tov` | done | unit (byte-split streams, CRCs) + e2e Anthropic stream |
| L02 | Anthropic Messages in → any provider | P0 | `src/providers/anthropic_in.tov` | done | unit + e2e (plain and streaming to OpenAI) |
| L03 | Responses API | P1 | `src/responses.tov` | done | unit + e2e (passthrough, translated, streaming) |
| L04 | Circuit breakers + adaptive load balancing | P1 | `src/health.tov` | done | unit (router: breakers, adaptive weights) |
| L05 | Guardrails (PII, secrets) | P1 | `src/guardrails.tov` | done | unit + e2e (prompt redaction) |
| L06 | Vertex AI (RS256 JWT, OAuth, provider) | P1 | `src/base64.tov`, `src/jwt.tov`, `src/providers/vertex.tov` | done | openssl-matched signature; e2e token exchange + cache |
| L07 | Routing rules (CEL subset) | P1 | `src/cel.tov` | done | unit + e2e (header rule) |
| L08 | Docker, compose, Helm | P1 | `Dockerfile`, `deploy/**` | done (image build untested: no Docker daemon here) | helm lint/template, compose config |
| L09 | Request log store | P1 | `src/logstore.tov` | done | unit + e2e (/api/logs, stats, JSONL files) |
| L10 | OpenTelemetry | P1 | `src/otel.tov` | done | unit + e2e (OTLP export, traceparent, gen_ai.*) |
| L11 | Cohere | P1 | `src/providers/cohere.tov` | done | unit |
| L12 | MCP client + tool execution | P1 | `src/mcp.tov` | done | unit + e2e (mock MCP server) |
| L13 | Config store, management API, admin auth | P1 | `src/store.tov` | done | unit + e2e (CRUD, hot reload, redaction) |
| L14 | Semantic cache | P1 | `src/semcache.tov` | done | unit + e2e (near-duplicate hit, unrelated miss) |
| L15 | Audio, images, files, batches | P1 | `src/media.tov` | done | unit + e2e (binary audio) |
| L16 | Plugins | P1 | `src/plugins.tov` | done | unit + e2e (mocker, header, maxtokens) |
| L17 | Web UI | P1 | `ui/index.html`, `src/ui_assets.tov` | done | Chromium test against a real gateway (`make ui`) |
| L18 | Async jobs, rerank, count tokens | P1 | `src/jobs.tov`, `src/extras.tov` | done | unit + e2e |

## Lead-owned

| ID | Work | Status |
|---|---|---|
| X01 | Integrate each module; e2e coverage per feature | done for everything above |
| X02 | Model aliases | done |
| X03 | Keep SCOPE.md and README in sync | ongoing |
| X04 | Real streaming on the `http1` server (default), WebSocket realtime on it, binary bodies | done |
| X05 | Semantic cache in the request path (embed on exact miss) | done |

## Defects found in review (all fixed)

- Config saves dropped every section the store didn't list (auth_config, routing_rules, otel, logs_store, mcp, plugins): now copy-and-modify, with a regression test.
- Virtual key secrets came from Math.random: now the kernel CSPRNG (`crypto.secureHex`).
- UI expected `/api/providers` as a list and deleted keys by name: server fixed to match.
- Adaptive weights compared latency across unrelated models: now only among the candidates.
- Responses route echoed the upstream body instead of the request (shadowed variable).
- README claimed a static binary; it links glibc.
- scripts/check.py applied safe fixes at byte offsets; tov reports character columns (corrupted edits on non-ASCII lines).
- Interface-held class instances crashed (Tov bug): converters and the WebSocket sink are concrete classes now.

## Wave 5 (P2, done)

| ID | Work | Files | Status | Verified by |
|---|---|---|---|---|
| L21 | Session affinity | `src/affinity.tov` | done | unit + e2e (a session stays on the key that worked) |
| L22 | Complexity router | `src/complexity.tov` | done | unit + e2e (tier map behind `auto`, header override) |
| L23 | MCP agent mode | `src/agent.tov` | done | unit + e2e (tool call run by the gateway, final answer) |
| L24 | Gateway as an MCP server | `src/mcpserver.tov` | done | unit + e2e (initialize, tools/list, tools/call, session required) |
| L25 | Audit log | `src/audit.tov` | done | unit + e2e (actor, denied changes, verify, JSONL export) |
| L26 | RBAC | `src/rbac.tov` | done | unit + e2e (viewer reads, can't write, can't read audit) |
| L27 | Secret managers | `src/secrets.tov` | done | unit (SigV4 vectors) + e2e (Vault KV v2 key) |
| L28 | Alerting | `src/alerts.tov` | done | unit + e2e (webhook fires, state visible) |

## Wave 6 (done)

| ID | Work | Files | Status | Verified by |
|---|---|---|---|---|
| L29 | Log exports to S3/GCS-compatible storage | `src/exports.tov` | done | unit (AWS SigV4 S3 examples) + e2e (signed PUT of JSONL) |
| L30 | SSO (OIDC) for the UI and management API | `src/oidc.tov` | done | unit (RS256, claims) + e2e (test IdP: PKCE, role from groups, single-use state, audit actor) |
| L31 | Clustering: shared budget and rate-limit counters | `src/cluster.tov` | done | unit (CRDT laws) + e2e (two nodes share a 3-request limit) |
| L32 | Vertex and Cohere stream converters | `src/streams_cohere.tov`, `providers/vertex.tov` | done | unit (byte-split Cohere streams) |

Integration glue (lead): `src/ops.tov` (RBAC gate, audit, alert, cluster and export timers, `/mcp`, OIDC routes, secrets).

## Lead-owned (waves 5–6)

| ID | Work | Status |
|---|---|---|
| X06 | Patch Tov so `Bun.serve` streams `ReadableStream` bodies (`tov-patches/`, `scripts/build-tov.sh`); `Bun.serve` is now the default server, streaming in every worker | done: e2e on both servers, 2 workers 36k rps vs 16k for one process |
| X07 | Outbound proxies (`proxy_config`; Tov's fetch has `proxy`), LiteLLM/LangChain route prefixes, OCR pass-through | done: e2e (proxy request line and credentials, prefixed routes, `/v1/ocr`) |
| X08 | stdio MCP servers | superseded by X11 |

## Defects found in review (waves 5–6, fixed)

- Agent mode dropped the last call's headers (request id, cache, attempts): it now keeps them.
- RBAC let viewers and editors read the audit log: it is now limited to admins and auditors.
- `scripts/check.py` applied "safe" fixes that cascaded from an unrelated error (it added `throws` and `try` across three files). Re-check after fixing the root error; don't apply fixes while it is red.
- A mock left running from a manual test made e2e flaky (port already bound). Kill stray processes before suites.

## Wave 7 (everything left in SCOPE.md, done)

| ID | Work | Pri | Files | Status |
|---|---|---|---|---|
| L33 | Guardrail integrations: AWS Bedrock Guardrails, Azure AI Content Safety, Patronus, generic webhook | P2 | `src/guardrail_providers.tov` | done: unit (SigV4 checked against Python) + e2e (block, redact, output block) |
| L34 | Access profiles: reusable permission sets (providers, models, budgets, rate limits, MCP tools) for virtual keys | P2 | `src/profiles.tov` | done: unit + e2e (required header, model limit, max_tokens cap, MCP tools, API, delete guard) |
| L35 | Virtual MCPs: named tool sets assembled from several MCP servers, served at `/mcp/{name}` | P2 | `src/vmcp.tov` | done: unit + e2e (renamed tool, defaults, 404, listing) |
| L36 | MCP auth: OAuth 2.1 for MCP servers (client credentials, refresh tokens, token cache) | P2 | `src/mcpauth.tov` | done: unit + e2e (client credentials, token reuse) |
| L37 | Required headers (reject requests missing configured headers) | P2 | lead: `governance.tov` | done: unit + e2e |
| L38 | Exporters: request logs to Datadog, Splunk HEC, Elasticsearch, generic HTTP | P2 | `src/exporters.tov` | done: unit + e2e (HTTP NDJSON, Elasticsearch bulk) |
| L39 | Long-tail providers (OpenAI-compatible family + IBM watsonx) | P2 | `src/providers/longtail.tov`, `src/providers/watsonx.tov` | done: unit + e2e (watsonx IAM + chat, NVIDIA) |
| L40 | Terraform: Helm release module and AWS ECS Fargate module | P1 | `deploy/terraform/**` | done: terraform fmt + validate on all three examples (no plan/apply: no cloud account) |
| L41 | Embeddings for Gemini, Bedrock (Titan, Cohere) and Vertex | P0 | `src/embeddings_native.tov` | done: unit + e2e (Gemini batch, Titan one call per input) |
| L42 | Anthropic SDK route streaming from any provider (OpenAI SSE → Anthropic events) | P0 | lead: `gateway.tov`, `native.tov` (anthropic_in already had the converter) | done: e2e (incremental events from an OpenAI-format upstream) |

| ID | Lead work | Status |
|---|---|---|
| X09 | Share budget, rate-limit and cache state between the worker processes of one node | done: file gossip of the CRDT counters + shared cache files; e2e on 3 workers |
| X10 | Build and run the Docker image (a daemon runs here now) | done: found and fixed two bugs (no g++ for BoringSSL; libstdc++ missing at runtime → distroless/cc); image 10.7 MB, serves with -workers 2 |
| X11 | stdio MCP servers: Tov patch for spawning processes with pipes | done: patch 0002 (`Bun.spawnSocket`); e2e; one server per worker, killed with it |
| X12 | Package the Tov patches for upstream (description, tests) | done: `tov-patches/README.md`, `tov-patches/tests/run.sh` (opening the upstream PR needs access to richiemcilroy/Tov) |
| X13 | SCOPE.md and README in sync | done |

## Defects found in review (wave 7, fixed)

- Two Docker image bugs that only a real build showed: g++ was missing for BoringSSL, and libstdc++ was missing in the runtime image.
- The guardrail webhook mock recorded its calls, which broke every test that reads the last upstream request.
- Access profiles: a deleted profile would have silently lifted its limits. Keys now fail closed, and deleting a profile that is in use is refused.
- `connection_string` was required, so stdio MCP configs failed to load.

## Wave 8: Bifrost parity P0 (from docs/parity.md)

The parity audit (docs/parity.md, against Bifrost main 6c84d7a) found 107 done, 124 partial
and 249 missing out of 497 features. P0 are the gaps a Bifrost user hits on switching.

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L43 | G4 | Bifrost price datasheet (4,487 models) embedded and synced; pricing_overrides | worker | done: unit + e2e |
| L44 | G3 | Read Bifrost's `guardrails_config` | worker | done: unit + e2e |
| L45 | G7, G48, G49 | Bifrost section names (`alerting`, `audit_logs`, `cluster_config`, ...) and unknown-key warnings | worker | done: unit + e2e (e2e config in Bifrost's dialect) |
| X15 | G1 | Async: `/v1/async/<op>/{id}`, Bifrost status names, missing ops | lead | done: e2e |
| X16 | G2 | `client.enforce_auth_on_inference` and `auth_config.is_enabled` (default on when credentials exist, as Bifrost) | lead | done: unit + e2e |
| X17 | G5, G9, G14, G17 | `/openai/v1/*`, `/pydanticai`, `GET /v1/models/{id}`, x-bifrost-* headers + CORS expose | lead | done: e2e |
| X18 | G6 | Bedrock SDK `converse-stream` and `invoke-with-response-stream` | lead | moved to wave 9 (L48) |
| X19 | G32 | SCOPE.md rows corrected to partial | lead | done |

## Wave 9: Bifrost parity P1

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L46 | G8 | Cohere SDK routes (chat, embed, rerank, tokenize; streaming) | worker; wired by L61 | done: unit + e2e |
| L47 | G11 | GenAI SDK cross-provider, models routes, countTokens, streaming | worker; wired by L61 | done: unit + e2e |
| L48 | G6, G12 | Bedrock SDK cross-provider, converse-stream, invoke-with-response-stream, count-tokens | worker; wired by L61 | done: unit + e2e (event-stream CRCs checked); http1 answers Bedrock streams whole |
| L49 | G19 | Reasoning parameters → Anthropic, Gemini, Bedrock; reasoning text back | worker → lead | done: unit + e2e |
| L50 | G23 | RE2 regex for `matches`, Bifrost CEL variables (percent units, "" when absent) | worker → lead | done: unit |
| L51 | G24, G25, G27 | Azure Entra ID, Bedrock assume-role, Bedrock Mantle | worker → lead | done: unit (fixed Microsoft/AWS hosts, no e2e) |
| L52 | G29 | OTLP metrics push | worker → lead | done: unit |
| L53 | G31 | Teams and PagerDuty channels, rate-limit metrics, channel cooldowns | worker → lead | done: unit; Bifrost channel mapping |
| L54 | G10 | Anthropic SDK models, message batches, files | worker; wired by L62 | done: unit + e2e |
| L55 | G16 | Native batches and files for Anthropic and Gemini; Gemini speech/images | worker; wired by L62 | done: unit + e2e (uploads kept in memory, 256 files) |
| L56 | G18 | Bifrost metric names and enrichment labels | worker → lead | done: unit + e2e |
| L57 | G21 | Governance model configs, provider governance, management routes | worker → lead | done: unit + e2e |
| L58 | G22 | MCP client and virtual MCP management API | worker → lead | done: unit + e2e; also fixed GET /api/config leaking MCP, OIDC, cluster and store secrets |
| L59 | G30 | Bifrost semanticcache plugin config; Qdrant and Redis vector stores | worker → lead | done: unit + e2e (Qdrant REST mock); RediSearch untested against a real server |
| L60 | G31 | Bifrost alert rules (CEL over scope usage) and `/api/alerting/*` | worker → lead | done: unit + e2e |
| L61 | G6, G8, G11, G12 | Wire L46–L48 into the routes, one route kind for streaming | worker | done: e2e on both servers |
| L62 | G10, G16 | Wire L54 and L55 | worker | done: e2e (21 checks) |
| L63 | G29 | Bifrost otel plugin options (trace headers, TLS, request headers, excluded attributes) | worker | done: unit + e2e; no gRPC |
| L64 | G34, G39, G49 | Direct keys, raw request/response echo, drop_excess_requests, prometheus_labels | worker | done: unit + e2e; drop_excess_requests is a logged no-op (no queue) |
| L65 | G38 | Remaining chat providers (databricks, cloudflare, github-copilot, replicate, sarvam, wafer, opencode) | worker → lead (token minting) | done: unit; no live accounts |
| L66 | G50 | Bare-model provider resolution through the catalog; chained aliases | worker → lead (route hint, 400) | done: unit + e2e |
| L67 | G35, G47 | Passthrough routes; /api/version, /api/models, /api/keys, PUT /api/config | worker | done: unit + e2e; passthrough applies the VK gate only |
| X20 | G13, G15 | Responses lifecycle; realtime client_secrets, sessions, calls | lead | done: e2e |
| X21 | G20, G28 | Content-logging control; rerank semantics (vLLM native, error otherwise, raiju/lexical) | lead | done: e2e |
| X22 | G26 | TLS options (insecure_skip_verify, ca_cert_pem) | lead | done: e2e against a private-CA HTTPS upstream |

Earlier summary of the wave:

G8–G31, G33 in docs/parity.md: Cohere and PydanticAI SDK routes, Anthropic models/batches/files,
GenAI and Bedrock cross-provider, responses lifecycle, WebRTC realtime, media for non-OpenAI
providers, the x-bifrost-* response headers, metric names and labels, reasoning parameters,
content-logging control, governance model configs and provider budgets, MCP management API,
CEL variables, Azure Entra ID, Bedrock IAM roles, TLS options, Bedrock Mantle, rerank semantics,
OTel metrics, semantic cache plugin config and vector stores, alert channels, count-token labelling.

| L68 | — | Re-audit docs/parity.md against the code | worker → lead | done: 197 done, 131 partial, 152 missing of 498; three wrong claims found and fixed |

Process note: e2e uses fixed ports, so every run (workers and lead) goes through
`flock /tmp/raiju-e2e.lock`; a worker's stray mock once broke another run.

## Wave 10: the mechanical remainder (from the re-audit)

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L69 | G5 | /openai/deployments/{d}/* variants | worker | done: unit + e2e (both servers) |
| L70 | G7 | Bifrost plugins: logging, telemetry, governance, compat, routing, prompts | worker | done: unit + e2e |
| L71 | G16 | Vertex, Bedrock, Cohere media/files/batches; Gemini STT; batch results route | worker | done except Vertex/Bedrock batches and files (GCS/S3) |
| L72 | G11 | GenAI files, batches, cachedContents, operations, :predict, /genai/v1/rank | worker | done: unit + e2e |
| L73 | G12, G25, G27 | /bedrock/rerank and Bedrock rerank, real count-tokens, inference-profile arn, use_openai_endpoints, Mantle Anthropic models | worker | done: unit + e2e; batch S3 open |
| L74 | G47, G18 | Remaining management routes; remaining metric families | worker → lead (login audit) | done; enterprise-only routes skipped |

## Wave 11: everything mechanical that's left

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L75 | G16, G25 | Vertex batches and files (GCS), Bedrock batches and files (S3) | worker | done: unit + e2e (mock GCS, S3, Vertex and Bedrock jobs) |
| L76 | G17, G22 | Remaining x-bifrost-* headers; MCP verification and OAuth routes, tool_sync_interval, allow_by_default | worker | done: headers, tool sync, allow_by_default, auto-execute; MCP OAuth code flows moved to L91 |
| L77 | G30 | Weaviate, Pinecone, chromem; cache_tool_call_responses, disable_identity_scoping | worker | done: unit + e2e (Python mocks; not run against live Weaviate or Pinecone) |
| L78 | G29 | OTLP over gRPC (protobuf, HTTP/2, gRPC on Tov sockets) | worker | done: plaintext h2c; TLS gRPC needs the ALPN Tov patch (L92) |
| L79 | G47, G18 | Proxy config, breaker reset and policies, vault flush, log analytics, MCP logs, model parameters and catalog; overhead and routing metric families | worker | done; policy rerouting moved to L91 |
| L80 | G48, G39 | Every remaining config key (encryption_key, server.*, concurrency and queues, provider options, ...); raw payload storage | worker | done: unit + e2e; AES-256-GCM config encryption |

## Wave 12: the P2 features (owner: "address ALL gaps")

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L81 | G36, G38 | Decisions API, typesafe provider, decision-model complexity classifier | worker | done: unit (1,084) + e2e http1; Bun e2e re-run by lead after merge; unprefixed /decisions routes, decision pricing overrides, x-bf-passthrough-extra-params gate open |
| L82 | G37 | Compat plugin (param dropping and conversion, text-to-chat, chat-to-responses, reasoning-only models) | worker | done: unit (1,075) + e2e (both servers); limits moved to L100 |
| L83 | G40 | WebSocket responses, live sessions, the UI socket | worker | done: /v1/responses WebSocket mode (bridge), /v1/live/sessions with attach and content, /ws UI socket (log feed scoped by data access, lead fix); unit + e2e; limits moved to L102 |
| L84 | G41 | Projects, business units, custom roles and data access scopes | worker | done: governance.projects and business_units, x-bf-project-id and x-bf-customer-id, custom roles (management API), data access scopes on logs and analytics; unit + e2e (both servers). Open: project members API and split policies, entity_dac overrides, Bifrost role-id API shape |
| L85 | G42 | BigQuery, Kafka, Pub/Sub sinks; Parquet payloads; export retention | worker | done (wired by L89) |
| L86 | G43 | Guardrails: regex, secrets rule set, reversible redaction, LLM judge, MCP tool-call guard, Presidio, Azure PII, Model Armor, CrowdStrike | worker | done (wired by L90) |
| L87 | G44, G45 | Cluster discovery (Kubernetes, DNS, Consul, etcd, mDNS, UDP), leader election; auth proxies | worker | done except UDP/mDNS (Tov has no UDP: L92) and broker mode |
| L88 | G46 | Prompt repository and deployments, webhooks, feature flags, notifications | worker | done: prompt repository and deployments, webhooks (Standard Webhooks signing, retries), feature flags, notifications; unit; e2e Bun (lead re-runs both after merge). Not built (to SCOPE.md Out): skills marketplace, Warp, A2A agent gateway, Sidekiq; deliveries are in memory |

| L89 | G42 | Wire the sinks into ops (BigQuery, Pub/Sub, Kafka, Maxim, Parquet, retention) with gateway-level e2e | worker | done: unit + e2e (both servers) |
| L90 | G43 | Wire the guardrails into the gateway (local engines, LLM judge, MCP tool guard, reversible) with e2e | worker | done: unit + e2e (both servers); Gitleaks set is a 35-rule subset |
| L91 | G47, G22 | Circuit-breaker policy rerouting (persisted); MCP OAuth authorization-code flows | worker | done: circuit_breaker_policies (config, API, persisted), breaker reset, MCP OAuth authorization-code flow (PKCE, dynamic registration); unit + e2e (both servers). Open: per-key sub-circuits; per_user_* MCP auth types |
| L92 | G29, G44 | Tov patches 0003 (TLS ALPN) and 0004 (UDP); TLS gRPC export; UDP and mDNS discovery | worker | done: Tov patches 0003 (ALPN) and 0004 (UDP) with upstream versions; TLS gRPC export; udp and mdns discovery (Raiju wire format: Bifrost's is not public); unit + e2e (both servers) |

## Wave 13: what remains after wave 12

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L93 | G43 | Full Gitleaks rule set (from upstream gitleaks.toml, not memory) | worker | done: gitleaks v8.30.1, 220 rules (pkcs12-file is path-only; generic-api-key held back until L101), keyword prefilter (20 KB check 41 ms → 3 ms); unit + e2e |
| L94 | G44 | Broker-mode clustering (relay process) and lock-based leader election | worker | done: broker mode (HTTP relay process, `-mode broker`; Bifrost's is gRPC) and etcd lease leader lock (Raiju design; Bifrost elects by rank); unit + e2e |
| L95 | G4, cache | Owner switches, defaults unchanged: refuse unpriced models; exact-match cache scoped per virtual key | worker | done: client.refuse_unpriced_models (budgeted requests to an unpriced model are refused, 403) and cache.scope_by_virtual_key, both off by default; unit + e2e |
| L96 | G32, G33, all | Re-audit docs/parity.md (rows counted by script) and bring SCOPE.md and README in sync | worker | done: sections re-audited (L96a, L96b, L96c); summary and docs in L96d |
| L100 | G37 | Compat remainder: stream conversions (text-to-chat, chat-to-responses), decision emulation (needs L81), azure_deepseek, reasoning budget scaling and min_output_tokens, summary fitting for Responses | worker | done: streamed text-to-chat and chat-to-responses, decision emulation, Azure DeepSeek reasoning drop, output and reasoning budget fitting, Responses-side drops; unit + e2e. Open: compat headers on streamed answers, native-decision model checks |
| L101 | G43 | Secrets engine: capture groups for secretGroup, the entropy filter and gitleaks allowlists and stopwords; then enable generic-api-key | worker | done: regex captures (linear), secretGroup spans, entropy (above N, as gitleaks), global and per-rule allowlists and stopwords, trailing boundaries restored, generic-api-key on; unit + e2e. Open: gitleaks:allow comments not honoured (fail closed), keyword-dense 20 KB check ~35 ms |
| L102 | G40 | WebSocket and live remainder: Responses socket streams events as they arrive (not after completion), response.cancel, /openai/responses aliases; live sessions for more providers, POST /v1/live/sessions (WebRTC create), session registry and /ws shared across workers, /ws heartbeat | worker | done: Responses socket streams OpenAI events as they arrive, response.cancel (Raiju extension: Bifrost rejects it), /openai aliases, POST /v1/live/sessions validated then 501 (no WebRTC peer), live registry and /ws shared across workers, /ws heartbeat; unit + e2e |
| L97 | from L96 | Whatever the re-audit still lists as missing or partial and buildable | workers | done: split into L97a to L97t below; remainders queued as wave 14 |
| L97a | (a) | Route families: /openai unversioned, /anthropic/v1/complete, /v1/completions bridge, POST /v1/realtime SDP, genai batch and Vertex regional paths, Bedrock job and file routes, /cursor, GET /mcp SSE | worker | done: unversioned /openai family, /anthropic/v1/complete, POST /v1/realtime SDP, Vertex regional batch and cachedContents paths, Bedrock job and file routes, /cursor, GET /mcp SSE; /v1/completions keeps Bifrost's default (bridge only with compat); unit + e2e. Open: legacy complete streaming, cursor Responses streaming |
| L97b | (a) | Management API: providers create and keys, config metadata, VK rotate and quota, team members, routing-rule and complexity APIs, users and /me, projects members, access-profile versions, permissions listings | worker | partial: provider create and key reads, config metadata, VK rotate with cooldown, VK expires_at, team members (parts 1-3 in part); parts 4-9 moved to L97j |
| L97c | (a) | Management API: logs filters, by id, sessions, user/app/user-agent fields and histograms, delete and recalculate-cost; cache stats and clear; audit by id; session setup and ws-ticket; plugin listings | worker | done: logs in Bifrost shapes with its filters, log by id, sessions and summary, user and user-agent fields, user-agent mappings, delete and recalculate-cost, cache stats and clears, audit by id and filterdata, ws-ticket, plugin listings; unit + e2e. Open (L97l): background cost recalculation, setup flow, plugin CRUD, unrecorded log filters |
| L97d | (a) | MCP auth: per_user_oauth and per_user_headers types and flows, MCP sessions, tool groups, OAuth config status, OpenAPI preview, oauth2 sessions and consent | worker | partial: MCP client keys (per-client timeout, stickiness, require_public_target, allowed_extra_headers, tool_pricing, global sync interval), VK and access-profile mcp_configs enforced, tool groups API, OAuth config status and revoke, OpenAPI-defined MCP clients and preview; per-user auth types and temp tokens moved to L97k |
| L97e | (a) | Media for the remaining providers (speech, transcription, image generation, edits, variations); GET /v1/models/{model} metadata | worker | done: image edits (Gemini, Vertex, Bedrock) and variations (Bedrock), GET /v1/models/{model} from the provider (OpenAI-format, Anthropic, Gemini); unit + e2e. Open: Bedrock Stability edits, retrieve for Bedrock/Vertex/Cohere/Azure; found multipart byte corruption (fixed by lead) |
| L97f | (b) | Headers: x-bf-dim-* on logs, parent and correlation ids, x-bf-lh-*, app from User-Agent, x-bf-maxim-*, x-bf-mcp-include-tools, x-bf-mcp-session-id, passthrough-extra-params gate, SDK-route async headers, forwarded-proto; response headers (request id echo, cache hit details, pricing request type, passthrough path, compat on streams, extra_fields placement) | worker | done: log metadata (x-bf-dim-*, x-bf-lh-*, logging_headers), parent and correlation ids, app from User-Agent, Maxim attributes, x-bf-mcp-include-tools, passthrough-extra-params (chat), SDK-route async create and poll, job TTL, request id echo, cache origin headers, passthrough path, compat headers on streams, extra_fields in headers; unit + e2e. Open: x-bf-mcp-session-id (L97d), alias model name/family |
| L97g | (c) | Config keys: body limit on bun, drop_excess_requests, governance header, retention without logs_store, use_for_batch_api, vertex SA options, provider prompt_cache, VK mcp_configs, global tool sync interval, vector_store timeouts, audit retention and omit_ip, load balancer and pricing URLs, setup_token, access_profiles alias, large payloads, credential conflict, header filters, VK lifecycle, routing chain depth, network_config extras, ignore_provider_cost | worker | done: body limit on Bun, drop_excess_requests default queue, header_filter_config, whitelisted_routes, setup_token gate, use_for_batch_api (Bifrost: batch/file routes use flagged keys only), provider prompt_cache ttl and injection points, routing_chain_max_depth, dump_errors, webhook retention, log_retention_days; unit + e2e. Not applicable here: large_payload_optimization (no streamed request bodies), fetch knobs Tov lacks, Vertex AWS federation |
| L97h | (d) | Providers: Bedrock and Vertex model lists, Vertex exact count tokens, OpenRouter native decisions, Databricks and Cloudflare listing, Cloudflare rerank, Sarvam, Wafer and Replicate operations, prompt-cache injection points, scoped aliases | worker | partial: model lists for Bedrock, Vertex, Cloudflare (Databricks empty, as Bifrost), Vertex exact count tokens, OpenRouter native decisions; unit + e2e. Not in Bifrost: Cloudflare rerank, Sarvam text/embeddings, Bedrock/Vertex retrieve. Rest in L97n |
| L97i | (e), (h), (i) | Plugins and observability: telemetry routing families and push gateway, OTel span filters and overhead options, mocker conditions, jsonparser and routing chain_rule, plugin sequencing, export redaction, streaming output guardrails, persisted webhook deliveries | worker | partial: routing classifier metric families, Prometheus push gateway, mocker parity (conditions, weights, probability, priority, latency, default behaviour), raw payload redaction in logs and exports, webhook deliveries persisted; unit + e2e. Rest moved to L97m |
| L97j | (a), (f) | Governance remainder: PUT /api/config beyond client, VK quota, budget overrides, VK users, expired-key cleanup, routing-rule and complexity APIs, users and /me routes, project members and split policies, entity_dac, access-profile versions, permission listings, audit retention and archive, adaptive LB API, per-key sub-circuits | worker | partial: PUT /api/config framework and auth sections, VK quota (self-service), budget overrides (forever), VK users, expired-key sweep, routing-rule and complexity APIs, roles permission_ids, RBAC catalogue, /users/me/permissions, user role; unit + e2e. Rest in L97p |
| L97k | (g) | MCP per-user auth: per_user_headers and per_user_oauth types and flows, MCP sessions list/reauth/revoke, temporary MCP tokens, per-user consent | worker | partial: per_user_headers auth (per-key values sealed at rest, header flows, credential revoke, verify-headers, tool calls need the caller's values); unit + e2e. per_user_oauth, sessions, temp tokens in L97o |
| L97l | (a) | Logs remainder: background cost recalculation with progress and cancel, /api/session/setup with setup_token, plugin CRUD, the log filters Raiju does not record yet (routing rule, selected key, stop reason, alias, roots/group sessions, complexity) | worker | done: background cost recalculation (status, cancel), /api/session/setup with a setup session, plugin CRUD on the live chain, recorded log fields and filters (selected key, routing rule and engine, alias, complexity, cache hit type, stop reason, roots/group sessions), cache hit-rate stats; fixed lost selected-key metric labels; unit + e2e |
| L97m | (e), (h), (i) | Observability remainder: OTel span filters, export_overhead_spans, trace_type, overhead attributes, group_traces_by_session, disable_root_span_content; jsonparser options; routing chain_rule; plugin sequencing; guardrails on streamed output; custom labels on http_* metrics | worker | done: OTel plugin span filter, overhead spans and breakdown, session-grouped traces, OTLP MCP histogram; telemetry overhead and user labels, custom labels on http_*; guardrails on streamed chat output; jsonparser stream completion; routing chain_rule; plugin placement and order; unit + e2e. Open: guards on text and Responses streams, stream redaction and replay |
| L97n | (d) | Providers remainder: Replicate (text, images, edits, files, models), scoped and object-form aliases, Bedrock Stability edits and variations, Wafer text and models, OpenRouter billed cost and decision-model listing, Bedrock listing pagination | worker | partial: OpenRouter billed cost and decision-model listing, Bedrock listing pagination and GET signing fix; Wafer text and models already OpenAI-compatible. Rest in L97q |
| L97o | (g) | MCP per-user OAuth: consent, token rows by key or x-bf-mcp-session-id, /api/oauth/per-user/flows, /api/mcp/sessions list/reauth/revoke, temporary MCP tokens | worker | partial: per_user_oauth flows, sealed token rows by key or x-bf-mcp-session-id, consent with temporary MCP tokens, /api/mcp/sessions list/reauth/revoke; unit + e2e. HTML consent page and MCP-as-OAuth-server open |
| L97p | (f), (i) | Governance last part: project members and split policies, entity_dac, access-profile versions/clone/deactivate/propagate, audit retention/omit-IP/archive, adaptive LB API, per-key sub-circuits, budget override cycles, vk-creation-policy, VK access-profile links | worker | partial: project members and split policies (none/equal, member budget caps), entity_dac object form per resource, access-profile versions/clone/activate/deactivate/propagate, user-held profiles and VK links, vk-creation-policy, budget override cycles, audit retention/omit-IP/archive to object storage, adaptive LB held keys/incidents/clear, per-key sub-circuits; unit + e2e. Open: rate-limit split, profile role binding, archive manifest/gzip, adaptive refusal classification and wait ladder |
| L97q | (d) | Providers last part: Replicate predictions (text, images, edits, files, models), scoped and object-form aliases with the alias-model-name/family headers, Bedrock Stability edits and variations, Wafer file upload, OpenRouter chat usage.cost | worker | partial: Replicate image generation, files and models listing; object-form aliases with model_name pricing and the alias-model-name/family headers; Bedrock Stability edits; Wafer file upload; usage.cost billed on OpenAI-format chat (OpenRouter); ignore_provider_cost honoured; unit + e2e. Open: Replicate text, edits, polling; Stability variations (Bifrost's body is rejected by Bedrock); usage.cost on streams |
| L97r | (g) | MCP OAuth remainder: HTML consent page for per-user OAuth and temporary tokens, Raiju as an OAuth authorization server for MCP clients (metadata, register, authorize, token) | worker | partial: per-user connect page and consent page (self-contained HTML), Raiju as OAuth authorization server for /mcp (discovery, JWKS, dynamic registration, authorize with PKCE S256, token with refresh rotation, RS256 JWTs mapped to a virtual key, 401 with resource_metadata), client.mcp_server_auth_mode and oauth2_server_config; unit + e2e. Open: session and user consent modes, grants list/revoke, persisted grants, generated signing key |
| L97s | (e), (i) | Streamed guardrails remainder: output guards on text completion and Responses streams, stream redaction and replay | worker | partial: local regex and secrets output guards on streamed text completions and Responses (converted and passthrough), redaction with holdback, guarded raw_response and cached replays; unit + e2e. Open: built-in guard on streams, replay pacing, matches spanning a release point |
| L97t | (a) | Log filters Raiju still refuses: agent_names, tool_call_names, complexity score bounds, prompt filters (record what they need) | worker | done: tool_call_names, min/max_complexity_score, selected_prompt_ids and prompt_names recorded and filtered on every log route; unit + e2e. agent_names stays refused (no registered agents); tool names not recorded for streamed answers |
| L96d | G32, G33 | Final docs: scripts/parity_count.py and Summary, Gaps and Remaining gaps, SCOPE.md and README.md in sync (after L97) | worker | done: scripts/parity_count.py (--write, --check; make parity-count), Summary regenerated (560 parity rows: done 368, partial 144, missing 11, out-of-scope 28, n/a 9; 34 Raiju-only), gap statuses and remaining gaps rewritten, SCOPE.md and README.md in sync, Out table extended; G32 and G33 closed |

## Wave 14 (queued, not started)

Consolidated from the "Open:" notes above and docs/parity.md "Remaining gaps". Older "Open:"
notes on L84, L91, L97f and L97m were finished by later rows (L97p, L97k/L97o, L97q, L97s).

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L103 | G41 | Governance remainder: rate-limit shares split across project members, access-profile role binding, user-held profiles governing requests, Bifrost role-id API shape, budget-override cycle count kept across restarts | worker | done: rate-limit shares per project member (split none) and equal splits; Bifrost role-id routes (/api/governance/rbac/roles/{role_id}); access profiles attached to custom roles; held profiles govern the holder's keys (charged per user); budget-override cycles kept across restarts (override.started_at). Fixed: a role change dropped teams, projects and profiles. Unit + e2e (g41_e2e). Behaviour change: profiles a user holds now govern all that user's keys, and every held profile is charged (Bifrost charges one). Open: no background redivision of member slices; is_default and apply_to_existing are stored only; built-in roles have no ids |
| L104 | G41, G42 | Audit and adaptive LB remainder: archive manifest, gzip and archive_max_object_bytes splitting; adaptive refusal classification, wait ladder and incident history | worker | partial: audit archive writes per-window parts (archive_max_object_bytes, never splitting a line), manifest.json and optional gzip (archive_compress; src/gzip.tov, fixed Huffman), default prefix now Bifrost's "bifrost/audit-logs/..."; adaptive refusal classes (src/refusal.tov), hold ladder (src/holds.tov), incident history at GET /api/adaptive-routing/history/issues; refusals hold keys even with breakers and adaptive off (429: 10 s to 2 min). Unit + e2e (l104_e2e). Open: no archive e2e (5-minute pass floor) or real bucket; windows not aligned to the interval; old-prefix objects not migrated; incidents in memory, not cluster-shared; no provider-level hold; classifier phrase lists in part |
| L105 | G14, G17, (d) | Providers remainder: Replicate text, image edits, polling past Prefer: wait, file list/retrieve/delete/content; usage.cost on streamed answers; model retrieve for Cohere and Azure; server-side-fallback-model on streamed Anthropic answers; Stability extra params | worker | partial: provider-reported usage.cost billed on streamed chat (owner decision); Cohere model retrieve; Replicate text (as a chat prediction), image edits, polling for images, file list/retrieve/delete; Stability generation extras. Unit + e2e (l105_e2e). Open: streamed /v1/completions ignores usage.cost; Azure retrieve not built (Bifrost refuses it too); server-side-fallback-model on streamed Anthropic answers needs a chunk extra_fields shape first (G17); Replicate chat still errors past Prefer: wait; Vertex retrieve missing |
| L106 | (g) | MCP OAuth remainder: session and user consent modes, /api/oauth2/sessions list and revoke, grants persisted across restarts, generated and stored signing key, Bifrost's redirect scheme list | worker | done: generated 2048-bit RSA signing key (jwt.tov generateRsaPem) saved once in mcp-oauth-state.json beside config.json when no signing_key is set (a configured key wins; sealed with the config cipher when one is set); grants persisted there with GET/DELETE /api/oauth2/sessions; session consent mode; Bifrost redirect scheme check (https, loopback http, cursor://). Unit + e2e (mcp_grants_e2e). Open: auth codes and pending consents stay in memory; user consent mode needs an identity provider; VK rotate does not revoke MCP grants; two workers writing the state file at once can race; state file uses the default umask |
| L107 | G43, G37 | Streams remainder: built-in guard (guardrails.detect) on streams, replay pacing (stream_replay_event_interval_ms), redaction across a release point, tool names recorded on streamed answers, compat headers on streamed answers, legacy completions and cursor Responses streaming (L97a) | worker | partial: the built-in guard (guardrails.detect) on streams (block and redact), release points never split a match (PEM blocks held BEGIN to END), cached-stream replay paced by guardrails.stream_replay_event_interval_ms, tool names logged for streamed answers, legacy Anthropic completion and cursor Responses streaming; compat headers on streamed answers checked (already sent). Unit + e2e (l107_e2e). Open: Bifrost holds and replays live block-capable streams, Raiju still cuts them mid-stream; block rules rescan the whole answer per event |
| L108 | G40 | Live sessions for providers other than OpenAI; POST /v1/live/sessions (WebRTC create, now 501) | worker | partial: xAI realtime relayed; Azure realtime takes Entra tokens and extra headers; POST /v1/live/sessions creates the WebRTC session at OpenAI and records it (was 501). Unit + e2e. Open: the WebRTC create is a pass-through: Raiju has no WebRTC peer, so media and events after the create are not metered, guarded or logged (Bifrost terminates WebRTC); live sessions stay OpenAI only, as in Bifrost |
| L109 | G36, G37 | Unprefixed /decisions routes, decision pricing overrides, native-decision model checks | worker | partial: /openai, /litellm, /langchain, /pydanticai decision routes; decision pricing overrides (request_types, input/output_cost_per_token_decisions); native-decision check (TypeSafe, OpenRouter) with compat emulation; cost recalculation bills decisions. Unit + e2e (l109_e2e). Open: OpenAI native decision models still refused unless emulated; the datasheet's own decision rates are not read; a bare /decisions stays unrouted, as in Bifrost |
| L110 | G39, G47, G22 | x-bf-store-raw-request-response; the a3 histograms and rankings still partial; the inprocess MCP connection type. (The websocket, large_payload_optimization, access_profiles, network_config, oauth_key_config and token_exchange items moved to L112, the missing-rows task) | worker | partial: raw request and response kept for streamed answers too (store_raw_request_response, 1 MiB cap, dropped with content logging off); per-request input, output and additional cost, overhead_ms and canonical_model_name on log entries; overhead percentiles in the latency histogram; model rankings by provider and model with throughput and the cost split, Bifrost trend rules; by-dimension histograms take Bifrost's names and error texts. Unit + e2e (l110_e2e). Open: inprocess MCP is not expressible (Bifrost needs a Go server object); overhead not measured for streams sent straight to the client; cost recalculation reprices the total only |
| L111 | G43 | Honour `gitleaks:allow` comments; bring the keyword-dense 20 KB secrets check under 35 ms | worker | partial: Gitleaks rules skip a match whose line holds gitleaks:allow (guard_regex.tov skip_line_containing), unit + e2e; bench/guard_secrets.tov. Keyword-dense code: 23 to 35 ms per 20 KB (target met, just). Open: text holding every rule keyword takes about 0.9 s per 20 KB; the cost is the regex VM in the window gate (L118) |
| L119 | HA, UI | Cluster-wide live feed: nodes relay log events to peers or the broker; any node's /ws streams the merged feed tagged with node id; resume from the last event id after a reconnect to another replica (short ring buffer); server-side batching (about 100 ms) and backpressure. No sticky sessions needed behind a load balancer | worker | done: feed events carry node, seq and id; nodes relay their events to peers (mesh, HMAC-signed POST /api/cluster/feed) or through the broker; /ws?since= replays from a ring buffer (10,000 events / 5 min) on any replica, with gap and resumed notices; /ws?batch=1 sends arrays every 100 ms and closes a slow batch client with 1013; cluster.feed config; raiju_feed_* metrics (src/feed.tov). Unit + e2e (feed_cluster_e2e, two mesh nodes). Open: no forwarding (a node not peered with the producer needs broker mode); broker mode and multi-worker share files are unit-tested only; store updates are not replayed |
| L120 | SCIM, auth | SCIM follow-up from L115: OIDC sign-in refuses users that governance marks disabled (a SCIM-deactivated user can still sign in through OIDC today) without changing sign-in for users not in governance; client.enforce_scim_auth as Bifrost defines it | worker | done: OIDC sign-in answers 403 ("This account is disabled", audited, no session) for a user governance marks disabled, by subject or lower-cased email; open SSO sessions of such a user stop at their next request (ops.tov liveSession); users not in governance sign in as before; client.enforce_scim_auth accepted and ignored with a note, as Bifrost overwrites it from enforce_auth_on_inference. Unit + e2e (l120_e2e). Open: the identity-aware proxy in full mode does not consult governance |
| L118 | G43 | Regex engine speed for the secrets check: integer opcodes, no Inst copies per step, first-byte or required-literal skip, so text holding every Gitleaks keyword checks 20 KB in under 35 ms (L111 measured 0.9 s) | worker | done: regex engine on integer opcodes over parallel arrays with a first-character skip and no per-step record copies; required-literal extraction (Regex.literals) so each rule tries only the windows and starts its literal can reach; each window decoded once. Bench 20 KB: every-keyword text 841 ms to 16 ms, keyword-dense code 22.5 ms to 5.6 ms; findings identical to the old engine on 180 random texts and 2,400 window-seam cases. Open: a text dense in five common keywords takes about 40 ms; sourcegraph-access-token has no required literal |
| L112a | — | Missing rows, config keys (owner: build all): websocket config, large_payload_optimization, top-level access_profiles, dual_credential_conflict_behavior, logging_headers, retain_content_in_object_storage, keys[].oauth_key_config, network_config knobs (enforce_http2, http2_ping_interval, keep_alive_timeout, max_conns_per_host, stream_idle_timeout, beta_header_overrides) | worker | partial: websocket.max_connections_per_user (per-route cap, 1013 close), top-level access_profiles mapped onto governance, dual_credential_conflict_behavior "error", network_config.stream_idle_timeout_in_seconds, keys[].oauth_key_config (client_credentials and jwt_bearer, src/oauth_key.tov), logging_headers (already built). Unit + e2e (l112a_e2e). Accepted and noted, not applied: large_payload_optimization (routing reads the model from the body, so bodies stay buffered), retain_content_in_object_storage, websocket.pool and transcript_buffer_size, enforce_http2, http2_ping_interval, keep_alive_timeout, max_conns_per_host (Tov fetch is HTTP/1.1 with no pool knobs), beta_header_overrides. Parity missing rows 11 to 5 |
| L112b | — | Missing rows, the rest (owner: build all): /api/api-keys CRUD, dynamic plugins (Go shared objects, WASM), MCP token_exchange auth | worker | partial: /api/api-keys CRUD (value shown once, SHA-256 stored, governance.api_keys; a key authenticates the management API with its own permissions; grants capped at the caller's) and the APIKeys permission; MCP token_exchange auth (RFC 8693; src/tokenexchange.tov) with caching and POST .../verify-exchange. Unit + e2e (l112b_e2e, l112b_exchange_e2e). Open: token_exchange clients are not connected at runtime (no tool list without a prior connect); dynamic plugins not built: Go .so plugins need the Go runtime, and WASM is reachable only by linking JavaScriptCore into the gateway (about 34 MB), an owner decision |
| L113 | UI | Admin client = the web UI built into the gateway (owner, 2026-10-17). Framework: SolidJS 2.0 RC (owner; no React), TypeScript, Vite on Bun, types generated from docs/openapi/management.yaml, virtualized lists. Vite output (hashed assets) embedded in the binary through src/ui_assets.tov (committed; the gateway builds without Node), RAIJU_UI_DIR overrides it. Screens: overview, live feed, providers, keys and governance, logs, MCP, config. The first plain-JS attempt is superseded: its tests and notes feed this row, its ui/index.html is not merged | worker | done: the admin UI is a SolidJS 2.0 RC app in web/ (TypeScript, Vite on Bun, types generated from docs/openapi/management.yaml), embedded as hashed assets with precomputed gzip in src/ui_assets.tov and served by src/uiserve.tov (ETag/304, immutable assets, CSP; RAIJU_UI_DIR override); make web and make web-check. Screens: sign-in, overview, providers, virtual keys, budgets, rate limits, teams, customers, logs, MCP, config, playground; the Live screen uses the L119 protocol (batch=1, since= resume, gap notice, node column) through a fixed-row-height virtualizer. ui/index.html removed. make ui about 160 browser checks. Open: dashboard charts, MCP OAuth consent screens, virtual MCP and tool group editors, role-aware hiding of actions; vite-plugin-solid is renamed upstream to @solidjs/vite-plugin |
| L114 | — | Scope the exact-match response cache per virtual key (owner, 2026-10-17), as the semantic cache already is | lead | done: cache.scope_by_virtual_key (L95) now on unless false; the e2e owner gateway leaves it unset to cover the default. make unit 1,381 passed; e2e all passed on Bun and http1; openapi-check ok (310 operations) |
| L115 | Scope | SCIM user provisioning (moved in from Out, 2026-10-17) | worker | partial: SCIM 2.0 at /scim/v2 (src/scim.tov): Users (filter, paging, get, create, PUT, PATCH incl. active false, delete) and Groups mapped to teams, discovery documents, SCIM errors; scim_config.enabled and config.provisioningToken; off by default; deactivated users disabled for the proxy and credentials; last enabled admin protected. Unit + e2e (l115_e2e). Open: OIDC sign-in still admits a SCIM-deactivated user (L120); IdP directory sync and claim mapping, ETags, token rotation and multiple tokens, Bifrost enterprise schema extensions; enforce_scim_auth (L120) |
| L116 | Scope | A2A: agent cards, JSON-RPC tasks, `/agents/a2a`, `/api/agents`; unblocks the `agent_names` log filter (moved in from Out, 2026-10-17) | worker | partial: A2A agents: /api/agents CRUD, inspect, refresh-card and history, cards fetched and cached; the gateway serves each agent's card rewritten to /agents/a2a/{name}/json-rpc and proxies message/send, message/stream (SSE), tasks/get and tasks/cancel (v0.3 and v1 names) with virtual-key auth, grants, budgets and rate limits; calls logged as kind a2a; agent_names log filter works (src/agents.tov). Lead fix: x-bf-async no longer captures /agents/a2a. Unit + e2e (l116_e2e). Open: REST and gRPC bindings, push notifications, tasks/resubscribe, OAuth and TLS upstream auth, forwarded caller credentials, the aggregated card, timed card refresh, history stats routes; agent calls cost 0 |
| L117 | Scope | MCP code mode (moved in from Out, 2026-10-17) | worker | partial: MCP code mode: is_code_mode_client hides a client's tools behind four meta-tools (listToolFiles, readToolFile, getToolDocs, executeToolCode) in chat requests; programs run in a Starlark subset interpreter written in Tov (src/starlark.tov) with step, memory, log, tool-call, value and nesting limits; tool calls from code go through the same gates as direct calls; code_mode_binding_level and code_mode_limits (src/codemode.tov). Unit + e2e (l117_e2e). Open: no while, classes, try, lambda, f-strings; not offered on the Responses API or POST /mcp; a program reruns once per tool call (results cached) |

## UI track

| ID | Work | Owner | Status |
|---|---|---|---|
| L98 | OpenAPI spec for the management API, checked against the routes | worker | done: docs/openapi/management.yaml (203 operations), `make openapi-check` probes a gateway both ways; found /api/mcp/virtual answering any method (fixed) |
| L99 | Native client spike (providers list plus live logs) in gpui and Slint; compare | worker | done: clients/gpui-spike and clients/slint-spike build, share one data layer (GET /api/providers, /ws live log feed) checked headless against a gateway; Slint frame rendered to clients/slint-spike/screenshot.png; clients/README.md compares and recommends Slint (smaller graph, faster build, headless render, mobile targets), licence choice left to the owner. No display here: windows not launched |

Decision taken by the lead: models without a price stay a warning (cost 0), as in Bifrost;
refusing them is a one-line switch if the owner wants it.

## UI track (after parity)

The owner wants a native client for desktop and mobile in time, as fast as gpui. The
web UI stays as the built-in admin page. Plan: freeze the management API as an
OpenAPI spec first, then spike a small client (providers list plus live logs) in gpui
(desktop; mobile via the experimental gpui-mobile) and in Slint, and compare startup
time, memory and feel. Tauri 2 around the web UI is the quick all-platform fallback.

## P2 decisions for the owner

G34–G50 are mostly product decisions (passthrough routes, decisions API, compat plugin, more
providers, raw request echo, live/WebSocket responses, projects and custom RBAC, more log sinks
and guardrail engines, cluster discovery, auth proxies, the remaining management API and config
keys). See docs/parity.md.

## Next

Wave 14 above. The handoff for a new lead is HANDOFF.md plus handoff/leader-prompt.md.

## Wave 15 (owner decisions, 2026-10-17: build the correct way)

Tov runtime patches are numbered in advance so workers do not collide: 0005 WAMR (L121),
0006 libdatachannel (L122), 0007 fetch pool and HTTP/2 (L126). A worker that adds a patch
builds its own compiler inside its worktree (scripts/build-tov.sh there) and never touches
/home/user/raiju/build/tov; the lead rebuilds the shared compiler after merging.

| ID | Gap | Work | Owner | Status |
|---|---|---|---|---|
| L121 | (e) | Dynamic plugins as WASM (Bifrost's JSON ABI: malloc, free, get_name, init, pre_hook, post_hook, cleanup) on WAMR, added to the Tov runtime as tov-patches/0005; no JavaScriptCore | worker | assigned |
| L122 | G40 | WebRTC terminated in Raiju: libdatachannel through tov-patches/0006; Raiju is the peer for POST /v1/live/sessions and relays media and events to the provider, metering, guarding and logging them as Bifrost does | worker | assigned |
| L123 | G42 | Key holds as Bifrost documents them: only under adaptive load balancing, and shared by every node of the cluster | worker | assigned |
| L124 | G48 | large_payload_optimization: stream large request bodies upstream (routing fields from the first bytes), response thresholds and truncated logs as Bifrost defines them | worker | assigned |
| L125 | G48 | retain_content_in_object_storage: request content written to the object store, the log keeps a reference | worker | assigned |
| L126 | G48 | network_config keep_alive_timeout and max_conns_per_host, and upstream HTTP/2 (enforce_http2, http2_ping_interval) in the Tov fetch client (tov-patches/0007) | worker | assigned |
| L127 | G48 | The anthropic-beta header filter Bifrost has, then beta_header_overrides on top of it | worker | todo |

