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
| L43 | G4 | Bifrost price datasheet (5,125 models) embedded and synced; pricing_overrides | worker | assigned |
| L44 | G3 | Read Bifrost's `guardrails_config` | worker | assigned |
| L45 | G7, G48, G49 | Bifrost section names (`alerting`, `audit_logs`, `cluster_config`, ...) and unknown-key warnings | worker | assigned |
| X15 | G1 | Async: `/v1/async/<op>/{id}`, Bifrost status names, missing ops | lead | todo |
| X16 | G2 | `client.enforce_auth_on_inference` and `auth_config.is_enabled` | lead | todo |
| X17 | G5, G14 | Everything under `/openai/v1/*`; `GET /v1/models/{id}` | lead | todo |
| X18 | G6 | Bedrock SDK `converse-stream` and `invoke-with-response-stream` | lead | todo |
| X19 | G32 | SCOPE.md rows corrected to partial | lead | done |

## Wave 9: Bifrost parity P1 (queued)

G8–G31, G33 in docs/parity.md: Cohere and PydanticAI SDK routes, Anthropic models/batches/files,
GenAI and Bedrock cross-provider, responses lifecycle, WebRTC realtime, media for non-OpenAI
providers, the x-bifrost-* response headers, metric names and labels, reasoning parameters,
content-logging control, governance model configs and provider budgets, MCP management API,
CEL variables, Azure Entra ID, Bedrock IAM roles, TLS options, Bedrock Mantle, rerank semantics,
OTel metrics, semantic cache plugin config and vector stores, alert channels, count-token labelling.

## P2 decisions for the owner

G34–G50 are mostly product decisions (passthrough routes, decisions API, compat plugin, more
providers, raw request echo, live/WebSocket responses, projects and custom RBAC, more log sinks
and guardrail engines, cluster discovery, auth proxies, the remaining management API and config
keys). See docs/parity.md.

## Next

Everything in SCOPE.md is done except the five "Out" items. Remaining limits are in the README's Known gaps.
