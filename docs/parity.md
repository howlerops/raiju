# Raiju vs Bifrost: feature parity audit

Re-audited 2026-10-14 against the code at d27a62e; G2 (auth_config flags) and the retries metric were fixed right after.

Date: 2026-10-14. Target: Bifrost `main` at commit `6c84d7a` (shallow clone in `/tmp/claude-0/bifrost-src`). Raiju: read at commit `2923fea` plus the uncommitted working-tree edits present at read time (`src/logstore.tov`, `src/metrics.tov`, `src/ops.tov`, `src/semcache.tov`, `src/server.tov`; `/metrics` calls `ops.metricsText()`). Those edits were committed during the audit as `b506bfc`, and HEAD is now `32c5de8` (Tov patches only). The working tree matches HEAD, so the line numbers below hold for HEAD. This audit changed nothing else in the repo and made no commits.

Bifrost paths are relative to the Bifrost repo root. Raiju paths are relative to `/home/user/raiju`. Line numbers are given where they were read.

## Method

Re-audit (2026-10-14): every partial and missing row was checked against `src/` at d27a62e. Each row's Bifrost route, header or key was grepped in the code, and the commit that claims it was read. Done rows were spot-checked, not all re-read. Counts were computed from the table rows by script. The Summary's route coverage figures are from the original audit and were not recomputed.

- Bifrost routes: every `r.GET/POST/PUT/PATCH/DELETE` registration in `transports/bifrost-http/handlers`, plus the per-SDK route configs in `transports/bifrost-http/integrations/*.go`, mounted by `handlers/integrations.go:33-51`. Cross-checked against `docs/openapi/openapi.json` (511 paths, 669 method-path operations).
- Bifrost config: `transports/config.schema.json` (top-level properties and `$defs`).
- Bifrost headers: string literals in `transports/bifrost-http/lib/ctx.go` (request) and `lib/responseheaders.go` (response), plus the header reference in `docs/`.
- Bifrost providers and per-operation support: `core/schemas/bifrost.go` (provider and request-type constants) and the "Supported Operations" tables in `docs/providers/supported-providers/*.mdx`.
- Bifrost plugins and metrics: `plugins/*/main.go`, `plugins/telemetry/main.go` (metric names), `core/schemas/enrichment.go` (metric label dimensions).
- Raiju: `src/server.tov` dispatch, `src/media.tov`, `src/native.tov`, `src/extras.tov`, `src/jobs.tov`, `src/store.tov`, `src/ops.tov`, `src/governance.tov`, `src/gateway.tov`, `src/config.tov`, plus `README.md`, `SCOPE.md`, `LEDGER.md`. Routes, headers and config keys marked missing were checked by grep against `src/` and `ui/`.
- Route coverage (`/tmp/claude-0/audit/coverage.py`): Raiju's registered method and path shapes were matched against the documented OpenAPI operations. This measures path shape only. It does not check that a matched route behaves the same.

Status values:

- **done**: works as Bifrost documents it, for the cases checked.
- **partial**: exists, but a documented option, provider, operation or field is missing or behaves differently. The notes say which.
- **missing**: no route, header, key or code path.
- **out-of-scope**: listed in `SCOPE.md` under "Out".
- **n/a**: Bifrost itself removed the feature, or it is not GA upstream, or it is a Go-runtime detail with no HTTP or config meaning. Raiju is not penalised for these.
- Rows marked "Raiju-only" have no Bifrost counterpart. They are listed so the reader can see what Raiju adds.

Priority: P0 means a Bifrost user would hit it on the first day of switching, or it is a silent security or budget failure. P1 means a common Bifrost workflow breaks or behaves differently. P2 means a long-tail feature, a feature outside `SCOPE.md`, or a decision still to be made.

## Summary

Parity rows (one per feature or route family): **498**. Status counts: done 195, partial 133, missing 152, out-of-scope 11, n/a 7. Raiju-only extras (not parity items, listed for context): 25.

| Section | done | partial | missing | out-of-scope | n/a | Parity rows | Raiju-only extras |
|---|---:|---:|---:|---:|---:|---:|---:|
| (a) HTTP routes | 54 | 32 | 46 | 2 | 1 | 135 | 7 |
| (b) Headers | 29 | 7 | 16 | 0 | 2 | 54 | 8 |
| (c) config.json | 28 | 25 | 35 | 2 | 1 | 91 | 3 |
| (d) Providers | 33 | 29 | 2 | 4 | 0 | 68 | 1 |
| (e) Plugins | 2 | 8 | 5 | 0 | 0 | 15 | 3 |
| (f) Governance | 14 | 8 | 9 | 1 | 1 | 33 | 0 |
| (g) MCP | 11 | 4 | 14 | 1 | 0 | 30 | 0 |
| (h) Observability | 21 | 5 | 12 | 0 | 0 | 38 | 2 |
| (i) Enterprise | 5 | 13 | 13 | 1 | 2 | 34 | 1 |
| **Total** | **197** | **131** | **152** | **11** | **7** | **498** | **25** |

The original summary counted 497 parity rows. The tables hold 498, because section (i) was one row short. The re-audit recount fixes this. The `n/a` rows are features Bifrost has removed (x-bf-azure-endpoint, x-bf-bedrock-*, x-bf-prom-*), features Bifrost has not shipped (Google and GitHub SSO), a managed offering (InVPC), or Go-runtime settings with no HTTP or config meaning. The `out-of-scope` rows are the SCOPE.md "Out" items: videos, containers, SCIM, MCP code mode and media providers.

Headline gaps after the re-audit: unpriced models (G4), the OpenAI deployment routes (G5), the unmapped plugin names (G7) and the non-OpenAI media routes (G16). The top-15 list is at the end.


Route coverage by path shape:

| Set | Documented operations | Shape-matched in Raiju |
|---|---|---|
| All Bifrost OpenAPI operations | 669 | 85 (13%) |
| Inference and SDK route families, excluding videos and containers | 223 | 45 (20%) |
| Management and admin (`/api/*`, agents, OAuth) | 412 | 38 (9%) |

Several `SCOPE.md` entries overstate parity. "OpenAI SDK route", "Bedrock SDK route", "Google GenAI SDK route", "Anthropic SDK route", "Audio", "Images", "Files and batches", "Realtime", "config.json compatibility" and "Prometheus metrics" are all marked "done", but each has partial or missing pieces listed below. Gap G32 covers this.

## (a) HTTP routes

### a1. Native /v1 API

