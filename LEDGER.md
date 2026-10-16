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
| L97 | from L96 | Whatever the re-audit still lists as missing or partial and buildable | workers | todo |
| L97a | (a) | Route families: /openai unversioned, /anthropic/v1/complete, /v1/completions bridge, POST /v1/realtime SDP, genai batch and Vertex regional paths, Bedrock job and file routes, /cursor, GET /mcp SSE | worker | assigned |
| L97b | (a) | Management API: providers create and keys, config metadata, VK rotate and quota, team members, routing-rule and complexity APIs, users and /me, projects members, access-profile versions, permissions listings | worker | assigned |
| L97c | (a) | Management API: logs filters, by id, sessions, user/app/user-agent fields and histograms, delete and recalculate-cost; cache stats and clear; audit by id; session setup and ws-ticket; plugin listings | worker | assigned |
| L97d | (a) | MCP auth: per_user_oauth and per_user_headers types and flows, MCP sessions, tool groups, OAuth config status, OpenAPI preview, oauth2 sessions and consent | worker | assigned |
| L97e | (a) | Media for the remaining providers (speech, transcription, image generation, edits, variations); GET /v1/models/{model} metadata | worker | done: image edits (Gemini, Vertex, Bedrock) and variations (Bedrock), GET /v1/models/{model} from the provider (OpenAI-format, Anthropic, Gemini); unit + e2e. Open: Bedrock Stability edits, retrieve for Bedrock/Vertex/Cohere/Azure; found multipart byte corruption (fixed by lead) |
| L97f | (b) | Headers: x-bf-dim-* on logs, parent and correlation ids, x-bf-lh-*, app from User-Agent, x-bf-maxim-*, x-bf-mcp-include-tools, x-bf-mcp-session-id, passthrough-extra-params gate, SDK-route async headers, forwarded-proto; response headers (request id echo, cache hit details, pricing request type, passthrough path, compat on streams, extra_fields placement) | worker | done: log metadata (x-bf-dim-*, x-bf-lh-*, logging_headers), parent and correlation ids, app from User-Agent, Maxim attributes, x-bf-mcp-include-tools, passthrough-extra-params (chat), SDK-route async create and poll, job TTL, request id echo, cache origin headers, passthrough path, compat headers on streams, extra_fields in headers; unit + e2e. Open: x-bf-mcp-session-id (L97d), alias model name/family |
| L97g | (c) | Config keys: body limit on bun, drop_excess_requests, governance header, retention without logs_store, use_for_batch_api, vertex SA options, provider prompt_cache, VK mcp_configs, global tool sync interval, vector_store timeouts, audit retention and omit_ip, load balancer and pricing URLs, setup_token, access_profiles alias, large payloads, credential conflict, header filters, VK lifecycle, routing chain depth, network_config extras, ignore_provider_cost | worker | assigned |
| L97h | (d) | Providers: Bedrock and Vertex model lists, Vertex exact count tokens, OpenRouter native decisions, Databricks and Cloudflare listing, Cloudflare rerank, Sarvam, Wafer and Replicate operations, prompt-cache injection points, scoped aliases | worker | todo |
| L97i | (e), (h), (i) | Plugins and observability: telemetry routing families and push gateway, OTel span filters and overhead options, mocker conditions, jsonparser and routing chain_rule, plugin sequencing, export redaction, streaming output guardrails, persisted webhook deliveries | worker | todo |
| L96d | G32, G33 | Final docs: scripts/parity_count.py and Summary, Gaps and Remaining gaps, SCOPE.md and README.md in sync (after L97) | worker | todo |

## UI track

| ID | Work | Owner | Status |
|---|---|---|---|
| L98 | OpenAPI spec for the management API, checked against the routes | worker | done: docs/openapi/management.yaml (203 operations), `make openapi-check` probes a gateway both ways; found /api/mcp/virtual answering any method (fixed) |
| L99 | Native client spike (providers list plus live logs) in gpui and Slint; compare | worker | todo (after L98) |

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

Everything in SCOPE.md is done except the five "Out" items. Remaining limits are in the README's Known gaps.