Bifrost: `transports/bifrost-http/handlers/inference.go`, `asyncinference.go`, `mcpinference.go`, `wsrealtime.go`, `webrtcrealtime.go`, `realtime_client_secrets.go`, `wsresponses.go`, `livecontrol.go`, `wslive.go`. Documented in `docs/openapi/openapi.json`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| POST /v1/chat/completions | handlers/inference.go; openapi | done | `server.tov:212` (non-stream), `server.tov:330` and `front.tov:58-70` (stream). |
| POST /v1/completions | handlers/inference.go | partial | `server.tov:214`. Text completions only for OpenAI-format providers (`gateway.tov:1289-1293`, `streamsNatively`). |
| POST /v1/responses (create, stream) | handlers/inference.go; supported-providers/*.mdx | done | `server.tov:215`, `native.tov:187-212`. Native for OpenAI, translated for other chat providers. |
| GET /v1/responses/{id} | handlers/inference.go; supported-providers/openai.mdx "Responses Lifecycle" | done | `media.tov:45`. Retrieve through the Responses lifecycle (commit 12757de). OpenAI and Azure, as Bifrost documents it. |
| DELETE /v1/responses/{id} | same | done | `media.tov:46`. Delete through the Responses lifecycle (commit 12757de). OpenAI and Azure. |
| POST /v1/responses/{id}/cancel | same | done | `media.tov:47`. Cancel through the Responses lifecycle (commit 12757de). OpenAI and Azure. |
| GET /v1/responses/{id}/input_items | same | done | `media.tov:48`. Input items through the Responses lifecycle (commit 12757de). OpenAI and Azure. |
| POST /v1/responses/input_tokens | handlers/inference.go | done | `media.tov:43`. Commit 12757de. |
| POST /v1/responses/compact | handlers/inference.go; openai.mdx "Context Compaction" | done | `media.tov:44`. Commit 12757de. |
| GET /v1/responses (WebSocket mode) | handlers/wsresponses.go | missing | P2. |
| POST /v1/embeddings | handlers/inference.go | done | `server.tov:213`; `providers/index.tov:25-49`. |
| POST /v1/rerank | handlers/inference.go | done | `extras.tov:27-55`. Cohere and vLLM answer natively. Other providers return an error. Model `raiju/lexical` asks for the local BM25 ranking (commit 12757de). |
| POST /v1/ocr | handlers/inference.go; supported-providers/mistral.mdx | done | `media.tov:40`. OpenAI-format and Azure only. |
| POST /v1/audio/speech | handlers/inference.go | partial | `media.tov:27`. OpenAI-compatible, Azure and Gemini (WAV or PCM, commit c363369). Other providers are not routed. |
| POST /v1/audio/transcriptions | handlers/inference.go | partial | `media.tov:29`. OpenAI-compatible and Azure only. Gemini transcription is missing. |
| POST /v1/audio/translations | not in Bifrost openapi | done (Raiju-only) | `media.tov:27`. |
| POST /v1/images/generations | handlers/inference.go | partial | `media.tov:28`. OpenAI-compatible, Azure and Gemini (Imagen and image models, commit c363369). |
| POST /v1/images/edits | handlers/inference.go | partial | `media.tov:31`. OpenAI-compatible and Azure only. |
| POST /v1/images/variations | handlers/inference.go | partial | `media.tov:32`. OpenAI-compatible and Azure only. |
| /v1/videos (create, edits, list, get, content, delete, remix) | handlers/inference.go | out-of-scope | `SCOPE.md` Out: videos. |
| /v1/containers (and /files) | handlers/inference.go | out-of-scope | `SCOPE.md` Out: containers. |
| POST /v1/files, GET /v1/files | handlers/inference.go | partial | `media.tov:33-34`. OpenAI-compatible, Azure, Anthropic and Gemini (native, commit c363369). Vertex, Bedrock and Cohere missing (see d2). |
| GET/DELETE /v1/files/{id}, GET /v1/files/{id}/content | handlers/inference.go | partial | `media.tov:35-37`. Same providers as the file list. Vertex, Bedrock and Cohere missing. |
| POST /v1/batches, GET /v1/batches | handlers/inference.go | partial | `media.tov:38-39`. OpenAI-compatible, Azure, Anthropic and Gemini natively (commit c363369). Vertex, Bedrock and Cohere missing. |
| GET /v1/batches/{id}, POST /v1/batches/{id}/cancel | handlers/inference.go | partial | `media.tov:40-41`. Same providers as the batch list. |
| GET /v1/batches/{id}/results | handlers/inference.go | missing | No route (`media.tov:23-41` has none). Anthropic and Gemini batch output is read through `/v1/files/{id}/content` instead. |
| GET /v1/models | handlers/inference.go | done | `server.tov:202`, `listModels` at `server.tov:75-84`. Upstream listing for OpenAI-format, Anthropic and Gemini (`server.tov:31-42`). |
| GET /v1/models/{model} | handlers/inference.go (modelRetrieve) | partial | `server.tov` `retrieveModel` (commit 896b797). Returns `{id, owned_by, listed}` from the known model list. No provider metadata is fetched. |
| POST /v1/mcp/tool/execute | handlers/mcpinference.go | done | `server.tov:220`. |
| GET /v1/realtime (WebSocket upgrade) | handlers/wsrealtime.go | done (OpenAI, Azure) | `server.tov:323-328`, `front.tov:86-90`. Other realtime providers (xAI, ElevenLabs) are not wired. |
| POST /v1/realtime/calls (WebRTC SDP) | handlers/webrtcrealtime.go | done | `media.tov:52`. Passed through to OpenAI-compatible providers (commit 12757de). |
| POST /v1/realtime/client_secrets | handlers/realtime_client_secrets.go | done | `media.tov:50`. Passed through to OpenAI-compatible providers (commit 12757de). |
| POST /v1/realtime/sessions | openapi | done | `media.tov:51`. Passed through to OpenAI-compatible providers (commit 12757de). |
| /v1/live/sessions (REST, WebSocket attach, content) | handlers/livecontrol.go, wslive.go | missing | P2. Not in `SCOPE.md`. |
| POST /v1/async/{op} (submit) | handlers/asyncinference.go; docs/features/async-inference.mdx | done | `extras.tov:118-128`, `jobs.tov:173-180`. Ops: chat/completions, completions, embeddings, responses, images (generations, edits, variations), audio (speech, transcriptions), rerank, ocr and messages (commits 49ac636 and later). |
| GET /v1/async/{op}/{job_id} (Bifrost poll paths) | handlers/asyncinference.go; async-inference.mdx "Supported Endpoints" | done | `extras.tov:133-140`, `jobs.tov:184-194`. Statuses are pending, processing, completed and failed (`jobs.tov:23`). |
| GET /v1/async/jobs/{id} | not in Bifrost | done (Raiju-only) | `server.tov:203`, `extras.tov:123-127`. |
| POST /v1/count_tokens | not in Bifrost openapi | done (Raiju-only) | `server.tov:217`, `extras.tov:57-93`. Exact for Anthropic and Gemini, estimated (`"exact": false`) elsewhere. |
| POST /v1/decisions (and /openai/v1/decisions) | handlers/inference.go; docs/providers/self-hosted-decision-models.mdx | missing | P2. |

### a2. SDK and compatibility routes

Bifrost: `transports/bifrost-http/integrations/*.go`. Mounted by `handlers/integrations.go:33-51`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| POST /openai/v1/chat/completions, /openai/chat/completions | integrations/openai.go | done | `server.tov:167` (`CHAT_PATHS`). |
| POST /openai/deployments/{d}/chat/completions | integrations/openai.go | partial | `server.tov:212`. Chat only. |
| /openai/deployments/{d}/{embeddings, completions, responses, images, audio, models} | integrations/openai.go; openapi | missing | Only chat is routed for deployments. |
| POST /openai/v1/completions, /embeddings, /responses; GET /openai/v1/models; WS /openai/v1/realtime | integrations/openai.go | done | `server.tov:213-215`, `202`, `323`. |
| /openai/v1/audio/speech, /transcriptions; /openai/v1/images/*; /openai/v1/files*; /openai/v1/batches* | integrations/openai.go | done | `compatPath` maps `/openai/v1/` onto the `/v1` routes (commit 896b797). Media routes in `media.tov`. |
| /openai/v1/responses/{id} (GET, DELETE), cancel, input_items; /openai/v1/responses/input_tokens and /compact | integrations/openai.go | done | `compatPath`, then `media.tov:43-48` (commits 896b797 and 12757de). |
| /openai/v1/realtime/calls, client_secrets, sessions | integrations/openai.go | done | `compatPath` (commit 12757de). |
| POST /anthropic/v1/messages (and stream), any provider | integrations/anthropic.go | done | `server.tov:219`, `331`; `native.tov:117-130` (bridged to chat for non-Anthropic targets). |
| POST /anthropic/v1/messages/count_tokens | integrations/anthropic.go | done | `server.tov:218`; `extras.tov:71-79`. |
| GET /anthropic/v1/models | integrations/anthropic.go | done | `anthropic_batch.tov:308-310` (commit c363369). |
| /anthropic/v1/messages/batches (create, list, get, cancel, results) | integrations/anthropic.go | done | `anthropic_batch.tov:313-319` (commit c363369). Passed to Anthropic, or converted through an OpenAI-format provider. |
| /anthropic/v1/files (upload, list, get, content, delete) | integrations/anthropic.go | done | `anthropic_batch.tov:321-326` (commit c363369). |
| POST /anthropic/v1/complete (legacy) | integrations/anthropic.go | missing | P2. |
| POST /genai/v1beta/models/{m}:generateContent | integrations/genai.go | done | `native.tov:319-357`. Any provider: Gemini natively, others through the chat bridge (commit 0b03e53). |
| :streamGenerateContent, :countTokens, :embedContent, :predict | integrations/genai.go | partial | `native.tov:319-357`. All but `:predict`, which is missing. Streams to any provider. |
| GET /genai/v1beta/models, GET /genai/v1beta/models/{m} | integrations/genai.go | done | `server.tov` `genaiModels` (commit 0b03e53). |
| GET /genai/v1beta/models/{m}/operations/{id} | integrations/genai.go | missing | P1. |
| /genai/v1beta/files and /genai/upload/v1beta/files | integrations/genai.go | missing | P1. |
| /genai/v1beta/batches (and /{id}), Vertex batchPredictionJobs | integrations/genai.go | missing | P1. |
| /genai/v1beta/cachedContents (and /{id}, Vertex regional) | integrations/genai.go | missing | P2. |
| POST /genai/v1/rank | integrations/genai.go | missing | P2. Raiju has `/v1/rerank` only. |
| POST /bedrock/model/{id}/converse | integrations/bedrock.go | done | `native.tov:403-446`. Any provider (commit 0b03e53). |
| POST /bedrock/model/{id}/invoke | integrations/bedrock.go | done | `native.tov:403-446`. Any provider (commit 0b03e53). |
| POST /bedrock/model/{id}/converse-stream | integrations/bedrock.go:68 | done | `native.tov:392`, AWS event-stream framing (commit 0b03e53). |
| POST /bedrock/model/{id}/invoke-with-response-stream | integrations/bedrock.go:118 | done | `native.tov:392`, AWS event-stream framing (commit 0b03e53). |
| POST /bedrock/model/{id}/count-tokens | integrations/bedrock.go:323 | partial | `native.tov:408-410`. Returns an estimate (`estimateChatTokens`). No Bedrock count call. |
| POST /bedrock/rerank | integrations/bedrock.go:287 | missing | P1. |
| /bedrock/model-invocation-job(s), /bedrock/files/* | integrations/bedrock.go | missing | P2. |
| POST /cohere/v2/chat, /cohere/v2/embed, /cohere/v2/rerank, POST /cohere/v1/tokenize | integrations/cohere.go:73-200 | done | `server.tov` (`/cohere/v2/*`, `/cohere/v1/tokenize`), `native.tov:284-300` (commit 0b03e53). |
| /litellm/* and /langchain/* prefixes | integrations/litellm.go, langchain.go | done | `compatPath` strips the prefix on every route, Cohere routes included (commit 0b03e53). |
| /pydanticai/* prefix | integrations/pydanticai.go | done | `compatPath` (commit 896b797). |
| /cursor/* routes | integrations/cursor.go | missing | P2. |
| /openai_passthrough, /anthropic_passthrough, /azure_passthrough, /bedrock_passthrough, /genai_passthrough, /chatgpt_passthrough, /runware_passthrough | integrations/passthrough.go:184-261 | partial | `passthrough.tov` `ROUTES` (commit 6b82d47). Six prefixes done. `/runware_passthrough` is not built (its media provider is out of scope). |
| /typesafe/v1/models, /typesafe/v1/systemone | integrations/typesafe.go | missing | P2. |
| /agents/a2a/{name}/* | handlers/agentgateway.go | missing | P2. Not in `SCOPE.md`. |

### a3. Management API (/api)

Bifrost: `transports/bifrost-http/handlers/*.go`, documented in `docs/openapi/openapi.json`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| GET /api/config | handlers/config.go | partial | `store.tov` `handleApi`. Read-only. Secrets are masked in every section (commit 5c2c8af). |
| PUT /api/config, POST /api/config/metadata | handlers/config.go | partial | PUT takes the `client` section only (commit 6b82d47). The metadata route is missing. |
| GET /api/version | handlers/config.go | done | `store.tov` `handleApi` (commit 6b82d47). |
| GET and PUT /api/proxy-config; POST /api/pricing/force-sync | handlers/config.go | partial | `POST /api/pricing/force-sync` is done (`server.tov` `manage`, commit 6b82d47). `/api/proxy-config` is missing. |
| GET /api/providers (list), GET/PUT/DELETE /api/providers/{p} | handlers/providers.go | done | `store.tov:943-968`. PUT upserts. |
| POST/PUT/DELETE /api/providers/{p}/keys[/{id}] | handlers/providers.go | done | `store.tov:971-990`. |
| POST /api/providers (create) | handlers/providers.go | partial | Create-by-POST returns 404. Upsert is through PUT. |
| GET /api/providers/{p}/keys/{id}; POST refresh-models (provider and key) | handlers/providers.go | missing | P2. |
| GET /api/keys | handlers/providers.go | done | `store.tov` `handleApi` (commit 6b82d47). |
| GET /api/models, /details, /base, /parameters; PUT /api/models/catalog | handlers/providers.go | partial | `/api/models` and `/api/models/{provider}` list the catalog (commit 6b82d47). `/details`, `/base`, `/parameters` and PUT catalog are missing. |
| /api/governance/virtual-keys CRUD | handlers/governance.go | done | `store.tov:924-941`. |
| VK rotate (collection and per key), GET /virtual-keys/quota, budget override PUT/DELETE, VK users | handlers/governance.go | missing | P2. |
| /api/governance/budgets, rate-limits, customers, teams | handlers/governance.go | done | `store.tov:33` (`COLLECTIONS`). Raiju exposes CRUD; the Bifrost documented routes for budgets and rate limits are read-only. |
| /api/governance/model-configs CRUD | handlers/governance.go | done | `store.tov` `modelConfigRoute` (commit 31f4aaa). |
| /api/governance/providers (provider-level budgets and limits) | handlers/governance.go | done | `store.tov` `providerGovRoute` (commit 31f4aaa). |
| /api/governance/pricing-overrides CRUD | handlers/governance.go | done | `store.tov` `pricingRoute` (commit 31f4aaa). |
| /api/governance/routing-rules and /api/routing/rules CRUD | handlers/governance.go, routing.go | partial | Config file only (`config.tov`, `governance.routing_rules`). No management API. |
| /api/routing/complexity-analyzer-* and /api/governance/complexity-analyzer-config | handlers/routing.go | partial | Config only (`complexity_router` in `config.tov`). No API. |
| /api/governance/business-units CRUD, customers, users, governance | handlers/governance.go | missing | P2. |
| /api/governance/projects CRUD and members | handlers/governance.go | missing | P2. |
| /api/users CRUD, /api/governance/users, /users/email/{email}, PUT /users/{id}/role, /users/me/permissions | handlers/governance.go | partial | `ops.tov` users(), `rbac.tov`. CRUD and Basic or Bearer tokens. No role endpoint, no email lookup, no VK links. |
| /api/governance/access-profiles CRUD | handlers/governance.go | partial | `profiles.tov`. CRUD only. No versions, clone, activate or deactivate, roles, or propagate. |
| /api/roles, /api/permissions, /api/resources, /api/operations, /api/governance/rbac/* | handlers/governance.go, roles | partial | `rbac.tov`: four fixed roles (admin, editor, viewer, auditor). No custom roles and no permission API. |
| GET /api/governance/usage | not in Bifrost (budget usage is GET /api/governance/budgets) | done (Raiju-only) | `server.tov:207`. |
| GET /api/logs (list and filters) | handlers/logging.go | partial | `server.tov:205`. Filters: limit, model, offset, provider, since, status, text, until, virtual_key (`logstore.tov` parseQuery). Bifrost's filter set is larger. |
| GET /api/logs/stats | handlers/logging.go | partial | `server.tov:206`. Response shape differs. |
| GET /api/logs/{id}, /sessions/{id}, /sessions/{id}/summary | handlers/logging.go | missing | P2. |
| GET /api/logs histograms (cost, tokens, latency, models, throughput, by provider or dimension), rankings, dashboard, filterdata, dropped | handlers/logging.go | missing | P2. |
| DELETE /api/logs; POST /api/logs/recalculate-cost (status, cancel) | handlers/logging.go | missing | P2. |
| /api/logs/user-agent-mappings CRUD | handlers/logging.go | missing | P2. |
| GET/DELETE /api/mcp-logs and sub-routes | handlers/logging.go | missing | P2. |
| GET /api/mcp (status) and GET /api/mcp/clients | handlers/mcp.go | done | `server.tov` `mcpView` at `/api/mcp`. `/api/mcp/clients` in `mcpapi.tov` (commit 5c2c8af). |
| /api/mcp/client CRUD; reconnect, refresh-tools, verify-headers, verify-exchange, reauthorize, reregister, initiate-verification, complete-oauth, openapi-spec | handlers/mcp.go | partial | CRUD, reconnect and refresh-tools in `mcpapi.tov` (commit 5c2c8af). Verify, reauthorize, reregister, initiate-verification, complete-oauth and openapi-spec answer 501 (`mcpapi.tov:494`). |
| /api/mcp/library (and force-sync, filterdata); POST /api/mcp/openapi/preview | handlers/mcp.go | missing | P2. |
| /api/mcp/virtual-mcps CRUD, virtual-key attach and detach | handlers/virtualmcp.go | done | `mcpapi.tov` `virtualRoute`, with virtual-key attach and detach (commit 5c2c8af). |
| /api/mcp/tool-groups CRUD | openapi | missing | P2. |
| /api/mcp/sessions (list, reauth, revoke); /api/oauth/per-user/flows/* | handlers/mcpsessions.go | missing | P2. |
| /api/mcp/per-user-headers flows and credential revoke | handlers/mcpheaders.go | missing | P2. |
| /api/oauth/callback, /api/oauth/config/{id}/status, DELETE /api/oauth/config/{id} | handlers/mcpoauth2.go | missing | P2. Raiju does client credentials and refresh only (`mcpauth.tov`). |
| /api/oauth2/sessions; /api/oauth2/consent/flows/* | handlers/mcpoauth2sessions.go, mcpoauth2consent.go | missing | P2. |
| /.well-known/oauth-protected-resource, /.well-known/oauth-authorization-server, /.well-known/jwks.json, /oauth2/register, /oauth2/authorize, /oauth2/token | handlers/mcpoauth2discovery.go, mcpoauth2issuance.go | missing | P2. Raiju reads these as an OAuth client only (`mcpauth.tov`). |
| /api/session/login, logout, is-auth-enabled, ws-ticket, setup | handlers/session.go | missing | P2. Raiju authenticates with Basic or Bearer user tokens (`rbac.tov:99-100`) and OIDC session tokens (`ops.tov:582`). |
| /api/oidc/login, /api/oidc/callback, /api/oidc/status | not in Bifrost openapi | done (Raiju-only) | `ops.tov:448-460`. |
| /api/audit-logs (list), /export, /verify | enterprise/audit-logs.mdx; openapi | partial | `ops.tov:609-636`. No {id} route, no filterdata, no `/api/governance/audit-logs` alias. |
| /api/alerts | not in Bifrost openapi | partial (Raiju-only) | `ops.tov:638-643`. GET only. |
| /api/notifications (GET, POST) | handlers/notifications.go | missing | P2. |
| /api/webhooks CRUD, /{id}/test, /{id}/rotate-secret, deliveries, redeliver | handlers/webhooks.go | missing | P2. Not in `SCOPE.md`. |
| /api/plugins CRUD, /builtins, /loaded | handlers/plugins.go | missing | P2. Plugins are config-only (`config.tov`, `plugins`). |
| /api/feature-flags | handlers/featureflags.go | missing | P2. |
| GET /api/cache (stats) | handlers/cache.go | partial | `server.tov:204`. DELETE /api/cache/clear/{id} and /clear-by-key/{key} are missing. |
| /api/circuit-breaker/policies, /state | openapi | missing | P2. Config only (`health`). |
| POST /api/vault/flush-cache | openapi | missing | P2. |
| POST /api/cluster/sync (peer sync) | Bifrost has its own cluster gossip (`cluster_config`) | partial | Raiju-only HMAC protocol (`ops.tov:327`). Not wire-compatible with Bifrost clustering. |
| /api/prompt-repo/* | handlers/prompts.go | missing | P2. Not in `SCOPE.md`. |
| /api/skills/* and /api/skills/serve/* (marketplace git, zip) | handlers/skills.go, skills_serving.go | missing | P2. Not in `SCOPE.md`. |
| /api/agents/* (history, push-configs, inspect) | handlers/agentgateway.go | missing | P2. Not in `SCOPE.md`. |
| /api/warp/* | handlers/warp.go | missing | P2. Not in `SCOPE.md`. |
| /api/sidekiq/jobs* | handlers/sidekiq.go | missing | P2. Bifrost's internal job queue. |
| /api/dev/pprof* | handlers/devpprof.go | n/a | Dev-only profiling. |

### a4. Ops and transport

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| GET /health | handlers/health.go | done | `server.tov:199`. Returns `{"status":"ok"}`. |
| GET /metrics | plugins/telemetry | partial | `server.tov`. Families and labels follow Bifrost (`metrics.tov`, commits 202c6e6 and 0b03e53). Routing, key-rotation, active-request, provider-key-up, MCP-duration and overhead-component families are missing (h1). |
| GET / (web UI) | handlers/ui.go | done | `server.tov:200`, `ui_assets.tov`. Raiju's own UI, a subset of Bifrost's. |
| CORS and preflight (`client.allowed_origins`) | lib/ | done | `server.tov` `EXPOSED` is sent as `Access-Control-Expose-Headers` (commit abf4a31). |
| POST /mcp (gateway as MCP server, sessions) | handlers/mcpserver.go | done | `ops.tov:645-700`, `mcpserver.tov`. |
| GET /mcp (SSE stream) and GET /mcp/{slug} | handlers/mcpserver.go | missing | P2. `ops.tov:687` returns 405 for non-POST (except DELETE). |
| POST /mcp/{slug} (virtual MCP) | handlers/mcpserver.go | done | `server.tov:197`, `vmcp.tov`. |
| /ws (UI WebSocket) | handlers/websocket.go | missing | P2. |
| HTTP/1.1 server and Bun.serve | n/a | done (Raiju-only) | `front.tov`, `server.tov`. |

## (b) Headers

### b1. Request headers

Bifrost: string literals in `transports/bifrost-http/lib/ctx.go`, `ConvertToBifrostContext` (about lines 419-766), and `lib/virtualkey.go`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| x-bf-vk | lib/ctx.go:421 | done | `governance.tov:124`. |
| VK in Authorization Bearer, x-api-key, x-goog-api-key or api-key | docs/features/governance/virtual-keys.mdx; lib/ctx.go:419-422 | done | `governance.tov:126-130`. |
| x-bf-api-key (pin a key by name or id) | lib/ctx.go:548 | done | `gateway.tov` (x-bf-api-key); `router.tov:63-70` (pickKey). |
| x-bf-api-key-id | lib/ctx.go:554 | done | `gateway.tov` (x-bf-api-key-id). |
| x-bf-direct-key (raw provider key from the caller) | lib/ctx.go:422, 900; lib/ctx.go:59-60 | done | `governance.tov:77-81`. Used only when `client.allow_direct_keys` is on (commit cbd6ad3). |
| x-bf-session-id | lib/ctx.go:618 | done | `affinity.tov`. |
| x-bf-session-ttl | lib/ctx.go:622 | done | `affinity.tov`. |
| x-bf-session-affinity | lib/ctx.go:638 | done | `affinity.tov`. |
| x-bf-project-id, x-bf-project-name | lib/ctx.go (project keys) | missing | No projects. P2. |
| x-bf-customer-id, x-bf-customer-name | docs/features/governance/budget-and-limits.mdx | missing | Customer comes from the VK only. P2. |
| x-bf-dim-* (custom metric and log dimensions) | lib/ctx.go:443 | partial | Prometheus labels only, through `client.prometheus_labels` (`metrics.tov:319-349`, commit cbd6ad3). Log dimensions are not recorded. |
| x-bf-prom-* (custom Prometheus labels) | lib/ctx.go:449 | n/a | Removed upstream. Bifrost swallows it (`transports/bifrost-http/lib/ctx.go:449`). Use `x-bf-dim-*`, which is done. |
| x-bf-maxim-* | lib/ctx.go:455; plugins/maxim | missing | Third-party plugin, not in `SCOPE.md`. Decide. |
| x-bf-mcp-include-clients | lib/ctx.go:477 (x-bf-mcp- prefix) | done | `gateway.tov` (x-bf-mcp-include-clients). |
| x-bf-mcp-include-tools | docs/mcp/filtering.mdx | missing | P2. |
| x-bf-mcp-session-id | lib/ctx.go:504 | missing | P2. |
| x-bf-eh-* (forward extra headers to the provider) | lib/ctx.go:651 | done | `gateway.tov` (x-bf-eh-). |
| x-bf-cache-key | lib/ctx.go:561 | done | `gateway.tov`. |
| x-bf-cache-ttl | lib/ctx.go:566 | done | `gateway.tov`. |
| x-bf-cache-threshold | lib/ctx.go:587 | done | `gateway.tov`. |
| x-bf-cache-type (direct or semantic) | lib/ctx.go:602 | done | `gateway.tov` (`gateway.tov:948`). |
| x-bf-cache-no-store | lib/ctx.go:607 | done | `gateway.tov`. |
| x-bf-prompt-cache-auto-inject | lib/ctx.go:725 | done | `gateway.tov`. |
| x-bf-disable-content-logging | lib/ctx.go:743 | done | `gateway.tov:1503` (commit 12757de). |
| x-bf-store-raw-request-response | lib/ctx.go:737 | missing | P2. |
| x-bf-send-back-raw-request | lib/ctx.go:715 | done | `gateway.tov:404-412` (commit cbd6ad3). Per provider, or per request with `client.allow_per_request_raw_override`. |
| x-bf-send-back-raw-response | lib/ctx.go:731 | done | `gateway.tov:404-412` (commit cbd6ad3). Per provider, or per request with `client.allow_per_request_raw_override`. |
| x-bf-parent-request-id | lib/ctx.go:750 | missing | P2. |
| x-bf-passthrough-extra-params | lib/ctx.go:757 | missing | P2. |
| x-bf-compat | lib/ctx.go:766 | missing | P2. Compat plugin (G37). |
| x-bf-async-webhook, x-bf-async-job-result-ttl | lib/ctx.go:675; docs/features/async-inference.mdx | missing | P2. |
| x-bf-prompt-id, x-bf-prompt-version | plugins/prompts; docs/features/prompt-repository | missing | P2. Not in `SCOPE.md`. |
| x-bf-model-provider | docs; server listing | done | `server.tov:76`. |
| x-bf-list-models-provider | docs | done | `server.tov:76`. |
| x-bf-agent-correlation-id, x-bf-agent-vk-id, x-bf-agent-auth | handlers/agentgateway.go | missing | P2. |
| x-bf-lh-* (logging headers, `client.logging_headers`) | docs; config.schema.json client | missing | P2. |
| x-bf-app, x-bf-user-id, x-bf-env, x-bf-tenant (attribution) | core/schemas/enrichment.go (app); docs | partial | Only `x-bf-app` is read, for the `app` metric and log label (`gateway.tov:1342`). `x-bf-user-id`, `x-bf-env` and `x-bf-tenant` are not read. |
| x-bf-azure-endpoint, x-bf-bedrock-* | docs (removed in v1.5) | n/a | Removed upstream. |
| x-request-id (incoming id reused as the request id) | lib/responseheaders.go | partial | `gateway.tov:867` reads it. It is not echoed back as a response header. |
| x-bf-provider (media provider selection) | not in Bifrost | done (Raiju-only) | `media.tov:123-129`. |
| x-bf-routing-rule | not in Bifrost | done (Raiju-only) | `gateway.tov`. |
| x-bf-complexity-tier | not verified in Bifrost (complexity_tier is a routing-rule variable) | done (Raiju-only) | `gateway.tov`, `complexity.tov`. |
| x-bf-mcp-agent (agent mode toggle) | not in Bifrost (Bifrost uses per-client tools_to_auto_execute) | done (Raiju-only) | `gateway.tov`. |

### b2. Response headers

Bifrost: `transports/bifrost-http/lib/responseheaders.go` (constants at lines 23-132) and `ExposedResponseHeaders`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| x-bifrost-request-id | responseheaders.go:23 | done | `gateway.tov:886`. |
| x-bifrost-trace-id | responseheaders.go:24 | done | `gateway.tov:1285`, when tracing is on (`otel.tov`). |
| x-bifrost-provider | responseheaders.go:70 | done | `gateway.tov` `routedHeaders` (commit abf4a31). |
| x-bifrost-original-model, x-bifrost-resolved-model | responseheaders.go:71-72 | done | `gateway.tov` `routedHeaders` (commit abf4a31). |
| x-bifrost-request-type | responseheaders.go:74 | done | `gateway.tov:1283` (commit abf4a31). |
| x-bifrost-fallback-index | responseheaders.go:73 | done | `gateway.tov` `routedHeaders` (commit abf4a31). |
| x-bifrost-latency-ms, x-bifrost-upstream-latency-ms | responseheaders.go:79, 125 | done | `gateway.tov` (commit abf4a31). |
| x-bifrost-routing-info-* (12 headers) | responseheaders.go:86-97 | partial | 7 of 12 sent (`gateway.tov` `routedHeaders`). Missing: key, alias-model-id, alias-model-name, alias-model-family and server-side-fallback-model. |
| x-bifrost-cache-hit, -hit-type, -id, -hit-latency-ms, -similarity, -threshold, -provider-used, -model-used, -input-tokens, -requested-provider, -requested-model | responseheaders.go:106-116 | partial | Sent: hit, hit-type, requested provider and model, similarity, threshold (`gateway.tov` `cacheHeaders`). Missing: -id, -hit-latency-ms, -provider-used, -model-used, -input-tokens. |
| x-bifrost-pricing-request-type, x-bifrost-converted-request-type | responseheaders.go:126-127 | missing | P2. |
| x-bifrost-dropped-compat-params, x-bifrost-dropped-unsupported-tools | responseheaders.go:128-129 | missing | P2. |
| x-bifrost-passthrough-path | responseheaders.go:130 | missing | P2. |
| x-bifrost-error-type, x-bifrost-retry-after-ms | responseheaders.go:131-132 | partial | x-bifrost-error-type is sent (`gateway.tov:1407`). x-bifrost-retry-after-ms is missing. Raiju reads upstream Retry-After internally. |
| `extra_fields` in the body, or in headers with `client.extra_fields_placement` | lib/responseheaders.go:161-170; config.schema.json client | partial | Body only: raw request and response go in `extra_fields` when send-back is on (`gateway.tov`, `withRawFields`). `client.extra_fields_placement` is missing. |
| Access-Control-Expose-Headers for the x-bifrost-* headers | lib/responseheaders.go ExposedResponseHeaders | done | `server.tov` `EXPOSED` (commit abf4a31). |
| x-bf-attempts | not in Bifrost | done (Raiju-only) | `gateway.tov:593`, `973`. |
| x-bf-fallback-used | not in Bifrost | done (Raiju-only) | `gateway.tov:1002`. |
| x-bf-overhead-us | not in Bifrost | done (Raiju-only) | `gateway.tov:1008`. |
| x-bf-plugin-short-circuit, x-bf-agent-steps, x-bf-agent-tool-calls | not in Bifrost | done (Raiju-only) | `gateway.tov`. |

## (c) config.json

### c1. Top-level sections

Bifrost: top-level properties of `transports/config.schema.json`. Raiju: `Config` in `src/config.tov` (lines 280-300) and the loaders in `config.tov`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| version, $schema, source_of_truth, env_label | config.schema.json (top) | missing | Not read. No effect. P2. |
| encryption_key | config.schema.json (top) | missing | Bifrost encrypts stored keys with it. Raiju resolves `env.` and vault references instead (`config.tov` resolveEnv). P2. |
| setup_token | config.schema.json (top) | missing | Setup flow. P2. |
| server.* (read_buffer_size, a2a_*, plugin_download_*) | config.schema.json server | missing | Raiju takes `-port` and `-workers` on the command line. P2. |
| auth_config (admin_username, admin_password, is_enabled, disable_auth_on_inference) | config.schema.json auth_config | done | P0 (G2). All four are read (`config_compat.tov`, `config.tov` resolveConfig): `is_enabled: false` turns admin auth off, and `disable_auth_on_inference` leaves inference open unless `client.enforce_auth_on_inference` says otherwise. 
| client.* | config.schema.json client | partial | See c2. |
| providers.* | config.schema.json providers | partial | See c3. |
| governance.* | config.schema.json governance | partial | See c4. |
| alerting | config.schema.json alerting | done | `config_compat.tov` `alerting` mapping, rules as CEL (commit 8e98ea5). |
| webhooks[] | config.schema.json webhooks | missing | P2. |
| agents[] | config.schema.json agents | missing | P2. Not in `SCOPE.md`. |
| mcp.* | config.schema.json mcp | partial | See c5. |
| vector_store | config.schema.json vector_store | partial | Redis and Qdrant are read (`config.tov`, `vectorstore.tov`, commit d91ef07). Weaviate, Pinecone and chromem are not supported. |
| config_store (sqlite, postgres) | config.schema.json config_store | partial | Raiju stores config as a JSON file with `.bak` (`store.tov`). |
| logs_store.* | config.schema.json logs_store | partial | `config.tov` LogsStoreConfig: enabled, dir, retention_days, max_memory_entries, content_logging; `logstore.tov` prunes by retention_days. Bifrost's type, config, writer and object_storage are ignored. |
| skills_registry | config.schema.json skills_registry | missing | P2. Not in `SCOPE.md`. |
| plugins[] | config.schema.json plugins | partial | `otel` and `semanticcache` entries are mapped (`config_compat.tov` `mapPlugins`, commits 0d269dd and d91ef07). Other names are reported as unknown and not loaded (`plugins.tov:381`). |
| websocket | config.schema.json websocket | missing | P2. |
| guardrails_config | config.schema.json guardrails_config | done | `guardrails_compat.tov`, `main.tov` `withBifrostGuardrails` (commit 0c999ff). |
| audit_logs | config.schema.json audit_logs | partial | Read as `audit` (`config_compat.tov:342-358`). retention_days, omit_ip_addresses, archive_* and object_storage are reported as ignored. |
| cluster_config | config.schema.json cluster_config | partial | Read as `cluster` (`config_compat.tov:362-384`). Type `broker` and discovery settings are not supported. |
| load_balancer_config | config.schema.json load_balancer_config | partial | Mapped into `health.adaptive` (`config_compat.tov:391-431`). Tracker, bootstrap and other fields are reported as ignored. |
| circuit_breaker_config | config.schema.json circuit_breaker_config | done | Mapped to `health.circuit_breaker` (`config_compat.tov:391-406`). |
| large_payload_optimization | config.schema.json large_payload_optimization | missing | P2. |
| scim_config | config.schema.json scim_config | out-of-scope | `SCOPE.md` Out: SCIM. |
| access_profiles (top-level) | config.schema.json access_profiles | missing | Raiju reads `governance.access_profiles` only. P2. |
| feature_flags | config.schema.json feature_flags | missing | P2. |
| proxy_config (global outbound proxy) | config.schema.json proxy_config | missing | Raiju has per-provider proxies only (`config.tov` ProxyConfig). P2. |
| framework.pricing (pricing_url, pricing_sync_interval) | config.schema.json framework; framework/modelcatalog/config.go:109 (default URL) | partial | `pricing_url` and `pricing_sync_interval` become `pricing_sync` (`config_compat.tov:436-451`). Sync runs only when a pricing section is set. Other fields are reported as ignored. |
| Raiju-only top-level keys (cache, prompt_cache, health, pricing, otel, semantic_cache, session_affinity, complexity_router, mcp_server, virtual_mcps, log_exports, exporters, cluster, oidc, alerts, audit, secrets, guardrails) | not in Bifrost (several correspond to Bifrost sections above) | done (Raiju-only) | `config.tov` Config type. Bifrost configs that use the Bifrost names for these will not load into the Raiju fields. |

### c2. client.*

Bifrost: `transports/config.schema.json` `$defs/client` (and `client.*` properties).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| allowed_origins | client.allowed_origins | done | `server.tov:148-157`. |
| enable_logging | client.enable_logging | done | `gateway.tov:448`. |
| enforce_governance_header | client.enforce_governance_header | partial | `governance.tov:85`. Gates the VK requirement, default false. |
| enforce_auth_on_inference | client.enforce_auth_on_inference | done | Read as the gate (`governance.tov:120-121`, commit 32da2e6). When unset, it is on when any credentials exist. |
| required_headers | client.required_headers | done | `governance.tov:86`. |
| max_request_body_size_mb | client.max_request_body_size_mb | done | `main.go:88`. |
| async_job_result_ttl | client.async_job_result_ttl | done | `gateway.tov:400`. |
| mcp_agent_depth | client.mcp_agent_depth | done | `gateway.tov:457`. |
| mcp_tool_execution_timeout | client.mcp_tool_execution_timeout | partial | Raiju has `mcp.tool_execution_timeout_seconds` (`config.tov` McpConfig). |
| mcp_tool_sync_interval | client.mcp_tool_sync_interval | missing | P2. Raiju has no periodic tool re-sync. |
| mcp_auto_execute | not in Bifrost (Bifrost: per-client tools_to_auto_execute) | done (Raiju-only) | `gateway.tov:456`. |
| disable_content_logging | client.disable_content_logging | done | `gateway.tov:1503-1504` (commit 12757de). |
| prometheus_labels | client.prometheus_labels | done | `metrics.tov:319-349` (commit cbd6ad3). |
| drop_excess_requests | client.drop_excess_requests | partial | Parsed. A startup note says it does nothing, since there is no queue (`config_compat.tov`, commit cbd6ad3). |
| allow_direct_keys | client.allow_direct_keys | done | `governance.tov:107-108`. Gates `x-bf-direct-key` (commit cbd6ad3). |
| allowed_headers, header_filter_config, logging_headers, whitelisted_routes | client.* | missing | P2. |
| compat | client.compat | missing | P2 (G37). |
| extra_fields_placement | client.extra_fields_placement | missing | P2. |
| dual_credential_conflict_behavior | client.dual_credential_conflict_behavior | missing | P2. |
| hide_deleted_virtual_keys_in_filters, delete_expired_virtual_keys, vk_rotation_cooldown, enforce_vk_object_ownership, hidden_request_types | client.* | missing | P2. |
| routing_chain_max_depth | client.routing_chain_max_depth | missing | P2. |
| mcp_server_auth_mode, oauth2_server_config, mcp_external_client_url, a2a_external_client_url, skills_external_client_url | client.* | missing | P2. |
| log_retention_days | client.log_retention_days | partial | Raiju has `logs_store.retention_days` (`logstore.tov`). P2. |
| initial_pool_size | client.initial_pool_size | n/a | Go connection-pool setting. |
| enforce_scim_auth | client.enforce_scim_auth | out-of-scope | SCIM. |

### c3. providers.*

Bifrost: `$defs/provider`, `base_key`, `network_config`, `custom_provider_config`, `proxy_config`, `azure_key`, `bedrock_key`, `vertex_key`, `prompt_cache`. Raiju: `src/config.tov` (`KeyConfig`, `NetworkConfig`, `ProxyConfig`, `CustomProviderConfig`, `ProviderConfig`).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| keys[]: name, value, models, weight, aliases | base_key | done | `config.tov` KeyConfig; `router.tov`. |
| keys[].use_for_batch_api | base_key | missing | P2. |
| keys[].oauth_key_config | base_key | missing | P2. |
| keys[].azure_key_config (endpoint, deployments, api_version) | azure_key | done | `config.tov` AzureKeyConfig. |
| Azure Entra ID: client_id, client_secret, tenant_id, scopes | azure_key (docs/providers/supported-providers/azure.mdx) | done | `config.tov`, `cloud_auth.tov`. Client credentials, tokens cached (commit 6aeb7f2). |
| bedrock_key_config (access key, secret key, session token, region, deployments) | bedrock_key | partial | `config.tov` BedrockKeyConfig. |
| Bedrock: role_arn, external_id, session_name, arn, batch role and S3, use_openai_endpoints | bedrock_key | partial | role_arn, external_id and session_name assume a role through STS (`config.tov:467-471`, commit 6aeb7f2). Inference-profile arn, batch role and S3, and use_openai_endpoints are missing. |
| vertex_key_config (project_id, region, auth_credentials) | vertex_key | partial | `config.tov` VertexKeyConfig. No aws_workload_identity, service_account_email, audience or token_lifetime. |
| watsonx_key_config | not in Bifrost | done (Raiju-only) | `config.tov`. |
| network_config: base_url, extra_headers, default_request_timeout_in_seconds, max_retries, retry_backoff_initial, retry_backoff_max | network_config | done | `config.tov` NetworkConfig; `router.tov`. |
| network_config: insecure_skip_verify, ca_cert_pem | network_config | done | `providers/types.tov:37-43` (commit b66cf96). |
| network_config: enforce_http2, http2_ping_interval, keep_alive_timeout, max_conns_per_host, stream_idle_timeout, beta_header_overrides, allow_private_network | network_config | missing | P2. |
| concurrency_and_buffer_size | provider.concurrency_and_buffer_size | missing | P2. |
| proxy_config (provider): http with credentials | proxy_config | done | `config.tov` ProxyConfig; `providers/types.tov`. SOCKS5 and environment types are missing (Tov fetch is HTTP only; `SCOPE.md`). |
| send_back_raw_request, send_back_raw_response, store_raw_request_response | provider.* | partial | Both send-back keys work per provider (`gateway.tov:404-412`, commit cbd6ad3). store_raw_request_response is missing. |
| ignore_provider_cost | provider.ignore_provider_cost | missing | P2. |
| injected_tools | provider.injected_tools | missing | P2. |
| custom_provider_config.base_provider_type, is_key_less | custom_provider_config | done | `config.tov`; `router.tov` kindOf. |
| custom_provider_config: allowed_requests, request_path_overrides, does_not_send_done_marker, wait_for_usage, TLS | custom_provider_config | missing | P2. |
| openai_config.disable_store | provider.openai_config | missing | P2. |
| prompt_cache (provider): auto_inject, ttl, cache_control_injection_points | provider.prompt_cache | partial | Raiju has a top-level `prompt_cache.auto_inject` only (`config.tov` PromptCacheConfig). |

### c4. governance.*

Bifrost: `config.schema.json` governance properties. Raiju: `GovernanceConfig` in `config.tov`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| budgets, rate_limits, customers, teams, virtual_keys, routing_rules | governance.* | partial | Core fields done. VK `mcp_configs` and business-unit or project fields are missing. |
| governance.auth_config | governance.auth_config | done | `config.tov` AdminAuthConfig. |
| business_units, projects, roles | governance.* | missing | P2. |
| pricing_overrides | governance.pricing_overrides | done | `store.tov` `pricingRoute`, config `governance.pricing_overrides` (commit 31f4aaa). |
| model_configs | governance.model_configs | done | `store.tov` `modelConfigRoute` (commit 31f4aaa). |
| providers (provider-level governance) | governance.providers | done | `store.tov` `providerGovRoute` (commit 31f4aaa). |
| complexity_analyzer_config | governance.complexity_analyzer_config | partial | Raiju has top-level `complexity_router`. |

### c5. mcp.*

Bifrost: `config.schema.json` `mcp` and `$defs/mcp_client_config`. Raiju: `src/mcp.tov` (`McpClientConfig`, `McpConfig`).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| client_configs[]: name, connection_type (stdio, http, sse), connection_string, headers, stdio_config, tools_to_execute | mcp_client_config | done | `mcp.tov:12-23`. |
| connection_type inprocess, openapi | mcp_client_config.connection_type | missing | P2. |
| auth_type: none, headers, oauth | mcp_client_config.auth_type | done | `mcpauth.tov`. |
| auth_type: per_user_oauth, per_user_headers, token_exchange | mcp_client_config.auth_type | missing | P2. |
| tools_to_auto_execute (per client) | mcp_client_config | partial | Raiju has a global `client.mcp_auto_execute` (`gateway.tov:456`). |
| endpoint_slug, allow_by_default, allow_on_all_virtual_keys, disabled, is_ping_available, needs_session_stickiness | mcp_client_config | partial | Read by the management API (`mcpapi.tov`, commit 5c2c8af). is_ping_available and needs_session_stickiness are missing. |
| require_public_target (SSRF guard), tls_config, allowed_extra_headers, tool_pricing, tool_execution_timeout, tool_sync_interval | mcp_client_config | missing | P2. No SSRF guard in `mcp.tov`. |
| mcp.tool_groups | mcp.tool_groups | missing | P2. |
| mcp.tool_manager_config | mcp.tool_manager_config | missing | P2. |
| mcp.virtual_mcps | mcp.virtual_mcps | done | `config_compat.tov:234-260`, read as top-level `virtual_mcps` (commit 0c999ff). |
| mcp.tool_sync_interval | mcp.tool_sync_interval | missing | P2. |

## (d) Providers

### d1. Provider list

Bifrost: provider constants `core/schemas/bifrost.go:49-82`, and per-provider pages in `docs/providers/supported-providers/`. Raiju: `src/providers/openai.tov` (ENDPOINTS, lines 14-29), `longtail.tov` (lines 10-27), `index.tov`, `anthropic.tov`, `gemini.tov`, `bedrock.tov`, `vertex.tov`, `cohere.tov`, `watsonx.tov`.

The notes list only the operations that differ from the "Supported Operations" table in the Bifrost docs.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| openai | supported-providers/openai.mdx: chat, responses, responses lifecycle, text, embeddings, decisions, speech, STT, images, image edit, files, batch, videos, compaction, models | partial | Raiju: chat, streaming, responses (lifecycle, compaction, input_tokens), text, embeddings, speech, STT, images, files, batch, realtime, models. Missing: decisions. Videos out-of-scope. Evidence `openai.tov:14`. |
| azure | supported-providers/azure.mdx: chat, responses, embeddings, files, images, image edit, models, compaction, decisions, batch | partial | Raiju serves Azure through `openai.tov` and media (`media.tov`). Entra ID is done (commit 6aeb7f2). Missing: decisions. |
| anthropic | supported-providers/anthropic.mdx: chat, responses, text, files, batch, models | partial | Raiju: chat, streaming, responses (bridged), count tokens, models, files and batches (commit c363369). Missing: legacy text. |
| bedrock | supported-providers/bedrock.mdx: chat, responses, text, embeddings, files, batch, models, images, image edit and variation, count tokens | partial | Raiju: Converse chat and streaming, responses (bridged), embeddings (Titan and Cohere), role_arn. Count tokens are an estimate (`native.tov:408`). Missing: files, batch, images. |
| bedrock_mantle | supported-providers/bedrock-mantle.mdx: chat (+stream), responses, tool calling, vision, reasoning, structured outputs, prompt caching, models, count tokens | partial | Chat through the Bedrock OpenAI-compatible endpoint (`providers/bedrock_mantle.tov`, commit 6aeb7f2). Anthropic-family models are refused (`bedrock_mantle.tov:60`). No model list or count tokens. |
| cohere | supported-providers/cohere.mdx: chat, responses, embeddings, models | done | Raiju: chat, streaming, embeddings, native rerank (`extras.tov:38-41`), responses (bridged). Cohere SDK routes missing (a2). |
| vertex | supported-providers/vertex.mdx: chat, responses, embeddings, images, image edit, video (out), models, text, batch and files through genai routes | partial | Raiju: chat, streaming, embeddings, responses, count tokens (`extras.tov:80-86`). Missing: images, image edit, batch, files, model list. |
| mistral | supported-providers/mistral.mdx: chat, responses, STT, OCR, embeddings, models | done | Raiju: OpenAI-compatible (`openai.tov:16`); STT and OCR routed through media. |
| ollama | supported-providers/ollama.mdx: chat, responses, text, embeddings, models, decisions | done | Raiju: `openai.tov:26`. Decisions missing (a1). |
| opencode-go | supported-providers/opencode.mdx: chat, responses, models | done | OpenAI-compatible base (`longtail.tov`, commit d27a62e). |
| opencode-zen | supported-providers/opencode.mdx: chat, responses, models | done | OpenAI-compatible base (`longtail.tov`, commit d27a62e). |
| groq | supported-providers/groq.mdx: chat, responses, models | done | `openai.tov:15`. |
| sgl | supported-providers/sgl.mdx: chat, responses, text, embeddings, models, count tokens | done | `openai.tov:28`. Count tokens estimated. |
| parasail | supported-providers/parasail.mdx: chat, responses, models, embeddings | done | `openai.tov:23`. |
| perplexity | supported-providers/perplexity.mdx: chat, responses, models, decisions | done | `openai.tov:25`. Decisions missing. |
| cerebras | supported-providers/cerebras.mdx: chat, responses, text, models | done | `openai.tov:19`. |
| deepseek | supported-providers/deepseek.mdx: chat, responses, text, models | done | `openai.tov:18`. |
| gemini | supported-providers/gemini.mdx: chat, responses, speech, STT, images, image edit, video (out), embeddings, files, batch, models, count tokens | partial | Raiju: chat, streaming, responses, embeddings, count tokens (`extras.tov:80-86`), models, speech, images (Imagen), files and batch (commit c363369). Missing: STT. |
| github-copilot | supported-providers/github-copilot.mdx: chat, responses, models | partial | Chat through a Copilot token or a GitHub App (`providers/githubcopilot.tov`, commit d27a62e). Model listing is missing (only OpenAI-compatible, Anthropic and Gemini are listed). |
| huggingface | supported-providers/huggingface.mdx: routes to 19 inference backends (fal-ai, hf-inference, cerebras, sambanova and others) with chat, embeddings, speech, transcription and image operations | partial | Raiju uses only the single Hugging Face router as an OpenAI-compatible endpoint (`longtail.tov:10`). No multi-backend routing, no model aliasing, no speech, transcription or image operations. |
| nebius | supported-providers/nebius.mdx: chat, responses, text, embeddings, images, models | done | `openai.tov:22`. |
| xai | supported-providers/xai.mdx: chat, responses, text, images, compaction, models | partial | Raiju: `openai.tov:17`. Missing: xAI realtime (Raiju realtime is OpenAI and Azure only). Compaction missing. |
| replicate | supported-providers/replicate.mdx: chat, responses, text, images, image edit, video (out), files, models | partial | Chat as synchronous predictions (`providers/replicate.tov`, commit d27a62e). Text, images, image edit, files and models are missing. |
| vllm | supported-providers/vllm.mdx: chat, responses, text, embeddings, rerank, STT, count tokens, models, OCR | done | OpenAI-compatible (`openai.tov:27`). Rerank calls vLLM's rerank API (`extras.tov:38-41`, commit 12757de). Count tokens are estimated, as for sgl. |
| runway | supported-providers/runway.mdx: video only | out-of-scope | `SCOPE.md` Out: videos, media providers. |
| runware | supported-providers/runware.mdx: image, video, other media tasks | out-of-scope | `SCOPE.md` Out: media providers. |
| fireworks | supported-providers/fireworks.mdx: chat, responses, text, embeddings, models, count tokens | done | `openai.tov:20`. |
| sarvam | supported-providers/sarvam.mdx: chat, responses, speech, STT, models, text, embeddings | partial | Chat only, through the OpenAI-compatible endpoint (`longtail.tov`, commit d27a62e). Speech, STT, text, embeddings and models are missing. |
| wafer | supported-providers/wafer.mdx: chat, responses, text, file upload, models | partial | Chat only (`longtail.tov`, commit d27a62e). File upload, text and models are missing. |
| databricks | supported-providers/databricks.mdx: chat, responses, embeddings, models, decisions | partial | Chat and embeddings (`providers/databricks.tov`, commit d27a62e). Decisions and model listing are missing. |
| cloudflare | supported-providers/cloudflare.mdx: chat, responses, embeddings, decisions, models, rerank | partial | Chat and embeddings (`providers/cloudflare.tov`, commit d27a62e). Rerank, decisions and model listing are missing. |
| typesafe | supported-providers/typesafe.mdx: decisions, models | missing | P2 (G36). |
| elevenlabs | supported-providers/elevenlabs.mdx: speech, sound effects, STT, models, realtime | out-of-scope | `SCOPE.md` Out: media providers. |
| Raiju-only providers: together, lmstudio, nvidia, sambanova, deepinfra, novita, hyperbolic, lambda, moonshot, zhipu, dashscope, ai21, upstage, baseten, featherless, inception, friendli, siliconflow, github (GitHub Models), watsonx | not Bifrost constants (Bifrost reaches OpenAI-compatible endpoints through custom providers) | done (Raiju-only) | `openai.tov:14-29`, `longtail.tov:10-27`, `watsonx.tov`. Each is an OpenAI-compatible base URL plus prefix. |
| custom OpenAI-compatible providers | custom_provider_config | done | `config.tov`, `router.tov`. See c3 for the missing options. |

### d2. Operations across providers

Bifrost: `core/schemas/bifrost.go:135-200` (request types), `core/providers/<name>/` (implementations).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Chat completions (non-stream) | core/providers | done | `providers/index.tov:51-64`. |
| Chat completions (stream) | core/providers | done | `providers/index.tov:67-74`; `server.tov:330`, `front.tov`. Native SSE for OpenAI-format and Azure; converted for Anthropic, Gemini, Bedrock, Cohere, Vertex (`streams.tov`, `streams_cohere.tov`). |
| Text completions | ChatCompletion-style text (text_completion) | partial | OpenAI-format providers only (`gateway.tov:1289-1293`). |
| Responses API (create) | responses | done | Native OpenAI, translated others (`native.tov:187-212`). |
| Responses lifecycle (retrieve, delete, cancel, input_items) | responses_retrieve, responses_delete, responses_cancel, responses_input_items | done | `media.tov:45-48` (commit 12757de). OpenAI and Azure. |
| Responses input_tokens and compaction | responses_* | done | `media.tov:43-44` (commit 12757de). |
| Embeddings | embedding | done | `providers/index.tov:25-49`. Anthropic has no embeddings upstream in Bifrost either. |
| Speech (TTS) | speech, speech_stream | partial | OpenAI-compatible, Azure and Gemini (commit c363369). Other providers are not routed. |
| Transcription (STT) | transcription, transcription_stream | partial | OpenAI-compatible and Azure only. Gemini STT is missing. |
| Images (generate, edit, variation) | image_generation, image_edit, image_variation | partial | Generation: OpenAI-compatible, Azure and Gemini (Imagen). Edits and variations: OpenAI-compatible and Azure only. |
| Files | file_upload, file_list, file_retrieve, file_delete, file_content | partial | OpenAI-compatible, Azure, Anthropic and Gemini (commit c363369). Vertex, Bedrock and Cohere missing. |
| Batches | batch_create, batch_list, batch_retrieve, batch_cancel, batch_results, batch_delete | partial | OpenAI-compatible, Azure, Anthropic and Gemini (commit c363369). The results route is missing (a1). |
| Rerank | (provider rerank) | done | Cohere and vLLM natively. Others error, except `raiju/lexical` (`extras.tov:27-55`, commit 12757de). |
| Count tokens | count_tokens | partial | Exact for Anthropic and Gemini (`extras.tov:80-86`). Estimated elsewhere, marked `"exact": false` (`extras.tov:69`). Bedrock is an estimate too. |
| List models | list_models | partial | Upstream listing for OpenAI-format, Anthropic, Gemini (`server.tov:31-42`). Others return the configured models only. |
| Retrieve model | model_retrieve | partial | Route exists (`server.tov` `retrieveModel`). Returns a stub with `listed`, not provider metadata. |
| OCR | ocr | done | Mistral and OpenAI-compatible (`media.tov:40`). |
| Realtime (WebSocket) | realtime (provider-specific) | partial | OpenAI and Azure only (`SCOPE.md`). |
| Realtime (WebRTC, client secrets, sessions) | realtime calls and client secrets | done | `media.tov:50-52` (commit 12757de). OpenAI-compatible providers. |
| Videos and containers | video_*, container_* | out-of-scope | `SCOPE.md` Out. |
| Passthrough (raw upstream proxy) | Passthrough, PassthroughStream | partial | Six of seven prefixes (`passthrough.tov`, commit 6b82d47). `/runware_passthrough` is missing (media provider, out of scope). |
| Decisions | Decision (typesafe, openai, openrouter, cloudflare, databricks, perplexity, ollama) | missing | P2 (G36). |
| Async jobs | core/schemas/async.go | done | See a1. |
| Prompt caching (automatic injection) | prompt_cache.auto_inject, cache_control_injection_points | partial | Anthropic and Bedrock auto-inject (`anthropic.tov`, `bedrock.tov`; SCOPE). `cache_control_injection_points` missing. |
| Reasoning / thinking parameters | docs/providers/reasoning.mdx (provider conversions) | done | `reasoning.tov`, `providers/anthropic.tov`, `gemini.tov`, `bedrock.tov` (commit ac4bf4f). |
| Retries with backoff and Retry-After | network_config.max_retries and backoff | done | `router.tov`, `gateway.tov:640`. |
| Fallback chains | fallbacks in request, routing rules | done | `router.tov`, `cel.tov`, `gateway.tov`. |
| Weighted key balancing and per-key model lists | keys[].weight, keys[].models | done | `router.tov:63-78`, `keyAllows` (`router.tov:51-60`). |
| Key pinning | x-bf-api-key, x-bf-api-key-id | done | `gateway.tov`. |
| Session affinity | x-bf-session-* | done | `affinity.tov`. |
| Model aliases (static, per key) | keys[].aliases | done | `config.tov` KeyConfig.aliases; `router.tov:45-49`. |
| Model aliases (dynamic, scoped, chained) | docs/providers/aliasing-models.mdx | partial | Chained key aliases with cycle and depth checks (`aliases.tov`, commit ebc25c7). Dynamic and scoped aliases are missing. |
| Default provider resolution for unprefixed names | docs/providers/provider-routing.mdx (model catalog) | done | `router.tov`: key model lists, then the model family, then the model catalog (commit ebc25c7). |
| Custom pricing and model catalog sync | framework/modelcatalog; docs/providers/custom-pricing.mdx | partial | Built-in datasheet (`pricing_data.tov`, commit 0c999ff). Sync from a URL when configured (`ops.tov:436-470`). Pricing overrides exist. Models outside the datasheet still cost 0. |

## (e) Plugins

Bifrost: `plugins/<name>/main.go` (plugin names at `PluginName` constants). Raiju: `src/plugins.tov` `makePlugin` (lines 347-372) and the feature code in `src/`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| governance plugin | plugins/governance (store.go, resolver.go, tracker.go, mcp.go) | done (built in) | `governance.tov`, `profiles.tov`, `rbac.tov`. Built in rather than loaded as a plugin. |
| logging plugin | plugins/logging (writer.go, costrecalc.go, live.go) | partial | `logstore.tov`, `gateway.tov:448`. No cost recalculation endpoint, no live socket, no SQL writer. |
| telemetry plugin (Prometheus) | plugins/telemetry/main.go | partial | Families and labels follow Bifrost (`metrics.tov`, commit 202c6e6). See h1 for the missing families. |
| otel plugin | plugins/otel (traces and metrics, gRPC or HTTP, span filters) | partial | Traces (OTLP HTTP), metrics push (`otel_metrics.tov`) and plugin options (commits 0d269dd and abf4dbb). No gRPC: collector 4317 is rewritten to HTTP 4318. |
| maxim plugin | plugins/maxim | missing | Third-party observability. Not in `SCOPE.md`. Decide. |
| mocker plugin | plugins/mocker/main.go | partial | `plugins.tov`: `rules` with `model` or `contains` only. Bifrost has conditions (providers, models, regex, request size), weighted responses, latency, probability, priority, default_behavior. |
| jsonparser plugin | plugins/jsonparser | partial | `plugins.tov` JsonParserConfig: `strip_markdown_fences` only. Compare the Bifrost plugin options before claiming parity. |
| compat plugin | plugins/compat (convertparams, dropparams, azure, requestcopy) | missing | P2 (G37). |
| modelcatalogresolver plugin | plugins/modelcatalogresolver | missing | P2. |
| prompts plugin | plugins/prompts | missing | P2. Not in `SCOPE.md`. |
| routing plugin | plugins/routing (complexity classifiers, decision models) | partial | CEL variables and RE2 `matches` (`cel.tov`, `regex.tov`, commit abf4dbb). No decision-model classifier (G36). |
| semanticcache plugin | plugins/semanticcache/main.go:32-61 | partial | `semcache.tov`, with Qdrant and Redis through `vectorstore.tov` (commit d91ef07). The plugin entry is mapped. cache_tool_call_responses and disable_identity_scoping are reported as ignored. |
| circuit-breaker (docs/features/plugins/circuit-breaker.mdx) | docs | done | `health.tov`. Config location differs (c1). |
| header plugin (set_request_headers) | not in Bifrost | done (Raiju-only) | `plugins.tov` (`header`). |
| blocklist plugin | not in Bifrost | done (Raiju-only) | `plugins.tov` (`blocklist`). |
| maxtokens plugin | not in Bifrost | done (Raiju-only) | `plugins.tov` (`maxtokens`). |
| Dynamic plugins (Go shared objects, WASM) | docs/plugins/getting-started.mdx, writing-go-plugin.mdx, writing-wasm-plugin.mdx | missing | Raiju plugins are compiled in (`SCOPE.md` notes). P2. |
| Plugin ordering | docs/plugins/sequencing.mdx | partial | `plugins.tov` `buildChain`: config order. |

## (f) Governance

Bifrost: `docs/features/governance/*.mdx`, `docs/enterprise/*.mdx`, and `handlers/governance.go`. Raiju: `src/governance.tov`, `src/profiles.tov`, `src/rbac.tov`, `src/pricing.tov`, `src/guardrails.tov`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Virtual keys (create, list, update, delete) | features/governance/virtual-keys.mdx | done | `store.tov:924-941`, `governance.tov`. |
| VK key rotation and cooldown | handlers/governance.go (rotate), vk_rotation_cooldown | missing | P2. |
| VK budgets and rate limits per provider config | budget-and-limits.mdx "Provider-Level Governance" | done | `governance.tov:160-172`. |
| VK allowed providers and models | routing.mdx "Provider/Model Restrictions" | done | `governance.tov:160-172`. |
| Budgets (USD, reset durations) | budget-and-limits.mdx | done | `governance.tov:8, 24`, `durationMs`. |
| Budget hierarchy: VK, team, customer | budget-and-limits.mdx | done | `governance.tov:174-186`. |
| Budget hierarchy: business unit, project | enterprise/projects.mdx; teams-business-units-customers.mdx | missing | P2. |
| Budget overrides per VK | handlers/governance.go (budget override) | missing | P2. |
| Rate limits (request and token windows) | budget-and-limits.mdx | done | `governance.tov:115-117`, `governance.tov:189-201`. |
| Model limits (model-level budgets and rate limits, scope system) | features/governance/model-limits.mdx | done | `model_configs` (commit 31f4aaa). |
| Provider-level governance (global) | budget-and-limits.mdx | done | `governance.providers` and `/api/governance/providers` (commit 31f4aaa). |
| Customers | teams-business-units-customers.mdx | done | `store.tov:33`. |
| Teams | teams-business-units-customers.mdx | done | `store.tov:33`. |
| Required headers (global and per profile) | features/governance/required-headers.mdx | done | `governance.tov:86`, `governance.tov:141-146`. |
| Access profiles (reusable permission sets) | enterprise/access-profiles.mdx | partial | `profiles.tov`. No versions, clone, activate or deactivate, role binding, propagate. |
| RBAC (fixed roles) | enterprise/rbac.mdx | partial | `rbac.tov`: admin, editor, viewer, auditor. |
| RBAC (custom roles, permission editor) | handlers/governance.go (rbac roles and permissions) | missing | P2. |
| Data access control (scopes per role) | enterprise/data-access-control.mdx | missing | P2. |
| Users and tokens | enterprise/user-provisioning.mdx (SCIM excluded) | partial | `rbac.tov`, `ops.tov`. Basic and Bearer user tokens. |
| SSO: generic OIDC (PKCE, groups to roles) | enterprise/setting-up-generic-oidc | done | `oidc.tov`. Provider guides (Okta, Entra, Keycloak, Auth0, Zitadel, Google Workspace) are configurations of the same protocol, not verified individually. |
| SSO: Google and GitHub | features/sso-with-google-github.mdx | n/a | Bifrost marks it "Coming soon". |
| SCIM and user provisioning | enterprise/user-provisioning.mdx | out-of-scope | `SCOPE.md` Out: SCIM. |
| Audit logs (hash chain, HMAC, export, verify) | enterprise/audit-logs.mdx | partial | `audit.tov`. Missing: archive to object storage, retention, omit-IP option, per-entity routes. |
| Pricing overrides | governance.pricing_overrides; docs/providers/custom-pricing.mdx | missing | P1 (G21). |
| Cost tracking (price table) | docs/providers/custom-pricing.mdx; framework/modelcatalog | partial | Built-in datasheet, overrides and sync (see d2). Models outside it cost 0, and budgets skip them with a one-time warning (`gateway.tov`, `unpriced`). No refusal. |
| Complexity analyzer config | governance.complexity_analyzer_config; docs/features/complexity-router.mdx | partial | `complexity.tov`, config only. |
| Adaptive load balancing (weights, held keys, incidents, API) | enterprise/adaptive-load-balancing.mdx | partial | `health.tov`: weights. No held-keys or incidents API. |
| Circuit breaker policies (API) | enterprise/circuit-breaker.mdx | partial | `health.tov`. Config only. |
| Routing rules (CEL) | providers/routing-rules.mdx | done | `cel.tov` with Bifrost's variables, and RE2 `matches` (`regex.tov`, commit abf4dbb). |
| Projects | enterprise/projects.mdx | missing | P2. |
| Prompt deployments | enterprise/prompt-deployments.mdx | missing | P2. Not in `SCOPE.md`. |
| Alerts on budget and rate-limit usage | enterprise/alerting/alert-rules.mdx (budget_usage_percent, rate_limit_*_usage_percent, cel_expression) | done | `alertapi.tov` and `alerts.tov`: CEL rules over budget and rate-limit usage (commit 8e98ea5). |
| Governance per request: x-bf-customer-id | budget-and-limits.mdx | missing | P2. |

## (g) MCP

Bifrost: `docs/mcp/*.mdx`, `handlers/mcp*.go`, `core/mcp`, `config.schema.json` `mcp`. Raiju: `src/mcp.tov`, `src/mcpauth.tov`, `src/mcpserver.tov`, `src/agent.tov`, `src/vmcp.tov`, `src/ops.tov`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| MCP client over HTTP (streamable) | mcp/connecting-to-servers.mdx | done | `mcp.tov`. |
| MCP client over SSE | mcp/connections.mdx | done | `mcp.tov` ("sse" uses the POST transport). |
| MCP client over stdio | mcp/connections.mdx | done | `mcp.tov` (`stdio_config`), one server per worker (SCOPE). |
| MCP client inprocess and OpenAPI-defined servers | mcp/openapi-servers.mdx | missing | P2. |
| Auth: bearer and static headers | mcp/auth | done | `mcpauth.tov`. |
| Auth: OAuth client credentials and refresh token | mcp/auth | done | `mcpauth.tov` (SCOPE: L36). |
| Auth: per-user OAuth (authorization code, consent) | mcp/gateway-auth.mdx; handlers/mcpoauth2*.go | missing | P2. |
| Auth: per-user headers | handlers/mcpheaders.go | missing | P2. |
| Auth: token exchange | mcp/auth; mcp_client_config.auth_type | missing | P2. |
| Tool filtering: per client (`tools_to_execute`) | mcp/filtering.mdx Level 1 | done | `mcp.tov:17`. |
| Tool filtering: request headers (include clients) | mcp/filtering.mdx Level 2 | partial | x-bf-mcp-include-clients only. Missing: x-bf-mcp-include-tools. |
| Tool filtering: virtual key allow-lists | mcp/filtering.mdx Level 3 | partial | Access profiles `mcp_tools` (`profiles.tov`, `config.tov`). |
| Tool filtering: tool groups | config.schema.json mcp.tool_groups (no docs page) | missing | P2. |
| Tool execution endpoint | handlers/mcpinference.go | done | `server.tov:220`. |
| Agent mode (gateway runs allowed tool calls) | mcp/agent-mode.mdx | done | `agent.tov`; `gateway.tov:456-457`. Per-client config differs (client-level `mcp_auto_execute`). |
| Tool execution timeout | mcp/tool-execution.mdx | partial | `mcp.tool_execution_timeout_seconds` (`config.tov`). |
| Gateway as MCP server (POST /mcp) | mcp/overview.mdx; handlers/mcpserver.go | done | `ops.tov:645-700`, `mcpserver.tov`. |
| Gateway as MCP server (SSE GET) | handlers/mcpserver.go | missing | P2. |
| Virtual MCPs (named tool sets, renamed tools) | mcp/virtual-mcps.mdx | done | `vmcp.tov` (config-defined), `/mcp/{name}`. |
| Virtual MCPs management API | handlers/virtualmcp.go | done | CRUD and virtual-key attach and detach at `/api/mcp/virtual-mcps` (`mcpapi.tov`, commit 5c2c8af). |
| MCP sessions (list, reauth, revoke) | mcp/sessions.mdx | missing | P2. |
| MCP logs (/api/mcp-logs) | handlers/logging.go | missing | P2. |
| MCP client management API | handlers/mcp.go | partial | CRUD, reconnect and refresh-tools (`mcpapi.tov`, commit 5c2c8af). Verify, reauthorize and OAuth routes answer 501. |
| MCP OpenAPI import and preview | handlers/mcpopenapi.go | missing | P2. |
| MCP tool sync interval (periodic re-list) | mcp_client_config.tool_sync_interval | missing | P2. |
| MCP as an OAuth authorization server for MCP clients | mcp/gateway-auth.mdx; handlers/mcpoauth2issuance.go | missing | P2. |
| MCP guardrails (tool-call guard) | enterprise/guardrails.mdx "MCP Guardrails" | missing | P2. Grep finds no MCP reference in `guardrails.tov` or `guardrail_providers.tov`. |
| MCP code mode | mcp/code-mode.mdx | out-of-scope | `SCOPE.md` Out: MCP code mode. |
| MCP SSRF guard (require_public_target) | mcp_client_config.require_public_target | missing | P2. |
| MCP pricing per tool | mcp_client_config.tool_pricing | missing | P2. |

## (h) Observability

Bifrost: `plugins/telemetry/main.go` (metric definitions at lines 420-694), `core/schemas/enrichment.go` (label dimensions at lines 53-92), `docs/features/observability/*.mdx`. Raiju: `src/metrics.tov`, `src/gateway.tov` (call sites), `src/logstore.tov`, `src/otel.tov`, `src/exporters.tov`, `src/exports.tov`, `src/alerts.tov`.

### h1. Metrics

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| bifrost_upstream_requests_total | telemetry/main.go:459 | done | `gateway.tov`, with the enrichment label set (`metrics.tov`, commit 202c6e6). |
| bifrost_upstream_latency_seconds | telemetry/main.go:467 | done | `gateway.tov`, with `is_success` and the enrichment labels (commit 202c6e6). |
| bifrost_success_requests_total | telemetry/main.go:505 | done | `metrics.tov` (commit 202c6e6). |
| bifrost_error_requests_total (status_code, error_type) | telemetry/main.go:517 | done | `metrics.tov`, with status_code and error_type (commit 202c6e6). |
| bifrost_input_tokens_total | telemetry/main.go:525 | done | `gateway.tov:982`. |
| bifrost_output_tokens_total | telemetry/main.go:533 | done | `gateway.tov:983`. |
| bifrost_cache_hits_total (cache_type) | telemetry/main.go:541 | done | `metrics.tov` `cache_type` label (commit 202c6e6). |
| bifrost_cache_read_input_tokens_total, bifrost_cache_write_input_tokens_total (_5m, _1h) | telemetry/main.go:551-575 | done | `metrics.tov` (commit 202c6e6). |
| bifrost_cost_total | telemetry/main.go:583 | done | `gateway.tov:984`. Values depend on the price table (f). |
| bifrost_routing_embedding_requests_total, bifrost_routing_embedding_cost_total, bifrost_routing_llm_requests_total, bifrost_routing_llm_cost_total | telemetry/main.go:598-627 | missing | P2. |
| bifrost_stream_first_token_latency_seconds, bifrost_stream_inter_token_latency_seconds | telemetry/main.go:635-644 | done | `metrics.tov` (commit 202c6e6). |
| bifrost_request_retries | telemetry/main.go:653 | done | `gateway.tov` records the retries spent on each provider. |
| bifrost_key_rotation_events_total | telemetry/main.go:667 | missing | P2. |
| bifrost_active_requests | telemetry/main.go:675 | missing | P2. |
| bifrost_provider_key_up | telemetry/main.go:683 | missing | P2. |
| bifrost_mcp_client_operation_duration_seconds | telemetry/main.go:694 | missing | P2. |
| bifrost_overhead_latency_microseconds | telemetry/main.go:479 | done | `metrics.tov`, with labels (commit 202c6e6). |
| bifrost_overhead_component_microseconds | telemetry/main.go:496 | missing | P2. |
| http_requests_total, http_request_duration_seconds, http_request_size_bytes, http_response_size_bytes (path, method, status) | telemetry/main.go:420-449 | done | Recorded by the front ends (`front.tov:70-75`, `server.tov:124`, commit 0b03e53). |
| bifrost_request_duration_seconds | not defined by the Bifrost telemetry plugin | done (Raiju-only) | `gateway.tov:1021`. |
| raiju_realtime_sessions, raiju_mcp_tool_calls_total, raiju_guardrail_checks_total, raiju_guardrail_findings_total | not in Bifrost | done (Raiju-only) | `realtime.tov`, `gateway.tov:483`, `776`, `1095`, `1118`, `1226`. |
| Label dimensions: virtual_key_name, team_name, customer_name, selected_key_name, routing_rule_name, complexity_tier, alias, app, fallback_index, and the id variants | core/schemas/enrichment.go:53-92 (MetricSafeEnrichmentDimNames) | missing | P1 (G18). Raiju's labels are provider, model and status only (`metrics.tov:167-171`). |
| Custom labels: x-bf-dim-*, x-bf-prom-*, client.prometheus_labels | lib/ctx.go:443-449; config.schema client.prometheus_labels | missing | P2. |
| Default HTTP metric labels and the telemetry push gateway | telemetry/main.go; docs/features/telemetry.mdx | missing | P2. |

### h2. Logs and traces

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Request log store (queryable) | plugins/logging; handlers/logging.go | partial | `logstore.tov`: JSONL files and an in-memory index. Per worker (README "Known gaps"). |
| Content logging: global switch | client.disable_content_logging | done | `logs_store.content_logging` and `client.disable_content_logging` (`gateway.tov:1503-1504`, commit 12757de). |
| Content logging: per request | x-bf-disable-content-logging | done | `x-bf-disable-content-logging` (`gateway.tov:1503`, commit 12757de). |
| Log retention (days) | logs_store.retention_days; enterprise/log-exports.mdx | done | `logstore.tov`. |
| Log sinks: Datadog, Splunk HEC, Elasticsearch, generic HTTP | docs/features/observability/datadog.mdx, splunk.mdx | done | `exporters.tov` (SCOPE). |
| Log sinks: BigQuery, Kafka, Pub/Sub | docs/features/observability/bigquery.mdx, kafka.mdx, pubsub.mdx | missing | P2. |
| Log sink: Maxim | docs/features/observability/maxim.mdx; plugins/maxim | missing | P2. Not in `SCOPE.md`. |
| Log exports to S3 and GCS | enterprise/log-exports.mdx | done | `exports.tov`. |
| Log exports: Parquet payloads, retention policy, redaction on export | enterprise/log-exports.mdx | partial | `exports.tov` writes JSONL only. |
| OpenTelemetry traces | plugins/otel; features/otel.mdx | partial | `otel.tov`: OTLP HTTP, sampling, batching, traceparent (commit 0d269dd). No gRPC. |
| OpenTelemetry metrics export | plugins/otel/metrics.go | partial | OTLP/HTTP JSON push of four families: upstream requests and latency, overhead and sessions (`otel_metrics.tov`, commit abf4dbb). No gRPC. |
| Latency breakdown (overhead components) | features/observability/latency-breakdown.mdx | partial | `x-bf-overhead-us` and `bifrost_overhead_latency_microseconds` only. |
| Dashboards, histograms and rankings (management API) | handlers/logging.go | missing | P2. |
| Alerts: webhook and Slack | enterprise/alerting | done | `alerts.tov` (channel type is webhook or slack). |
| Alerts: Microsoft Teams and PagerDuty channels | enterprise/alerting/alert-channels.mdx | done | `alerts.tov:41-51` (commit abf4dbb). |
| Alert metrics: budget and rate-limit usage percent, CEL scoping | enterprise/alerting/alert-rules.mdx | done | CEL rules over budget and rate-limit usage (`alertapi.tov`, commit 8e98ea5). |

## (i) Enterprise

Bifrost: `docs/enterprise/*.mdx`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Audit logs | enterprise/audit-logs.mdx | partial | `audit.tov`. See f. |
| RBAC | enterprise/rbac.mdx | partial | `rbac.tov`. Fixed roles. |
| Custom roles and data access control | enterprise/data-access-control.mdx | missing | P2. |
| SSO: generic OIDC | enterprise/setting-up-generic-oidc | done | `oidc.tov`. |
| SSO: Google, GitHub | features/sso-with-google-github.mdx ("Coming soon") | n/a | Not GA upstream. |
| SCIM and user provisioning | enterprise/user-provisioning.mdx | out-of-scope | `SCOPE.md` Out: SCIM. |
| Access profiles | enterprise/access-profiles.mdx | partial | `profiles.tov`. See f. |
| Projects | enterprise/projects.mdx | missing | P2. |
| Teams, business units, customers | enterprise/teams-business-units-customers.mdx | partial | Teams and customers done. Business units missing. |
| Prompt deployments | enterprise/prompt-deployments.mdx | missing | P2. Not in `SCOPE.md`. |
| Virtual MCPs, enterprise access | enterprise/virtual-mcps.mdx | partial | `vmcp.tov`. Config and management API. No access-profile or project scoping. |
| Guardrails: built-in PII detectors | enterprise/guardrails/custom-regex.mdx (PII template) | partial | `guardrails.tov`: email, phone, ssn, credit_card, ipv4, api_key, aws_key, jwt, private_key. Matching uses literal strings for custom entries, not regex. |
| Guardrails: secrets detection (222 Gitleaks rules) | enterprise/guardrails/secrets-detection.mdx | partial | Raiju covers api_key, aws_key, jwt and private_key only. |
| Guardrails: custom regex | enterprise/guardrails/custom-regex.mdx | partial | `guardrails.tov` custom: literal strings only. |
| Guardrails: redaction modes (runtime, logs only, reversible reveal) | enterprise/guardrails/redaction.mdx | partial | `guardrails.tov`: redact, block, log. No reversible reveal. |
| Guardrails: prompt guardrails (LLM judge) | enterprise/guardrails/prompt-guardrails.mdx | missing | P2. |
| Guardrails: Presidio, Azure Language PII, Google Model Armor, CrowdStrike AIDR | enterprise/guardrails.mdx | missing | P2. |
| Guardrails: AWS Bedrock Guardrails | integrations/guardrails/aws-bedrock | done | `guardrail_providers.tov`. |
| Guardrails: Azure AI Content Safety | integrations/guardrails/azure-content-safety | done | `guardrail_providers.tov`. |
| Guardrails: Patronus, generic webhook | not in Bifrost docs as listed here | done (Raiju-only) | `guardrail_providers.tov`. |
| Guardrails: streaming output | enterprise/guardrails.mdx "Streaming Output Guardrails" | partial | Output guard on streamed responses (`gateway.tov:1226`). |
| Guardrails: MCP tool-call guard | enterprise/guardrails.mdx "MCP Guardrails" | missing | P2. |
| Secret managers: Vault KV v2, AWS Secrets Manager | enterprise/secret-management.mdx | done | `secrets.tov` (SCOPE). |
| Clustering | enterprise/clustering.mdx | partial | `cluster.tov`: static peers and HMAC-signed sync. No discovery (Kubernetes, DNS, Consul, etcd, mDNS, UDP), no leader election, no broker mode. |
| Adaptive load balancing | enterprise/adaptive-load-balancing.mdx | partial | See f. |
| Circuit breakers | enterprise/circuit-breaker.mdx | partial | See f. |
| Auth proxies: AWS ALB, Cloudflare ZTNA, generic proxy | enterprise/auth-proxy/*.mdx | missing | P2. |
| InVPC deployments | enterprise/invpc-deployments.mdx | n/a | Managed offering. Raiju ships Docker, Helm and Terraform (SCOPE). |
| Self-hosted deployment artifacts | deploy/ (Bifrost helm-charts, terraform) | done | Raiju `deploy/`, `Dockerfile`, `docker-compose.yml` (SCOPE). |
| Warp (log-aware assistant) | features/warp.mdx | missing | P2. Not in `SCOPE.md`. |
| Skills marketplace | features/skills-repository.mdx | missing | P2. Not in `SCOPE.md`. |
| Webhooks (signed deliveries, retries, redeliver) | features/webhooks.mdx | missing | P2. Not in `SCOPE.md`. |
| Agent gateway (A2A) | features/agent-gateway/* | missing | P2. Not in `SCOPE.md`. |
| Feature flags | handlers/featureflags.go | missing | P2. |
| Encryption of stored keys | encryption_key | missing | P2. |

## Gaps

Ordered by importance. Each gap says what to build and where Bifrost defines it. "Ledger task" means it can become a row in `LEDGER.md`.

### P0

- **G1. Async poll path and status names.** Build `GET /v1/async/<op>/{job_id}` for every submitted op, returning the same job JSON. Keep `GET /v1/async/jobs/{id}` as an alias. Use Bifrost's status names: pending, processing, completed, failed (`core/schemas/async.go:18-21`). Add the missing ops: audio/transcriptions, images/edits, images/variations, ocr, rerank. Bifrost: `transports/bifrost-http/handlers/asyncinference.go`, `docs/features/async-inference.mdx` "Supported Endpoints". Raiju: `src/server.tov:203`, `src/jobs.tov:22`, `162-170`. Ledger task. **Status: Done** (commit 49ac636). All listed ops and Bifrost poll paths are in place.

- **G2. Inference auth default and config keys.** Read `client.enforce_auth_on_inference` and top-level `auth_config.is_enabled`, and default to true for new configs (Bifrost's schema says true on new deployments and when the first admin is created; an explicit false opts out). Today Raiju's gate defaults to false (`src/governance.tov:85`), so a Bifrost config without the key lets anonymous inference through. Decide whether existing configs with the key omitted keep open behaviour. Bifrost: `transports/config.schema.json` (`client.enforce_auth_on_inference`, `auth_config`). Ledger task, with a decision. **Status: Done.** `auth_config.is_enabled` and `disable_auth_on_inference` are honoured. The gate now defaults to on when credentials exist (`src/governance.tov:121`). Commit 32da2e6.

- **G3. guardrails_config is ignored.** Bifrost's `guardrails_config` (`guardrail_rules`, `guardrail_providers`) is not read; Raiju reads `guardrails`. A Bifrost config therefore runs with no guardrails and no warning. Implement the Bifrost shape, or at least fail loudly. Bifrost: `transports/config.schema.json` `$defs/guardrails_config`, `docs/enterprise/guardrails.mdx`. Raiju: `src/config.tov` `GuardrailsConfig`. Ledger task. **Status: Done** (commit 0c999ff). Read through `src/guardrails_compat.tov`.

- **G4. Budgets and rate limits do not enforce for models outside the built-in price table.** `pricing.tov` covers 15 models. `cost()` returns 0 for any other model (`src/pricing.tov:56-58`), so a budget on those models never runs down. Add a Bifrost-compatible price catalog (default datasheet `framework/modelcatalog/config.go:109`, `pricing_url` and `pricing_sync_interval` in `config.schema.json` framework.pricing), plus `governance.pricing_overrides` (`docs/providers/custom-pricing.mdx`). Until then, refuse or warn when a budgeted request hits an unpriced model. Ledger task. **Status: Partial.** Built-in datasheet and opt-in sync are in place (commit 0c999ff). Models outside the datasheet still cost 0 and skip budgets. The only response is a one-time warning (`src/gateway.tov`, `unpriced`). No refusal.

- **G5. OpenAI SDK route is incomplete.** Mount `/openai/v1/audio/*`, `/openai/v1/images/*`, `/openai/v1/files*`, `/openai/v1/batches*`, `/openai/v1/responses/{id}` (GET, DELETE, cancel, input_items), `/openai/v1/responses/input_tokens`, `/openai/v1/responses/compact`, `/openai/v1/models/{id}`, and the deployment variants for embeddings, images, audio, responses and models. `compatPath` should map `/openai/v1/` onto the `/v1/` routes, as it already does for `/litellm/` and `/langchain/`. Bifrost: `transports/bifrost-http/integrations/openai.go` (`CreateOpenAIRouteConfigs`, paths `/openai/v1/...`), `docs/openapi/openapi.json`. Raiju: `src/server.tov:167-202`, `171-194`, `src/media.tov:23-41`. Ledger task. **Status: Done.** `/openai/deployments/{d}/*` for chat (streaming too), completions, embeddings, responses (input_tokens, compact), images (generations, edits, variations) and audio; the models variant is not registered by Bifrost either.

- **G6. Bedrock SDK streaming routes.** Add `POST /bedrock/model/{id}/converse-stream` and `/invoke-with-response-stream`, with event-stream framing. Reuse `bedrock.tov` `streamRequest` (`src/providers/index.tov:70`). Today `bedrockModel` returns 404 for any action other than converse or invoke (`src/native.tov:234`). Bifrost: `transports/bifrost-http/integrations/bedrock.go:68-125` and `118-200`. Ledger task. **Status: Done** (commit 0b03e53).

- **G7. Config sections that load silently under a different name, or not at all.** Bifrost names and Raiju names differ for these, and Raiju ignores Bifrost's name without a warning: **Status: Partial.** Mapped: alerting, audit_logs, cluster_config, circuit_breaker_config, load_balancer_config, framework.pricing, mcp.virtual_mcps, and the otel and semanticcache plugin entries (commits 0c999ff, 0d269dd, d91ef07, abf4dbb). The logging, telemetry and governance plugins map onto the client section; routing, compat and prompts load with a note for each setting Raiju doesn't implement (`src/config_compat.tov` mapPlugins). **Status now: Done** for config loading; the compat and prompts features themselves are G37 and G46.
  - `alerting` (Raiju: `alerts`), `audit_logs` (Raiju: `audit`), `cluster_config` (Raiju: `cluster`), `circuit_breaker_config` and `load_balancer_config` (Raiju: `health`), `framework.pricing` (Raiju: `pricing`), `mcp.virtual_mcps` (Raiju: top-level `virtual_mcps`), and `plugins[]` entries named `semanticcache`, `otel`, `logging`, `telemetry`, `governance`, `compat`, `routing`, `prompts` (only `header`, `mocker`, `jsonparser`, `blocklist` and `maxtokens` load).
  - Build a loader that maps the Bifrost names, and that reports every unrecognised key at startup. Bifrost: `transports/config.schema.json`. Raiju: `src/config.tov` loaders, `src/plugins.tov:347-372`. Ledger task.

### P1

- **G8. Cohere SDK routes.** Add `/cohere/v2/chat`, `/cohere/v2/embed`, `/cohere/v2/rerank`, `/cohere/v1/tokenize`, and the litellm and langchain variants. Bifrost: `transports/bifrost-http/integrations/cohere.go:73-200`. Raiju: `src/providers/cohere.tov` has the conversions; the routes are missing from `src/server.tov`. Ledger task. **Status: Done** (commit 0b03e53).

- **G9. `/pydanticai/*` prefix.** Add it to `compatPath` (`src/server.tov:171-175`). Bifrost: `transports/bifrost-http/integrations/pydanticai.go:25-37`. One-line change. Ledger task. **Status: Done** (commit 896b797).

- **G10. Anthropic SDK: models, batches, files.** Add `GET /anthropic/v1/models`, `/anthropic/v1/messages/batches` (create, list, get, cancel, results), `/anthropic/v1/files` (upload, list, get, content, delete). Bifrost: `transports/bifrost-http/integrations/anthropic.go` lines 321-330, 1078-1300, 1468-1700. Ledger task. **Status: Done** (commits 6e05a2d, c363369). Models, batches (including results) and files are routed in `src/anthropic_batch.tov`.

- **G11. GenAI SDK: cross-provider and missing routes.** Convert GenAI requests to the target provider, not only Gemini (`src/native.tov:223`). Add `GET /genai/v1beta/models` and `/models/{m}`, the operations route, files (with the upload route), batches, cachedContents, and `/genai/v1/rank`. Bifrost: `transports/bifrost-http/integrations/genai.go` (`CreateGenAIRouteConfigs`, file, batch and cached routes, lines 45-1395). Ledger task. **Status: Done** (commits 0b03e53, 6f3cbcd). generateContent, streaming, embeddings, countTokens, models, files (with resumable upload), batches, cachedContents, operations, :predict and /genai/v1/rank. Cached contents and operations are Gemini-only; non-Gemini batches convert generateContent requests only.

- **G12. Bedrock SDK: cross-provider, count-tokens and rerank.** Accept non-Bedrock targets by converting Converse to chat and back (`src/native.tov:240` rejects them today). Add `/bedrock/model/{id}/count-tokens` and `/bedrock/rerank`. Bifrost: `transports/bifrost-http/integrations/bedrock.go:287-360` and the request converters. Ledger task. **Status: Done** (commits 0b03e53 and the Bedrock rerank commit). Converse and invoke to any provider with streaming; count-tokens calls Bedrock's API for Bedrock targets (estimate elsewhere, marked); `/bedrock/rerank` and Bedrock as a /v1/rerank provider.

- **G13. Responses lifecycle and related routes.** Implement retrieve, delete, cancel and input_items for `/v1/responses/{id}` (OpenAI first), plus `/v1/responses/input_tokens` and `/v1/responses/compact`. Bifrost: `transports/bifrost-http/handlers/inference.go` (responses routes) and `integrations/openai.go:763-953`. Raiju: `src/server.tov:215`, `src/native.tov:187`. Ledger task. **Status: Done** (commit 12757de).

- **G14. Model retrieve.** Add `GET /v1/models/{model}` and `/openai/v1/models/{model}`. Bifrost: `transports/bifrost-http/handlers/inference.go` (modelRetrieve), `integrations/openai.go:1770-1772`. Raiju: `src/server.tov:202`. Ledger task. **Status: Done** (commit 896b797). The answer is a stub (see the a1 row for `GET /v1/models/{model}`).

- **G15. Realtime WebRTC, client secrets and sessions.** Add `POST /v1/realtime/calls`, `/v1/realtime/client_secrets`, `/v1/realtime/sessions`, and the `/openai/` variants. Bifrost: `transports/bifrost-http/handlers/webrtcrealtime.go`, `realtime_client_secrets.go`, openapi. Raiju: `src/realtime.tov` (WebSocket only). Ledger task. **Status: Done** (commit 12757de).

- **G16. Files, batches and media for non-OpenAI providers.** `media.tov:249` rejects providers that are not OpenAI-format or Azure. Add native implementations or pass-through for Anthropic (files, batches), Gemini (speech, STT, images, files, batches), Vertex (images, batches, files), Bedrock (images, files, batches), and Cohere (files). Also add `GET /v1/batches/{id}/results`. Bifrost: `core/providers/<name>/` (BatchCreate, FileUpload, etc.) and `docs/providers/supported-providers/*.mdx`. Ledger task (one per provider). **Status: Partial.** Done: Anthropic and Gemini files, batches and media; Gemini STT; Vertex and Bedrock images; `GET /v1/batches/{id}/results`. Remaining: Vertex batches and files (GCS) and Bedrock batches and files (S3); Cohere has none in Bifrost either.

- **G17. Bifrost response header contract.** Send `x-bifrost-provider`, `x-bifrost-original-model`, `x-bifrost-resolved-model`, `x-bifrost-request-type`, `x-bifrost-fallback-index`, `x-bifrost-latency-ms`, `x-bifrost-upstream-latency-ms`, and the cache headers (`x-bifrost-cache-hit`, `-hit-type`, `-similarity`, `-threshold`, and the rest). Add `x-bifrost-error-type` and `x-bifrost-retry-after-ms`. Add `Access-Control-Expose-Headers` for these. Decide whether to emit `extra_fields` in the body or the headers (`client.extra_fields_placement`). Bifrost: `transports/bifrost-http/lib/responseheaders.go:23-132` and `ExposedResponseHeaders`. Raiju: `src/gateway.tov:886-1008`, `src/server.tov:148-157`. Ledger task. **Status: Partial.** Most headers are sent (commit abf4a31). Remaining: x-bifrost-retry-after-ms; the cache headers -id, -hit-latency-ms, -provider-used, -model-used and -input-tokens; five routing-info headers; pricing and converted request type; dropped-compat and passthrough-path headers; and extra_fields header placement.

- **G18. Metric names and label dimensions.** Add `bifrost_success_requests_total`, `bifrost_error_requests_total` (status_code, error_type), `bifrost_stream_first_token_latency_seconds`, `bifrost_stream_inter_token_latency_seconds`, `bifrost_cache_read_input_tokens_total` and `_write_`, and the `http_*` family. Add the enrichment label set (`virtual_key_name`, `team_name`, `customer_name`, `selected_key_name`, `routing_rule_name`, `complexity_tier`, `alias`, `app`, `fallback_index` and the id variants). Keep `raiju_*` as extras. Bifrost: `plugins/telemetry/main.go:420-694`, `core/schemas/enrichment.go:53-92`. Raiju: `src/gateway.tov` call sites, `src/metrics.tov:167-171`. Ledger task. **Status: Partial.** Families and labels done, plus active requests, provider key up, key rotation and MCP duration. Remaining: the routing-classifier families (Raiju's complexity router is heuristic) and overhead components (off by default in Bifrost).

- **G19. Reasoning parameters.** Map `reasoning_effort` and `max_completion_tokens` to Anthropic thinking budgets, Gemini thinking config, and Bedrock Nova settings. Today these fields are dropped for non-OpenAI providers (no `reasoning_effort` handling in `src/`). Bifrost: `docs/providers/reasoning.mdx` ("Provider-Specific Conversions", "Effort vs. Max Tokens"). Ledger task. **Status: Done** (commit ac4bf4f).

- **G20. Per-request content logging control.** Read `x-bf-disable-content-logging` and `client.disable_content_logging` (both are missing), and apply them in `src/logstore.tov`. Bifrost: `transports/bifrost-http/lib/ctx.go:743`, `config.schema.json` client. Ledger task. **Status: Done** (commit 12757de).

- **G21. Governance objects missing from the management API and config.** `model_configs` (per-model budgets and limits), provider-level governance (`governance.providers`), and `pricing_overrides`. Add the Bifrost routes: `/api/governance/model-configs`, `/api/governance/providers`, `/api/governance/pricing-overrides`. Bifrost: `transports/bifrost-http/handlers/governance.go`, `config.schema.json` governance. Ledger task. **Status: Done** (commit 31f4aaa).

- **G22. MCP client and virtual MCP management.** Add `/api/mcp/client` CRUD, reconnect, refresh-tools and the verification routes, and `/api/mcp/virtual-mcps` CRUD with virtual-key attach and detach. Accept `mcp.client_configs` fields that Raiju lacks: `endpoint_slug`, `allow_by_default`, `disabled`, `tools_to_auto_execute` (per client), `tool_sync_interval`, `tls_config`. Bifrost: `transports/bifrost-http/handlers/mcp.go`, `handlers/virtualmcp.go`, `config.schema.json` `mcp_client_config`. Raiju: `src/mcp.tov:12-23`, `src/ops.tov:645-690`. Ledger task. **Status: Partial.** Client and virtual MCP CRUD, reconnect, refresh-tools and attach or detach are done (commit 5c2c8af). Remaining: verify-*, reauthorize, reregister, initiate-verification, complete-oauth and openapi-spec return 501. `tool_sync_interval` is stored but never re-lists tools. `is_ping_available` and `needs_session_stickiness` are not accepted.

- **G23. Routing CEL variables and regex.** Add the Bifrost variables (`virtual_key_name`, `virtual_key_id`, `team_name`, `team_id`, `customer_name`, `customer_id`, `request_type` values) and `params`. Bifrost's `matches` takes regular expressions. Rules written for Bifrost that use `*_name` currently fail to compile (`src/cel.tov:397`, IDENTS at `cel.tov:78`). Bifrost: `docs/providers/routing-rules.mdx` "Available Variables". Ledger task. **Status: Done** (commit abf4dbb).

- **G24. Azure Entra ID authentication.** Accept `client_id`, `client_secret`, `tenant_id` and `scopes` on Azure keys, and obtain tokens. Bifrost: `transports/config.schema.json` `azure_key`, `docs/providers/supported-providers/azure.mdx`. Raiju: `src/config.tov` AzureKeyConfig (API key only). Ledger task. **Status: Done** (commit 6aeb7f2).

- **G25. Bedrock IAM and endpoints.** Support `role_arn` with `external_id` and `session_name` (assume-role), inference-profile `arn`, batch S3 settings, and `use_openai_endpoints`. Add the `bedrock_mantle` provider (G27). Bifrost: `transports/config.schema.json` `bedrock_key`, `docs/providers/supported-providers/bedrock-mantle.mdx`. Raiju: `src/config.tov` BedrockKeyConfig. Ledger task. **Status: Partial.** role_arn, external_id, session_name, inference-profile arn and use_openai_endpoints are done. Remaining: batch role and S3 settings (with G16's Bedrock batches).

- **G26. TLS and network options.** Support `insecure_skip_verify` and `ca_cert_pem` per provider (and `proxy_config.ca_cert_pem`). These matter for private endpoints (vLLM, Ollama and in-house gateways). Bifrost: `transports/config.schema.json` `network_config`, `proxy_config`. Raiju: `src/config.tov` NetworkConfig, `providers/types.tov`. Confirm first whether Tov's fetch can take a CA bundle. Ledger task. **Status: Done** (commit b66cf96).

- **G27. Bedrock Mantle provider.** Add `bedrock_mantle` (OpenAI-compatible Bedrock endpoint, SigV4). Bifrost: `core/providers/bedrockmantle/`, `docs/providers/supported-providers/bedrock-mantle.mdx`. Ledger task. **Status: Done.** `bedrock_mantle` with OpenAI-family and Anthropic-family models (Messages). Remaining nice-to-haves: a Mantle model list and Claude count tokens.

- **G28. Rerank semantics.** For providers with a native rerank (vLLM, Bedrock, Cloudflare), call it. For the rest, return an error rather than a BM25 ranking, so clients do not get different results silently. Bifrost: `core/providers/vllm/`, `bedrock/`, `cloudflare/` (Rerank), `docs/providers/supported-providers/vllm.mdx`. Raiju: `src/extras.tov:27-55`. Ledger task. **Status: Done** (commit 12757de).

- **G29. OpenTelemetry metrics and signal options.** Add metrics export, gRPC, per-signal headers, and span filters. Bifrost: `plugins/otel/main.go:90-200` (config), `metrics.go`, `grpc.go`. Raiju: `src/otel.tov` (traces only). Ledger task. **Status: Partial.** Plugin options, metrics push and per-signal headers are done (commits 0d269dd and abf4dbb). Remaining: the gRPC transport. Collector 4317 is rewritten to HTTP 4318.

- **G30. Semantic cache config and backends.** Accept Bifrost's `semanticcache` plugin entry (`plugins[]`) with `dimension`, `vector_store_namespace`, `cache_tool_call_responses`, `disable_identity_scoping`. Add at least one external vector store (Redis, Qdrant, Weaviate or Pinecone). Bifrost: `plugins/semanticcache/main.go:32-61`, `docs/integrations/vector-databases/*.mdx`. Raiju: `src/semcache.tov` (in-process only). Ledger task. **Status: Done.** Qdrant, Redis, Weaviate, Pinecone and chromem (in-process, file-backed) stores; dimension, vector_store_namespace, cache_tool_call_responses and disable_identity_scoping (entries are scoped by virtual key by default, as Bifrost).

- **G31. Alert channels and metrics.** Add Teams and PagerDuty channels, and budget and rate-limit usage percent metrics. Bifrost: `docs/enterprise/alerting/alert-channels.mdx`, `alert-rules.mdx`. Raiju: `src/alerts.tov:6, 22` (`error_rate`, `p95_latency_ms`, `avg_latency_ms`, `requests`, `cost`, `budget_used`, `breaker_open`; channels `webhook`, `slack`). Ledger task. **Status: Done** (commits abf4dbb and 8e98ea5).

- **G32. SCOPE.md overstates parity.** Change these rows to partial with the caveats above: OpenAI SDK route, Bedrock SDK route, Google GenAI SDK route, Anthropic SDK route, Audio, Images, Files and batches, Realtime (WebSocket only), config.json compatibility, Prometheus metrics, Azure OpenAI (Entra), and Multi-core workers (metrics and logs per worker). Raiju: `SCOPE.md`. Doc task (not edited here). **Status: Open.** SCOPE.md was not updated after the waves, so several rows are out of date. For example, the Anthropic SDK row still says there are no models, batches or files routes. This re-audit edits only docs/parity.md, so SCOPE.md is left for a doc task.

- **G33. Count-token accuracy labelling.** Count tokens are estimated for most providers (`"exact": false`). Make this visible in the API docs and the SCOPE entry, or add provider-side counting where Bifrost has it (Bedrock count-tokens, Fireworks, SGL, Vertex). Bifrost: `docs/providers/supported-providers/*.mdx` "Count Tokens" rows. Raiju: `src/extras.tov:57-93`. Doc and ledger task. **Status: Partial.** Estimates are marked `"exact": false` (`src/extras.tov:69`). SCOPE.md still lists count tokens as done with no caveat. Bedrock count tokens are also an estimate.

### P2

- **G34. Direct-key bypass decision.** Bifrost's docs say direct-key bypass was removed in v1.5, but `main` still has `x-bf-direct-key` and `allow_direct_keys` (`transports/bifrost-http/lib/ctx.go:59-60, 894`). Confirm the target Bifrost version. If it is needed, implement `x-bf-direct-key` gated by `client.allow_direct_keys`. Otherwise warn at startup when the key is set. Raiju parses the key and does nothing (`src/config.tov`). **Status: Done** (commit cbd6ad3). Implemented, gated by `client.allow_direct_keys`.

- **G35. Passthrough routes.** `/openai_passthrough`, `/anthropic_passthrough`, `/azure_passthrough`, `/bedrock_passthrough`, `/genai_passthrough`, `/chatgpt_passthrough`, `/runware_passthrough`. Bifrost: `transports/bifrost-http/integrations/passthrough.go:184-261`. Not in `SCOPE.md`. **Status: Partial** (commit 6b82d47). Six prefixes are done. Remaining: `/runware_passthrough`.

- **G36. Decisions API and typesafe provider.** `/v1/decisions`, `/openai/v1/decisions`, `/typesafe/v1/systemone`, `/typesafe/v1/models`, and a decision-model complexity classifier (Laya, Nimble). Bifrost: `transports/bifrost-http/integrations/typesafe.go`, `docs/providers/self-hosted-decision-models.mdx`, `plugins/routing`. Not in `SCOPE.md`. **Status: Open.** Product decision. Not built: `/v1/decisions`, typesafe, and the decision-model classifier.

- **G37. Compat plugin.** Implement `x-bf-compat`, `client.compat`, parameter dropping and conversion, text-to-chat, chat-to-responses, reasoning-only models, and decision emulation. Bifrost: `plugins/compat/` (convertparams.go, dropparams.go, azure.go), `docs/features/compat-plugin.mdx`. Response headers `x-bifrost-dropped-compat-params` and `x-bifrost-dropped-unsupported-tools` depend on it. **Status: Open.** Product decision. Not built: the compat plugin and `x-bf-compat`.

- **G38. Missing providers.** Add `databricks`, `cloudflare`, `github-copilot`, `sarvam`, `wafer`, `opencode-go`, `opencode-zen`, `replicate` (chat only), and `typesafe`. Bifrost: `core/schemas/bifrost.go:49-82`, `docs/providers/supported-providers/`. `elevenlabs`, `runway` and `runware` are media providers and out of scope. **Status: Partial** (commit d27a62e). The listed chat providers are in. Remaining: typesafe (see G36).

- **G39. Raw request and response handling.** Implement `x-bf-send-back-raw-request`, `x-bf-send-back-raw-response`, `x-bf-store-raw-request-response`, and the provider-level `send_back_raw_*` keys (parsed but unused in Raiju). Bifrost: `transports/bifrost-http/lib/ctx.go:715-737`, `config.schema.json` provider. Ledger task. **Status: Partial** (commit cbd6ad3). Send-back for request and response, per provider and per request, is done. Remaining: `x-bf-store-raw-request-response`.

- **G40. Live, WebSocket responses, and the UI socket.** `/v1/responses` WebSocket mode (`handlers/wsresponses.go`), `/v1/live/sessions` (`handlers/wslive.go`, `livecontrol.go`), and `/ws` (`handlers/websocket.go`). Not in `SCOPE.md`. **Status: Open.** Product decision. Not built: WebSocket responses, `/v1/live/sessions` and `/ws`.

- **G41. Projects, business units and custom RBAC.** `governance.projects`, `governance.business_units`, `governance.roles`, `x-bf-project-id`, `x-bf-customer-id`, custom roles and permissions, and data access scopes. Bifrost: `handlers/governance.go`, `docs/enterprise/projects.mdx`, `data-access-control.mdx`. Enterprise scope decision. **Status: Open.** Enterprise decision. Not built: projects, business units, custom roles and data access scopes.

- **G42. Log sinks and export formats.** BigQuery, Kafka, Pub/Sub, Maxim sinks; Parquet payloads; export retention policy. Bifrost: `docs/features/observability/*.mdx`, `docs/enterprise/log-exports.mdx`. Raiju: `src/exports.tov` (JSONL only). **Status: Open.** Product decision. Not built: BigQuery, Kafka, Pub/Sub and Maxim sinks, and Parquet.

- **G43. Guardrail breadth.** Secrets detection (Gitleaks rule set), regex guardrails, reversible redaction, prompt guardrails (LLM judge), MCP tool-call guard, and the Presidio, Azure Language PII, Google Model Armor and CrowdStrike AIDR providers. Bifrost: `docs/enterprise/guardrails*.mdx`, `docs/integrations/guardrails/*`. Raiju: `src/guardrails.tov`, `src/guardrail_providers.tov`. **Status: Open.** Product decision. Not built: the Gitleaks rule set, prompt guardrails, MCP guard, and the Presidio, Google, Azure Language and CrowdStrike providers.

- **G44. Clustering discovery and leader election.** Kubernetes, DNS, Consul, etcd, mDNS and UDP discovery; leader election; broker mode. Bifrost: `transports/config.schema.json` `cluster_config`, `docs/enterprise/clustering.mdx`. Raiju: `src/cluster.tov`, static peers only. **Status: Open.** Product decision. Not built: discovery modes and leader election. Static peers only.

- **G45. Auth proxies.** AWS ALB, Cloudflare ZTNA and generic proxy auth. Bifrost: `docs/enterprise/auth-proxy/*.mdx`, `scim_auth_proxy` in the schema. Not in `SCOPE.md`. **Status: Open.** Product decision. Not built: AWS ALB, Cloudflare ZTNA and generic auth proxies.

- **G46. Out-of-scope decisions for Bifrost features not in SCOPE.md.** Prompt repository and deployments, skills marketplace, Warp, agent gateway (A2A), webhooks, feature flags, notifications, Sidekiq, Maxim. Each is a P2 product decision. Add them to SCOPE.md's Out table or to the ledger. **Status: Open.** Product decision. None of these are built, and none are in SCOPE.md's Out table yet.

- **G47. Remaining management API.** Config write (`PUT /api/config`), `/api/version`, `/api/keys`, `/api/models*`, provider refresh-models, circuit breaker and vault routes, proxy config, pricing force-sync, MCP logs and log histograms, and the `/api/session/*` login API. Bifrost: `handlers/config.go`, `handlers/providers.go`, `handlers/logging.go`, `handlers/session.go`, `handlers/circuit*`. Raiju: `src/store.tov`, `src/ops.tov`. **Status: Partial.** Done: version, keys, models (list, base, details), PUT /api/config (client), pricing force-sync, refresh-models, circuit-breaker state, logs histogram, session login, logout and is-auth-enabled. Remaining: proxy-config (no global proxy in Raiju), circuit-breaker reset and vault flush (enterprise-only in Bifrost), the other log histograms, MCP logs, models/parameters and the writable catalog.

- **G48. Remaining config keys.** `encryption_key`, `server.*`, `setup_token`, `vector_store`, `websocket`, `large_payload_optimization`, `feature_flags`, `proxy_config` (global), `access_profiles` (top-level), `provider.ignore_provider_cost`, `provider.injected_tools`, `openai_config.disable_store`, `custom_provider_config` options (allowed_requests, request_path_overrides, does_not_send_done_marker, wait_for_usage), `prompt_cache` per provider (ttl, cache_control_injection_points), `use_for_batch_api`, `concurrency_and_buffer_size`, and the `client.*` keys listed in c2. Bifrost: `transports/config.schema.json`. **Status: Partial** (commits 0c999ff, 0d269dd, d91ef07). Most config sections are mapped. Remaining: encryption_key, server.*, setup_token, websocket, large_payload_optimization, feature_flags, global proxy_config, top-level access_profiles, and the provider and custom-provider options listed in c3.

- **G49. Unused parsed keys.** `client.drop_excess_requests`, `client.prometheus_labels`, `client.allow_direct_keys`, `providers[].send_back_raw_response`. Either implement them or warn at startup. Raiju: `src/config.tov`. **Status: Done** (commit cbd6ad3). The three parsed keys are implemented. drop_excess_requests warns at startup, as the gap allows.

- **G50. Default provider resolution and dynamic aliases.** Model names without a provider prefix are resolved only through key model lists or a `claude` prefix (`src/router.tov:18-33`). Bifrost resolves through its model catalog, and supports dynamic and chained aliases. Bifrost: `docs/providers/provider-routing.mdx`, `aliasing-models.mdx`. **Status: Done** (commit ebc25c7).

## Remaining gaps (after wave 10)

1. G4. Models outside the datasheet cost 0 and skip budgets, with a warning, as in Bifrost (a switch to refuse them is the owner's call).
2. G16, G25. Vertex batches and files (GCS) and Bedrock batches and files (S3).
3. G17. Remaining x-bifrost-* response headers, including retry-after-ms.
4. G22. MCP verification and OAuth management routes answer 501; tool_sync_interval does nothing.
5. G29. OpenTelemetry over gRPC (Tov's fetch is HTTP/1.1 only).
6. G18. Routing-classifier and overhead-component metric families.
7. G47. Proxy-config, circuit-breaker reset, vault flush, the other log histograms, MCP logs.

P2 decisions still open: G36, G37, G40 to G46. Partial P2 items: G35, G39, G47, G48.
