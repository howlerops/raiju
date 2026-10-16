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

Parity rows (one per feature or route family): **498**. Status counts: done 201, partial 127, missing 152, out-of-scope 11, n/a 7 (the table below; the L97e media rows moved four partial rows to done). Raiju-only extras (not parity items, listed for context): 25.

| Section | done | partial | missing | out-of-scope | n/a | Parity rows | Raiju-only extras |
|---|---:|---:|---:|---:|---:|---:|---:|
| (a) HTTP routes | 58 | 28 | 46 | 2 | 1 | 135 | 7 |
| (b) Headers | 29 | 7 | 16 | 0 | 2 | 54 | 8 |
| (c) config.json | 28 | 25 | 35 | 2 | 1 | 91 | 3 |
| (d) Providers | 33 | 29 | 2 | 4 | 0 | 68 | 1 |
| (e) Plugins | 2 | 8 | 5 | 0 | 0 | 15 | 3 |
| (f) Governance | 14 | 8 | 9 | 1 | 1 | 33 | 0 |
| (g) MCP | 11 | 4 | 14 | 1 | 0 | 30 | 0 |
| (h) Observability | 21 | 5 | 12 | 0 | 0 | 38 | 2 |
| (i) Enterprise | 5 | 13 | 13 | 1 | 2 | 34 | 1 |
| **Total** | **201** | **127** | **152** | **11** | **7** | **498** | **25** |

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

Re-audited 2026-10-15 against HEAD (3183cf4) and Bifrost `6c84d7a`. Raiju notes name the file and function, not line numbers. Rows marked "L101/L102 in flight" are being changed by L102 (WebSocket and live remainder) and will be updated by the lead on merge.

### a1. Native /v1 API

Bifrost: `transports/bifrost-http/handlers/inference.go`, `asyncinference.go`, `mcpinference.go`, `wsrealtime.go`, `webrtcrealtime.go`, `realtime_client_secrets.go`, `wsresponses.go`, `livecontrol.go`, `wslive.go`. Documented in `docs/openapi/openapi.json`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| POST /v1/chat/completions | handlers/inference.go; openapi | done | `server.tov` `dispatch` (CHAT_PATHS); streamed by `server.tov` `chatStreamed` (Bun) and `front.tov` (http1). |
| POST /v1/completions | handlers/inference.go | partial | `server.tov` `dispatch`. Text completions for OpenAI-format providers (`gateway.tov` `streamsNatively`); other providers answer "does not serve text completions", as Bifrost does for Gemini, Cohere and Vertex without its compat text-to-chat plugin (checked in Bifrost `core/bifrost.go`: the chat conversion needs `BifrostContextKeyChangeRequestType`, which only the compat plugin sets). Open: Bifrost's Anthropic and Bedrock providers serve text completions natively; Raiju does not on this route (use `/anthropic/v1/complete`). |
| POST /v1/responses (create, stream) | handlers/inference.go; supported-providers/*.mdx | done | `server.tov` `dispatch` → `native.tov` `responsesApi`. Native for OpenAI, translated for other chat providers. |
| GET /v1/responses/{id} | handlers/inference.go; supported-providers/openai.mdx "Responses Lifecycle" | done | `media.tov` `PATTERNS` → `handleMedia` (responses.retrieve). OpenAI and Azure, as Bifrost documents it. |
| DELETE /v1/responses/{id} | same | done | `media.tov` `PATTERNS` → `handleMedia` (responses.delete). OpenAI and Azure. |
| POST /v1/responses/{id}/cancel | same | done | `media.tov` `PATTERNS` → `handleMedia` (responses.cancel). OpenAI and Azure. |
| GET /v1/responses/{id}/input_items | same | done | `media.tov` `PATTERNS` → `handleMedia` (responses.input_items). OpenAI and Azure. |
| POST /v1/responses/input_tokens | handlers/inference.go | done | `media.tov` `PATTERNS` → `handleMedia`. |
| POST /v1/responses/compact | handlers/inference.go; openai.mdx "Context Compaction" | done | `media.tov` `PATTERNS` → `handleMedia`. |
| GET /v1/responses (WebSocket mode) | handlers/wsresponses.go | partial | `server.tov` `wsUpgrade` → `wsresponses.tov` `ResponsesSocket`. Each response.create runs streamed, but the events go out after the upstream has finished, not as they arrive; response.cancel is missing. L101/L102 in flight (streaming, response.cancel). |
| POST /v1/embeddings | handlers/inference.go | done | `server.tov` `dispatch` → `gateway.tov` `Engine.embeddings`. |
| POST /v1/rerank | handlers/inference.go | done | `extras.tov` `rerank` and `rerankText`. Cohere, vLLM and Bedrock answer natively; model `raiju/lexical` asks for the local BM25 ranking. Other providers return an error. |
| POST /v1/ocr | handlers/inference.go; supported-providers/mistral.mdx | done | `media.tov` `PATTERNS` → `handleMedia` (ocr). OpenAI-format and Azure only. |
| POST /v1/audio/speech | handlers/inference.go; supported-providers/gemini.mdx | done | `media.tov` `PATTERNS` → `handleMedia`. OpenAI-compatible and Azure pass through; Gemini (WAV or PCM, `media_native.tov` `geminiSpeech`). Vertex, Bedrock and Anthropic answer 400: Bifrost has no speech for them either (vertex.mdx, bedrock.mdx). |
| POST /v1/audio/transcriptions | handlers/inference.go; supported-providers/gemini.mdx | done | `media.tov` `handleMedia`. OpenAI-compatible and Azure pass through; Gemini (speech-to-text through generateContent, `media.tov` `geminiMedia`). Vertex and Bedrock answer 400, as Bifrost does. |
| POST /v1/audio/translations | not in Bifrost openapi | done (Raiju-only) | `media.tov` `PATTERNS`. |
| POST /v1/images/generations | handlers/inference.go | done | `media.tov` `PATTERNS` → `handleMedia`. OpenAI-compatible and Azure pass through. Gemini (Imagen and image models, `media_native.tov` `geminiImageGeneration`), Vertex and Bedrock (`media_cloud.tov` `vertexImage`, `bedrockImage`). Anthropic has no image API. |
| POST /v1/images/edits | handlers/inference.go; supported-providers/gemini.mdx, bedrock.mdx | partial | `media.tov` `PATTERNS`; the form is read by `media.tov` `readEdit`. OpenAI-compatible and Azure pass through. Gemini (`media_native.tov` `geminiImageEdit`: the images inline on generateContent, or Imagen's :predict with reference images, mask and edit mode), Vertex (`media_cloud.tov` `vertexImageEdit`), Bedrock (`media_cloud.tov` `bedrockImageEdit`: inpainting, outpainting, background removal). Missing: Bedrock Stability AI edits (`stability.*` models; Bifrost's `ToStabilityAIImageEditRequest`). |
| POST /v1/images/variations | handlers/inference.go; supported-providers/bedrock.mdx | done | `media.tov` `PATTERNS`. OpenAI-compatible and Azure pass through. Bedrock (`media_cloud.tov` `bedrockImageVariation`, IMAGE_VARIATION on Titan and Nova Canvas, read by `media.tov` `readVariation`). Gemini and Vertex answer 400, as Bifrost has no variation for them. |
| /v1/videos (create, edits, list, get, content, delete, remix) | handlers/inference.go | out-of-scope | `SCOPE.md` Out: videos. |
| /v1/containers (and /files) | handlers/inference.go | out-of-scope | `SCOPE.md` Out: containers. |
| POST /v1/files, GET /v1/files | handlers/inference.go | done | `media.tov` `PATTERNS` → `handleMedia`; native for Anthropic, Gemini, Vertex (GCS) and Bedrock (S3) in `media.tov` `vertexStore` and `bedrockStore`. Cohere has no files API upstream (Bifrost's Cohere page lists Files as unsupported). |
| GET/DELETE /v1/files/{id}, GET /v1/files/{id}/content | handlers/inference.go | done | `media.tov` `PATTERNS` → `handleMedia`. Same providers as the file list. |
| POST /v1/batches, GET /v1/batches | handlers/inference.go | done | `media.tov` `PATTERNS` → `handleMedia`; native for Anthropic (`anthropic_batch.tov`), Gemini, Vertex (`media_cloud.tov` batch jobs) and Bedrock (`media_cloud.tov` S3 jobs). Cohere has no batch API upstream. |
| GET /v1/batches/{id}, POST /v1/batches/{id}/cancel | handlers/inference.go | done | `media.tov` `PATTERNS` → `handleMedia`. Same providers as the batch list. |
| GET /v1/batches/{id}/results | handlers/inference.go | done | `media.tov` `PATTERNS` → `handleMedia` (batches.results in each provider branch). Anthropic and Gemini output is also readable through `/v1/files/{id}/content`. |
| GET /v1/models | handlers/inference.go | done | `server.tov` `listModels`. Upstream listing for OpenAI-format, Anthropic and Gemini. |
| GET /v1/models/{model} | handlers/inference.go (modelRetrieve) | partial | `server.tov` `retrieveModel` → `model_retrieve.tov` `retrieveRequest` and `retrieveBody`. OpenAI-compatible providers (`/v1/models/{id}`), Anthropic and Gemini (`/v1beta/models/{id}`) return the provider's model object in Bifrost's shape; an upstream 404 is a 404 and a failed call a 502. Other providers keep the stub `{id, owned_by, listed}` from the known list. Missing: Bedrock, Vertex, Cohere and Azure retrieve (Bifrost has a ModelRetrieve for each). |
| POST /v1/mcp/tool/execute | handlers/mcpinference.go | done | `server.tov` `dispatch` → `gateway.tov` `Engine.executeTool`. |
| GET /v1/realtime (WebSocket upgrade) | handlers/wsrealtime.go | done (OpenAI, Azure) | `server.tov` `wsUpgrade` → `realtime.tov` `prepare`; `front.tov` (http1). xAI and ElevenLabs realtime are not wired. |
| POST /v1/realtime/calls (WebRTC SDP) | handlers/webrtcrealtime.go | done | `media.tov` `PATTERNS` → `handleMedia`. Passed through to OpenAI-compatible providers. |
| POST /v1/realtime (WebRTC SDP offer at the base path) | handlers/webrtcrealtime.go (resolveRealtimeSDPTarget) | done | `server.tov` `dispatch` → `media.tov` `realtimeSdp` (the model from the multipart session or ?model=, the call to `/v1/realtime/calls` of that provider; GET still upgrades to the WebSocket, `server.tov` `wsUpgrade`). Previous note: Bifrost accepts the SDP offer at `/v1/realtime` as well as `/v1/realtime/calls`. Raiju routes `/v1/realtime` to the WebSocket upgrade only (`server.tov` `wsUpgrade`, `realtime.tov` `prepare`), so a POST there is refused (400 without `?model=`). Raiju routes the SDP offer at `/calls` only (`media.tov` `PATTERNS`). Buildable: yes, by sending the offer to `/calls` logic from the base path. |
| POST /v1/realtime/client_secrets | handlers/realtime_client_secrets.go | done | `media.tov` `PATTERNS` → `handleMedia`. Passed through to OpenAI-compatible providers. |
| POST /v1/realtime/sessions | openapi | done | `media.tov` `PATTERNS` → `handleMedia`. Passed through to OpenAI-compatible providers. |
| /v1/live/sessions (REST, WebSocket attach, content) | handlers/livecontrol.go, wslive.go | partial | `server.tov` `wsUpgrade` → `live.tov` `LiveSocket` (session.start and attach); `live.tov` `contentId` and `liveContent` (recording). OpenAI only (`live.tov` `attachUpstream`). Missing: POST /v1/live/sessions (WebRTC create), GET list, other providers, and a registry shared between worker processes (`live.tov` `LiveRegistry` is per process). L101/L102 in flight. |
| POST /v1/async/{op} (submit) | handlers/asyncinference.go; docs/features/async-inference.mdx | done | `server.tov` `dispatch` → `asyncSubmitHooked` (`webhooks.tov`); `jobs.tov`. Ops: chat/completions, completions, embeddings, responses, images, audio, rerank, ocr and messages. |
| GET /v1/async/{op}/{job_id} (Bifrost poll paths) | handlers/asyncinference.go; async-inference.mdx "Supported Endpoints" | done | `server.tov` `asyncPoll` → `extras.tov` `asyncGet`; `jobs.tov`. Statuses are pending, processing, completed and failed. |
| GET /v1/async/jobs/{id} | not in Bifrost | done (Raiju-only) | `extras.tov` `asyncGet`. |
| POST /v1/count_tokens | not in Bifrost openapi | done (Raiju-only) | `server.tov` `dispatch` → `extras.tov` `countTokens`. Exact for Anthropic and Gemini, estimated (`"exact": false`) elsewhere. |
| POST /v1/decisions (and /openai/v1/decisions) | handlers/inference.go; docs/providers/self-hosted-decision-models.mdx | done | `server.tov` `dispatch` → `extras.tov` `decisionRoute` (`decisions.tov`, `decision_emulate.tov`). Custom providers and TypeSafe answer on their base format; other providers are refused, as Bifrost refuses them. Open (L81): decision pricing overrides and the x-bf-passthrough-extra-params gate. |

### a2. SDK and compatibility routes

Bifrost: `transports/bifrost-http/integrations/*.go`. Mounted by `handlers/integrations.go:33-51`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| POST /openai/v1/chat/completions, /openai/chat/completions | integrations/openai.go | done | `server.tov` `CHAT_PATHS`. |
| POST /openai/deployments/{d}/{chat/completions, completions, embeddings, responses (and input_tokens, compact), images, audio, models} | integrations/openai.go | done | `media.tov` `deploymentRoute` and `deploymentRequest` (the deployment is the model; dispatched by `server.tov` `dispatch`). Model listing under a deployment is not routed. |
| POST /openai/v1/completions, /embeddings, /responses; GET /openai/v1/models; WS /openai/v1/realtime | integrations/openai.go | done | `compatPath` maps `/openai/v1/` onto the `/v1` routes; `server.tov` `dispatch` and `wsUpgrade`. |
| /openai/{completions, embeddings, responses, models, files, batches, realtime} (no /v1 segment) | integrations/openai.go (CreateOpenAIRouteConfigs and the list, batch and file configs mounted at /openai) | done | `server.tov` `compatPath` (`isUnversionedOpenAI`) maps every /openai/X onto /v1/X (the deployments excepted); `wsUpgrade` does the same for /openai/realtime. Covers responses and its lifecycle, embeddings, completions, models and /models/{model}, files, batches, realtime/calls. L101/L102 may add the response WebSocket aliases. |
| /openai/v1/audio/speech, /transcriptions; /openai/v1/images/*; /openai/v1/files*; /openai/v1/batches* | integrations/openai.go | done | `compatPath` maps `/openai/v1/` onto the `/v1` routes; `media.tov` `PATTERNS`. |
| /openai/v1/responses/{id} (GET, DELETE), cancel, input_items; /openai/v1/responses/input_tokens and /compact | integrations/openai.go | done | `compatPath`, then `media.tov` `PATTERNS`. |
| /openai/v1/realtime/calls, client_secrets, sessions | integrations/openai.go | done | `compatPath`, then `media.tov` `PATTERNS`. |
| POST /anthropic/v1/messages (and stream), any provider | integrations/anthropic.go | done | `server.tov` `dispatch` and `streamKind`; `native.tov` `anthropicMessages` (bridged to chat for non-Anthropic targets). |
| POST /anthropic/v1/messages/count_tokens | integrations/anthropic.go | done | `server.tov` `dispatch` → `extras.tov` `countTokens`. |
| GET /anthropic/v1/models (and /{id}) | integrations/anthropic.go | done | `anthropic_batch.tov` `sdkRoute` and `anthropicSdk`. |
| /anthropic/v1/messages/batches (create, list, get, cancel, results) | integrations/anthropic.go | done | `anthropic_batch.tov` `sdkRoute` and `anthropicSdk`. Passed to Anthropic, or converted through an OpenAI-format provider. |
| /anthropic/v1/files (upload, list, get, content, delete) | integrations/anthropic.go | done | `anthropic_batch.tov` `sdkRoute` and `anthropicSdk`. |
| POST /anthropic/v1/complete (legacy) | integrations/anthropic.go | partial | `server.tov` `dispatch` → `native.tov` `anthropicLegacy`: the prompt becomes one user turn, served through the messages bridge by any provider, answered as `{id, type: "completion", completion, stop_reason, model, usage}`. Open: streaming is refused (400); Bifrost streams it, and sends Anthropic's own legacy call to Anthropic targets. |
| POST /genai/v1beta/models/{m}:generateContent | integrations/genai.go | done | `native.tov` `genai` (GenAI route in `server.tov` `dispatch`). Any provider: Gemini natively, others through the chat bridge. |
| :streamGenerateContent, :countTokens, :embedContent, :predict | integrations/genai.go | done | `native.tov` `genai` (streams through `server.tov` `streamKind`); `native.tov` `genaiModelRoute` for :predict (Imagen as images, other models as embeddings). |
| GET /genai/v1beta/models, GET /genai/v1beta/models/{m} | integrations/genai.go | done | `server.tov` `genaiModels`. |
| GET /genai/v1beta/models/{m}/operations/{id} | integrations/genai.go | partial | `native.tov` `genaiModelRoute` (operations.get). Gemini only; other providers answer Bifrost's unsupported-operation error (video retrieval). |
| /genai/v1beta/files and /genai/upload/v1beta/files | integrations/genai.go | done | `genai_in.tov` `genaiRoute`; `native.tov` `genaiSdk` → `genaiUpload` and `genaiStore`. Gemini natively; OpenAI-format, Anthropic, Vertex and Bedrock through the media routes. |
| /genai/v1beta/batches (and /{id}), :batchGenerateContent | integrations/genai.go | done | `genai_in.tov` `genaiRoute` → `native.tov` `genaiModelRoute` and `genaiStore`. Gemini natively; others through `media.tov`. POST on an item cancels with or without `:cancel`, as Bifrost routes it. Vertex's regional batchPredictionJobs (`/genai/v1/projects/{p}/locations/{l}/batchPredictionJobs`): `media.tov` `nativeRoute` and `nativeCloud`, the body as sent, to the key's project and region (the path's project and location are placeholders, as in Bifrost). |
| /genai/v1beta/cachedContents (and /{id}, Vertex regional) | integrations/genai.go | done | Gemini: `genai_in.tov` `genaiRoute` → `native.tov` `genaiStore` (cached.*). Vertex regional (`/genai/v1beta/projects/{p}/locations/{l}/cachedContents`): `media.tov` `nativeCloud` to the key's v1beta1 collection, as sent. |
| POST /genai/v1/rank | integrations/genai.go | done | `native.tov` `genaiRank` → `extras.tov` `rerank`. Vertex by default, as Bifrost. |
| POST /bedrock/model/{id}/converse | integrations/bedrock.go | done | `server.tov` `dispatch` → `native.tov` `bedrockModel`. Any provider. |
| POST /bedrock/model/{id}/invoke | integrations/bedrock.go | done | `native.tov` `bedrockModel`. Any provider. |
| POST /bedrock/model/{id}/converse-stream | integrations/bedrock.go:68 | done | `server.tov` `streamKind` and `native.tov` `bedrockModel`, AWS event-stream framing. |
| POST /bedrock/model/{id}/invoke-with-response-stream | integrations/bedrock.go:118 | done | `server.tov` `streamKind` and `native.tov` `bedrockModel`, AWS event-stream framing. |
| POST /bedrock/model/{id}/count-tokens | integrations/bedrock.go:323 | done | `server.tov` `dispatch` → `native.tov` `bedrockModel` → `extras.tov` `bedrockCountTokens`. Bedrock models are counted by Bedrock's CountTokens (exact); other providers get an estimate. |
| POST /bedrock/rerank | integrations/bedrock.go:287 | done | `server.tov` `dispatch` → `extras.tov` `bedrockRerank`; Bedrock or any rerank provider. |
| /bedrock/model-invocation-job(s), /bedrock/files/* | integrations/bedrock.go | done | `server.tov` `dispatch` → `media.tov` `nativeRoute` and `nativeCloud`: create, list, get and stop jobs as AWS calls with the body as sent; `/bedrock/files/{bucket}/{key}` (PUT, GET, HEAD, DELETE) and `/bedrock/files/{bucket}` (list) as S3 calls to the key's endpoint. Open: file bodies are read as text (a binary PUT is not byte-exact). |
| POST /cohere/v2/chat, /cohere/v2/embed, /cohere/v2/rerank, POST /cohere/v1/tokenize | integrations/cohere.go:73-200 | done | `server.tov` `dispatch` → `native.tov` `cohereChat`, `cohereEmbed`, `cohereRerank`, `cohereTokenize`. |
| /litellm/* and /langchain/* prefixes | integrations/litellm.go, langchain.go | done | `compatPath` strips the prefix on every route, Cohere routes included. |
| /pydanticai/* prefix | integrations/pydanticai.go | done | `compatPath`. |
| /cursor/* routes (chat through the Responses pipeline, models, anthropic, genai) | integrations/cursor.go | partial | `server.tov` `compatPath` strips `/cursor` for models, anthropic, genai, bedrock and cohere. Chat: `native.tov` `cursorChat` (a Responses-shaped body goes through `/v1/responses` and comes back as a chat completion, non-streamed; messages go to chat). Open: streamed Responses-shaped chat (400; Bifrost converts the Responses stream into chat chunks), and Bifrost's cursor-specific tool-result and Anthropic-block fixes in its request parser. |
| /openai_passthrough, /anthropic_passthrough, /azure_passthrough, /bedrock_passthrough, /genai_passthrough, /chatgpt_passthrough, /runware_passthrough | integrations/passthrough.go:184-261 | partial | `passthrough.tov` `ROUTES` and `passthroughRoute`. Six prefixes done, including GenAI interactions as raw passthrough. `/runware_passthrough` is not built (its media provider is out of scope). |
| /typesafe/v1/models, /typesafe/v1/systemone | integrations/typesafe.go | done | `server.tov` `dispatch` → `extras.tov` `decisionRoute` (`providers/typesafe.tov`). |
| /agents/a2a/{name}/* (agent card, json-rpc, rest message, tasks, push configs) | handlers/agentgateway.go | missing | P2. Not in `SCOPE.md`. |

### a3. Management API (/api)

Bifrost: `transports/bifrost-http/handlers/*.go`, documented in `docs/openapi/openapi.json`. Raiju routes: `server.tov` `manage` (dispatches the /api tree), `store.tov` `handleApi` (config, providers, governance, roles), `ops.tov` (users, logs, MCP logs, audit, sessions), `mcpapi.tov` (MCP clients), `profiles.tov`, `prompts.tov`, `webhooks.tov`, `flags.tov`, `notify.tov`, `alertapi.tov`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| GET /api/config | handlers/config.go | done | `store.tov` `handleApi` → `ConfigStore.redacted`. Secrets are masked in every section. |
| PUT /api/config (client section), POST /api/config/metadata | handlers/config.go | partial | `store.tov` `putConfig` takes the `client` section only (and refuses unknown settings); POST /api/config/metadata is `store.tov` `postMetadata` (L97b), stored as the top-level `metadata` map (strings, numbers, bools; null removes; objects and lists refused). Open: PUT /api/config for the other sections Bifrost's config.go accepts. |
| GET /api/version | handlers/config.go | done | `store.tov` `handleApi`. |
| GET and PUT /api/proxy-config | handlers/config.go | done | `store.tov` `handleApi` → `proxyRoute`; the gate for widening the global proxy is in `server.tov` `manage`. |
| POST /api/pricing/force-sync | handlers/config.go | done | `server.tov` `manage` → `ops.forcePricing`. |
| GET /api/providers (list), GET/PUT/DELETE /api/providers/{p} | handlers/providers.go | done | `store.tov` `providerRoute`. PUT upserts. |
| POST/PUT/DELETE /api/providers/{p}/keys[/{id}] | handlers/providers.go | done | `store.tov` `providerRoute`. |
| POST /api/providers (create) | handlers/providers.go | done | `store.tov` `createProvider` (L97b): the body's provider field names it, 409 when it exists; then `saveProvider`, as PUT. |
| GET /api/providers/{p}/keys (list) and GET /api/providers/{p}/keys/{id} | handlers/providers.go | done | `store.tov` `listProviderKeys` and `getProviderKey` (L97b): {keys, total} and one key, values masked. |
| POST /api/providers/{p}/refresh-models, POST /api/providers/{p}/keys/{id}/refresh-models | handlers/providers.go | done | `server.tov` `manage` → `refreshModels`. |
| GET /api/keys | handlers/providers.go | done | `store.tov` `handleApi` → `keyList` (masked). |
| GET /api/models (list), /api/models/{provider}, /details, /base, /parameters; PUT /api/models/catalog | handlers/providers.go | done | `store.tov` `modelList` (list); `ops.tov` `catalogView` (details, base), `modelParameters` (parameters), `catalogUpsert` (PUT catalog). |
| /api/governance/virtual-keys CRUD | handlers/governance.go | done | `store.tov` `governanceRoute` (COLLECTIONS). |
| VK rotate (collection and per key) | handlers/governance.go, virtualkeyrotation.go | partial | `store.tov` `rotateVkRoute` and `rotateVirtualKey` (L97b): new value in the reply, old value kept for client.vk_rotation_cooldown (`governance.tov` `prevVks`). Open: revoking the key's MCP OAuth grants on rotate. |
| GET /virtual-keys/quota, budget override PUT/DELETE | handlers/governance.go | missing | P2. Not routed (L97b did not reach them). |
| GET /api/governance/virtual-keys/{vk}/users (VK users) | handlers/governance.go | missing | P2. |
| /api/governance/budgets, rate-limits, customers, teams CRUD | handlers/governance.go | done | `store.tov` `governanceRoute` (COLLECTIONS, scoped by data access). Raiju exposes CRUD; the Bifrost documented routes for budgets and rate limits are read-only. |
| GET /api/governance/teams/{team}/members | handlers/governance.go | done | `store.tov` `teamMembers` (L97b): users whose `teams` name the team, as {members}; users have no email or id of their own, so the name stands for both. |
| /api/governance/model-configs CRUD | handlers/governance.go | done | `store.tov` `modelConfigRoute`. |
| /api/governance/providers (provider-level budgets and limits) | handlers/governance.go | done | `store.tov` `providerGovRoute`. |
| /api/governance/pricing-overrides CRUD | handlers/governance.go | done | `store.tov` `pricingRoute`. |
| /api/governance/routing-rules and /api/routing/rules CRUD | handlers/governance.go, routing.go | partial | Config only (`config.tov`, `governance.routing_rules`). No management API. |
| /api/routing/complexity-analyzer-* and /api/governance/complexity-analyzer-config | handlers/routing.go | partial | Config only (`complexity_router` in `config.tov`). No API. |
| /api/governance/business-units CRUD | handlers/governance.go | done | `store.tov` `businessUnitRoute`; data access scopes apply. L84. |
| /api/governance/projects CRUD | handlers/governance.go | partial | `store.tov` `projectRoute` (list with search and is_active, get, create, update, delete). Missing: the project members API (`/members/{member_id}`), split policies and entity_dac overrides. L84. |
| /api/users CRUD (with role in PUT), /api/users/{id}/role, /api/governance/users, /users/email/{email}, /users/me/permissions, /users/me/vk-creation-policy, /users/{id}/access-profiles/virtual-keys/{vk} | handlers/governance.go | partial | `ops.tov` `users` → `rbac.tov` `handleUsers`. CRUD and Basic or Bearer tokens. Missing: a separate role endpoint, email lookup, the caller's own permissions and VK-creation policy, and VK links to access profiles. |
| /api/governance/access-profiles CRUD, activate | handlers/governance.go | partial | `ops.tov` `profiles` → `profiles.tov` `handleProfiles`. CRUD and activate. No versions, clone, deactivate, roles or propagate. |
| /api/roles CRUD (custom roles) | handlers/governance.go, roles | done | `store.tov` `roleRoute`. Built-in roles (admin, editor, viewer, auditor) are fixed and reserved. L84. |
| /api/permissions, /api/resources, /api/operations, /api/governance/rbac/* | handlers/governance.go, roles | missing | P2. Raiju checks permissions from `rbac.tov` but does not list them through the API. |
| GET /api/governance/usage | not in Bifrost (budget usage is GET /api/governance/budgets) | done (Raiju-only) | `server.tov` `dispatch` → `governance.tov` `budgetUsage`. |
| GET /api/logs (list and filters) | handlers/logging.go | partial | `ops.tov` `logsRoute` → `logList` (L97c); `logapi.tov` `listJson`, `listFilter`, `pageOfQuery`; `logstore.tov` `filterFrom`, `selects`. Bifrost's list shape (logs, pagination, stats, has_logs), with Raiju's entries and total alongside. Filters: providers, models, status, virtual_key_ids, team, customer, user, business unit and project ids, session_id, user_agents, apps, objects, min and max latency, tokens and cost, missing_cost_only, content_search, request_id, start_time, end_time, period, sort_by and order. Not recorded, refused with 400: selected_key_ids, routing_rule_ids, routing_engine_used, stop_reasons, aliases, parent_request_id, roots_only, group_sessions, agent names and correlation id, complexity filters, prompt filters, cache_hit_types. |
| GET /api/logs/stats | handlers/logging.go | done | `ops.tov` `logStats` → `statsView` (`logstore.tov`). Bifrost's SearchStats fields for the recorded data; cache_hit_rate_total_requests and the semantic hit counts are not reported. |
| GET /api/logs/{id}, /sessions/{id}, /sessions/{id}/summary | handlers/logging.go | done | `ops.tov` `logById`, `sessionLogs`; `logapi.tov` `detailJson`, `sessionJson`, `sessionSummaryJson`. The session id is recorded on each entry from x-bf-session-id or a harness session header (`affinity.tov` `sessionId`, whose header list is shorter than Bifrost's: no x-session-affinity or session-id). Session pages are capped at 500, oldest first. |
| GET /api/logs histograms (cost, tokens, latency, models, throughput, by provider or dimension), rankings, dashboard, filterdata, dropped | handlers/logging.go | partial | `ops.tov` `logsRoute` (`logstore.tov`). Dimensions user, app and user_agent are recorded (L97c) and answer; team, customer, business unit, project, provider, model, virtual_key, tool and server too. /api/logs/rankings/users added (L97c). filterdata adds user_ids, apps and user_agents. |
| DELETE /api/logs; POST /api/logs/recalculate-cost (status, cancel) | handlers/logging.go | partial | `ops.tov` `deleteLogs` (admin only: all-data scope), `recalculateCost`, `recalcStatus`. The recalculation runs to the end inside its request and reports completed (Bifrost runs a background job with progress); cancel and status report that state, so cancel stops nothing. Costs are priced again from the current price list (`pricing.tov`). |
| /api/logs/user-agent-mappings CRUD | handlers/logging.go | partial | `ops.tov` `userAgentRoute` → `logapi.tov` `uaRoute`; saved in `config.tov` `user_agent_mappings` (via `store.tov` `setUserAgentMappings`). The app of a request is the first active mapping that matches, then Bifrost's built-in identifiers, else Other (`logapi.tov` `appOf`). regex match_type is refused: Raiju has no regular expression engine. |
| GET/DELETE /api/mcp-logs and sub-routes (get by id, filterdata, stats, histogram, cost, top-tools) | handlers/logging.go | done | `ops.tov` `logsRoute` → `mcpLogsRoute`. |
| GET /api/mcp (status) and GET /api/mcp/clients | handlers/mcp.go | done | `server.tov` `mcpView`; `/api/mcp/clients` in `mcpapi.tov` `mcpApi`. |
| /api/mcp/client CRUD; reconnect, refresh-tools, verify-headers, verify-exchange, reauthorize, reregister, initiate-verification, complete-oauth | handlers/mcp.go | partial | `mcpapi.tov` `mcpApi` and `verifyRoute`; `server.tov` `mcpAction` for reconnect and refresh. Authorization-code OAuth clients are done (L91). Missing: per_user_oauth and per_user_headers flows. |
| GET /api/mcp/client/{id}/openapi-spec | handlers/mcp.go | partial | `mcpapi.tov` openapiSpec: returns the stored inline spec of an openapi client, else 404. A spec_url client keeps only the URL. |
| /api/mcp/library (and force-sync, filterdata); POST /api/mcp/openapi/preview | handlers/mcp.go | partial | Preview done: `mcpapi.tov` openapiRoute. The library routes are missing. |
| /api/mcp/virtual-mcps CRUD, virtual-key attach and detach | handlers/virtualmcp.go | done | `mcpapi.tov` `virtualRoute`; `vmcp.tov`. |
| /api/mcp/tool-groups CRUD | openapi | done | `mcpapi.tov` toolGroupRoute: an alias of the virtual MCPs with the group's shape (`mcp_tool_groups`, `mcp_tool_group`). user_ids and api_key_ids are refused. |
| /api/mcp/sessions (list, reauth, revoke); /api/oauth/per-user/flows/* | handlers/mcpsessions.go | missing | P2. |
| /api/mcp/per-user-headers flows and credential revoke | handlers/mcpheaders.go | missing | P2. |
| /api/oauth/callback | handlers/mcpoauth2.go | done | `server.tov` `dispatch` → `mcpapi.tov` `oauthCallback` (MCP authorization-code flow, PKCE). |
| /api/oauth/config/{id}/status, DELETE /api/oauth/config/{id} | handlers/mcpoauth2.go | partial | `mcpapi.tov` oauthConfigRoute (the config is the MCP client of auth type oauth). Status is pending or authorized; the flow_id form, failed and expired are not done. DELETE drops the tokens; a live session keeps its token until it reconnects. |
| /api/oauth2/sessions; /api/oauth2/consent/flows/* | handlers/mcpoauth2sessions.go, mcpoauth2consent.go | missing | P2. |
| /.well-known/oauth-protected-resource, /.well-known/oauth-authorization-server, /.well-known/jwks.json, /oauth2/register, /oauth2/authorize, /oauth2/token | handlers/mcpoauth2discovery.go, mcpoauth2issuance.go | missing | P2. Raiju is an OAuth client only (`mcpauth.tov`, `oidc.tov`); it does not issue tokens. |
| /api/session/login, logout, is-auth-enabled | handlers/session.go | done | `ops.tov` `sessionRoute`. |
| /api/session/setup, /api/session/ws-ticket | handlers/session.go | partial | ws-ticket: `ops.tov` `sessionRoute` → `wsticket.tov` `WsTickets` (30 seconds, single use, issued to a caller who may read the logs); `/ws?ticket=` is consumed in `server.tov` `wsUpgrade`. setup: `ops.tov` `sessionRoute` answers 409 as Bifrost does while no setup lock is active; Raiju has no setup lock, so the setup token flow is not implemented. |
| /api/oidc/login, /api/oidc/callback, /api/oidc/status | not in Bifrost openapi | done (Raiju-only) | `ops.tov` `oidcRoute`. |
| /api/audit-logs (list), /export, /verify | enterprise/audit-logs.mdx; openapi | partial | `ops.tov` `auditRoute`; `audit.tov` `find`, `filterData`. L97c adds /api/audit-logs/{id} (Bifrost's {audit_log} wrapper; the id is the event's sequence number) and /api/audit-logs/filterdata (actors, actions, methods, paths, ips) and the /api/governance/audit-logs alias (`server.tov` `auditTarget`, RBAC in `rbac.tov`). No per-event /verify (the chain verify is whole-log). Bifrost's list filters (page, cursor, outcome, initiator, target) are not supported. |
| /api/alerts (GET) | not in Bifrost openapi | done (Raiju-only) | `ops.tov` `alertsView`. |
| /api/alerting/* (rules CRUD, usage, history) | not in Bifrost openapi | done (Raiju-only) | `server.tov` `manage` → `alertapi.tov` `alertingRoute`. |
| /api/health (per-target health) | not in Bifrost openapi | done (Raiju-only) | `server.tov` `dispatch` (GET, after the `ops.check` gate). |
| /api/notifications (GET, POST) | handlers/notifications.go | done | `server.tov` `manage` → `notify.tov` `notifyRoute`. |
| /api/webhooks CRUD, /{id}/test, /{id}/rotate-secret, deliveries, redeliver | handlers/webhooks.go | done | `server.tov` `manage` → `webhooks.tov` `webhookApi`. Standard Webhooks signing and retries (L88). Deliveries are in memory. |
| /api/plugins CRUD, /builtins, /loaded | handlers/plugins.go | partial | Read-only (L97c): `ops.tov` `pluginsRoute` lists GET /api/plugins and /api/plugins/{name} (from the config's plugins, with status from `plugins.tov` `entryStatus`), /builtins (the Bifrost names Raiju implements) and /loaded (the live chain). POST, PUT and DELETE answer 405: the plugin list changes through the config. |
| /api/feature-flags | handlers/featureflags.go | done | `server.tov` `manage` → `flags.tov` `flagRoute`. |
| GET /api/cache (stats) | handlers/cache.go | partial | `server.tov` `cacheView`. DELETE /api/cache/clear/{id} and /clear-by-key/{key} are in `ops.tov` `cacheClear` (L97c): they clear the exact-match cache (by the SHA-256 hex of the key, or the x-bf-cache-key the entry was stored under) and the semantic cache's local memory. Shared cache files are removed; other workers' memory copies last until they expire; the semantic cache's entries in an external vector store are not cleared. |
| /api/circuit-breaker/policies (CRUD), /state, /reset | openapi | done | `server.tov` `manage` → `ops.circuitPoliciesRoute` (`health.tov`), `ops.circuitView`, `ops.circuitReset`. Policies persisted (L91). |
| POST /api/vault/flush-cache | openapi | done | `server.tov` `manage` → `ops.vaultFlush`. |
| POST /api/cluster/sync (peer sync), GET /api/cluster/leader | Bifrost has its own cluster gossip (`cluster_config`) | partial | `ops.tov` `clusterSync` (Raiju HMAC protocol). Not wire-compatible with Bifrost clustering. GET /api/cluster/leader is Raiju-only (`ops.tov` `clusterLeader`, L94). |
| /api/prompt-repo/* (folders, prompts, versions, sessions, deployments) | handlers/prompts.go | done | `server.tov` `manage` → `prompts.tov` `promptRoute`. Deliveries and deployments (L88). |
| /api/skills/* and /api/skills/serve/* (marketplace git, zip) | handlers/skills.go, skills_serving.go | missing | P2. Not in `SCOPE.md`. |
| /api/agents/* (history, push-configs, inspect) | handlers/agentgateway.go | missing | P2. Not in `SCOPE.md`. |
| /api/warp/* | handlers/warp.go | missing | P2. Not in `SCOPE.md`. |
| /api/sidekiq/jobs* | handlers/sidekiq.go | missing | P2. Bifrost's internal job queue. |
| /api/api-keys (CRUD) | openapi | missing | P2. Not in `SCOPE.md`. |
| /api/dev/pprof* | handlers/devpprof.go | n/a | Dev-only profiling. |

### a4. Ops and transport

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| GET /health | handlers/health.go | done | `server.tov` `dispatch`. Returns `{"status":"ok"}`. |
| GET /metrics | plugins/telemetry | done | `server.tov` `dispatch` → `ops.metricsText` → `metrics.tov`. Families and labels follow Bifrost (http, request, token, cost, cache, upstream, stream, overhead components, routing, key rotation, active requests, provider key up, MCP duration). Per-family label sets were not re-checked against Bifrost one by one. The raiju_* families are extras. |
| GET / (web UI) | handlers/ui.go | done | `server.tov` `dispatch` (`INDEX_HTML`), `ui_assets.tov`. Raiju's own UI, a subset of Bifrost's. |
| CORS and preflight (`client.allowed_origins`) | lib/ | done | `server.tov` `cors` and `EXPOSED`. |
| POST /mcp (gateway as MCP server, sessions) | handlers/mcpserver.go | done | `ops.tov` `mcp` → `mcpserver.tov` `handleMcp`. |
| GET /mcp (SSE stream) and GET /mcp/{slug} | handlers/mcpserver.go | partial | `ops.tov` `mcp` answers GET with `text/event-stream` and one `connection/opened` event, after the same key and virtual-MCP checks as POST. Open: Bifrost keeps the stream open with heartbeats until the client leaves; Raiju ends it after the event (the server sends nothing on its own, so nothing is lost). DELETE ends a session. |
| POST /mcp/{slug} (virtual MCP) | handlers/mcpserver.go | done | `server.tov` `dispatch` → `ops.tov` `mcp` (virtual name) → `vmcp.tov`. |
| /ws (UI WebSocket) | handlers/websocket.go | partial | `server.tov` `wsUpgrade` → `ops.tov` `UiSocket` (log feed, scoped to the caller's data access). Accepts `?ticket=` from /api/session/ws-ticket (L97c). No heartbeat, and the socket registry is per process. L101/L102 in flight (heartbeat, registry shared across workers). |
| HTTP/1.1 server and Bun.serve | n/a | done (Raiju-only) | `front.tov`, `server.tov` `start`. |

## (b) Headers

### b1. Request headers

Bifrost: string literals in `transports/bifrost-http/lib/ctx.go`, `ConvertToBifrostContext` (about lines 419-766), and `lib/virtualkey.go`. Constants in `core/schemas/bifrost.go` and `core/schemas/async.go`. Raiju: function names are given (`src/gateway.tov`, `src/governance.tov` and so on), not line numbers.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| x-bf-vk | lib/ctx.go:421 | done | `governance.tov` findKey. |
| VK in Authorization Bearer, x-api-key, x-goog-api-key or api-key | docs/features/governance/virtual-keys.mdx; lib/ctx.go:419-422 | done | `governance.tov` findKey (Bearer first, then x-api-key, x-goog-api-key, api-key). |
| x-bf-api-key (pin a key by name or id) | lib/ctx.go:548 | done | `gateway.tov` attempt (the pinned key); `router.tov` pickKey. |
| x-bf-api-key-id | lib/ctx.go:554 | done | `gateway.tov` attempt. |
| x-bf-direct-key (raw provider key from the caller) | lib/ctx.go:422, 900; lib/ctx.go:59-60 | done | `governance.tov` directKeyFrom. Used only when `client.allow_direct_keys` is on. |
| x-bf-session-id | lib/ctx.go:618 | done | `affinity.tov` sessionHeaders. |
| x-bf-session-ttl | lib/ctx.go:622 | done | `affinity.tov` sessionHeaders. |
| x-bf-session-affinity | lib/ctx.go:638 | done | `affinity.tov` affinityMode. |
| x-bf-project-id, x-bf-project-name | core/schemas/bifrost.go:643-644 | done | Projects (L84): `governance.tov` projectOf. The key must belong to the project. Members API and split policies are open (L84). |
| x-bf-customer-id, x-bf-customer-name | docs/features/governance/budget-and-limits.mdx; core/schemas/bifrost.go:277 (set by Bifrost's enterprise governance plugin) | done | `governance.tov` admit: the charge goes to that customer, which the key must reach. |
| x-bf-dim-* (custom metric and log dimensions) | lib/ctx.go:443; core/schemas/bifrost.go:454 | done | Prometheus labels through `client.prometheus_labels` (`metrics.tov` customValues), and log row metadata (`reqlog.tov` logMetadata; the row's `metadata` field). |
| x-bf-prom-* (custom Prometheus labels) | lib/ctx.go:449 | n/a | Removed upstream. Bifrost swallows it (`transports/bifrost-http/lib/ctx.go:449`). Use `x-bf-dim-*`, which is done. |
| x-bf-maxim-* | lib/ctx.go:455; plugins/maxim | done | `reqlog.tov` maximAttrs: the trace and generation ids and names, the session, the log repo and the tags. `sink_maxim.tov` maximLines applies them; `exporters.tov` SinkSender.send sends one request per log repo. Only the Maxim log sink reads them. |
| x-bf-mcp-include-clients | lib/ctx.go:477 (x-bf-mcp- prefix) | done | `gateway.tov` withMcpTools. |
| x-bf-mcp-include-tools | docs/mcp/filtering.mdx | done | `gateway.tov` withMcpTools with includeToolNames and toolInList: the request's injected tools are narrowed to the listed `client-tool` names or `client-*` wildcards; an empty value includes none. Applies to chat injection, not to the `/mcp` tool listing. |
| x-bf-mcp-session-id | lib/ctx.go:504 | missing | P2. Read by session-mode per-user OAuth only; the header is not read yet and waits for L97d. |
| x-bf-eh-* (forward extra headers to the provider) | lib/ctx.go:651 | done | `gateway.tov` forwardedHeaders. |
| x-bf-cache-key | lib/ctx.go:561 | done | `gateway.tov` serveInner. |
| x-bf-cache-ttl | lib/ctx.go:566 | done | `gateway.tov` serveInner. |
| x-bf-cache-threshold | lib/ctx.go:587 | done | `gateway.tov` serveInner. |
| x-bf-cache-type (direct or semantic) | lib/ctx.go:602 | done | `gateway.tov` serveInner. |
| x-bf-cache-no-store | lib/ctx.go:607 | done | `gateway.tov` serveInner. |
| x-bf-prompt-cache-auto-inject | lib/ctx.go:725 | done | `gateway.tov` chatOnce. |
| x-bf-disable-content-logging | lib/ctx.go:743 | done | `gateway.tov` contentOff. Honoured only when `client.allow_per_request_content_storage_override` is on (commit 12757de). |
| x-bf-store-raw-request-response | lib/ctx.go:737 | done | `gateway.tov` storeRawOn. Honoured only when `client.allow_per_request_content_storage_override` is on. Provider setting otherwise. |
| x-bf-send-back-raw-request | lib/ctx.go:715 | done | `gateway.tov` sendBackRaw. Per provider, or per request with `client.allow_per_request_raw_override`. |
| x-bf-send-back-raw-response | lib/ctx.go:731 | done | `gateway.tov` sendBackRaw. Per provider, or per request with `client.allow_per_request_raw_override`. |
| x-bf-parent-request-id | lib/ctx.go:750 | done | Log column `parent_request_id` (`reqlog.tov` correlationIds; `gateway.tov` record). Bifrost also links MCP tool logs to it: not done. |
| x-bf-passthrough-extra-params | lib/ctx.go:757 | partial | `gateway.tov` chatOnce: with "true", the body's `extra_params` object is merged into the chat request. On `/v1/decisions` the extras always reach the provider, as Bifrost's decision route sets the gate itself, so no header gate is applied there. Other SDK routes do not read `extra_params`. |
| x-bf-compat | lib/ctx.go:766 | done | `compat.tov` withHeader, read by `gateway.tov` chatOnce and completions, `native.tov` responsesApi, and `extras.tov` decisionRoute. Compat headers on streamed answers are open (L100). |
| x-bf-async-webhook | lib/ctx.go:675; docs/features/async-inference.mdx | done | `webhooks.tov` asyncSubmitHooked, on `/v1/async/*` only. |
| x-bf-async (create) and x-bf-async-id (get) on integration routes | core/schemas/async.go:28-30; transports/bifrost-http/integrations/router.go | done | `server.tov` dispatch: a POST with x-bf-async runs as a job (`extras.tov` sdkAsyncSubmit, the job's op is the route); a GET with x-bf-async-id polls it (`sdkAsyncPoll`: 202 while it runs, then the route's own body or error). The path-based `/v1/async/<op>` routes are unchanged. x-bf-async-webhook is not applied on SDK routes. |
| x-bf-async-job-result-ttl | core/schemas/async.go:26 | done | `jobs.tov` resultTtlMs: seconds, applied to the job's own expiry (`ttl_ms`); 0, negative or non-numeric means the store's TTL, as Bifrost. Read on `/v1/async/*` and on SDK routes. |
| x-bf-prompt-id, x-bf-prompt-version | plugins/prompts/main.go:27; docs/features/prompt-repository/prompts-plugin.mdx | done | `prompts.tov` applyPrompt, applied before the messages in `gateway.tov` chatOnce (L88). |
| x-bf-prompt-var-* (prompt variable values) | not in Bifrost | done (Raiju-only) | `prompts.tov`. |
| x-bf-model-provider | docs; server listing | done | `server.tov` listModels; `extras.tov` typesafeModels. |
| x-bf-list-models-provider | docs | done | `server.tov` listModels. |
| x-bf-agent-correlation-id | plugins/logging/main.go:296 | done | Log column `agent_correlation_id` (`reqlog.tov` correlationIds, cut to 255 bytes as Bifrost does). |
| x-bf-agent-vk-id, x-bf-agent-auth | cli/internal/client/client.go; handlers/agentgateway.go | out-of-scope | The agent gateway (A2A) is in SCOPE.md Out. |
| x-bf-lh-* (logging headers, `client.logging_headers`) | plugins/logging/main.go:1728; config.schema.json client | done | `reqlog.tov` logMetadata: `x-bf-lh-<name>` and the `client.logging_headers` names (exact, or a prefix ending in `*`) go into the row's `metadata`. Credential-bearing headers are recorded as REDACTED; Bifrost stores them as sent. |
| x-bf-user-id, x-bf-env, x-bf-tenant | none: no Bifrost Go code reads these names | n/a | `x-bf-user-id` appears only in Bifrost's example config (`examples/configs/withcompat/config.json`, `required_headers` and `logging_headers`). Raiju's `client.required_headers` can require any header (`governance.tov`). Bifrost's tenant attribution appears in its tests as `x-bf-lh-tenant`, a logging header (see x-bf-lh-*). |
| x-bf-app (Bifrost classifies the app from User-Agent) | core/schemas/useragents.go; core/schemas/enrichment.go (app); plugins/logging/main.go detectAppFromUserAgent | done | `useragent.tov` appFromUserAgent, a port of Bifrost's matcher table; `gateway.tov` serveInner uses it when x-bf-app is absent. The app and the User-Agent are log row fields. |
| x-bf-app (Raiju's header) | not in Bifrost | done (Raiju-only) | `gateway.tov` serveInner sets the `app` label from this header. |
| x-bf-forwarded-proto (request scheme behind a load balancer) | transports/bifrost-http/lib/ctx.go:928 | missing | P2. Bifrost uses it to build the public base URL. Raiju builds no URL from the request (its OIDC and MCP redirect URIs come from config), so nothing reads it yet. |
| x-request-id (incoming id reused as the request id) | lib/responseheaders.go:28 | done | `gateway.tov` serveInner reuses it as the request id and echoes it; `server.tov` echoRequestId echoes the caller's id on every other route (Bifrost's tracing middleware, transports/bifrost-http/handlers/middlewares.go:119). |
| x-bf-provider (media provider selection) | not in Bifrost | done (Raiju-only) | `media.tov` deploymentRequest and provider selection. |
| x-bf-routing-rule | not in Bifrost | done (Raiju-only) | `gateway.tov` route and serveInner. |
| x-bf-complexity-tier | not verified in Bifrost (complexity_tier is a routing-rule variable) | done (Raiju-only) | `gateway.tov` serveInner; `complexity.tov` overrideTier. |
| x-bf-mcp-agent (agent mode toggle) | not in Bifrost (Bifrost uses per-client tools_to_auto_execute) | done (Raiju-only) | `gateway.tov` chat. |

### b2. Response headers

Bifrost: `transports/bifrost-http/lib/responseheaders.go` (constants at lines 23-132) and `ExposedResponseHeaders`. Raiju: `src/gateway.tov` serveInner and routedHeaders, cacheHeaders and cacheView helpers, and `src/server.tov` EXPOSED.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| x-bifrost-request-id | responseheaders.go:23 | done | `gateway.tov` serveInner. |
| x-bifrost-trace-id | responseheaders.go:24 | done | `gateway.tov` serveInner, when tracing is on (`otel.tov`). |
| x-bifrost-provider | responseheaders.go:70 | done | `gateway.tov` routedHeaders. |
| x-bifrost-original-model, x-bifrost-resolved-model | responseheaders.go:71-72 | done | `gateway.tov` routedHeaders. |
| x-bifrost-request-type | responseheaders.go:74 | done | `gateway.tov` serveInner. |
| x-bifrost-fallback-index | responseheaders.go:73 | done | `gateway.tov` routedHeaders. |
| x-bifrost-latency-ms, x-bifrost-upstream-latency-ms | responseheaders.go:79, 125 | done | `gateway.tov` serveInner (latency) and routedHeaders (upstream). |
| x-bifrost-routing-info-* (12 headers) | responseheaders.go:86-97 | partial | 10 of 12 sent (`gateway.tov` routedHeaders): provider, model, requested-provider, requested-model, is-fallback, primary-provider, primary-model, and key and alias-model-id when known; server-side-fallback-model on a non-streamed chat answer from Anthropic (`providers/anthropic.tov` usage iterations). Missing: alias-model-name and alias-model-family. |
| x-bifrost-cache-hit, -hit-type, -requested-provider, -requested-model, -similarity, -threshold | responseheaders.go:106-116 | done | `gateway.tov` cacheHeaders (direct and semantic hits). |
| x-bifrost-cache-hit-latency-ms | responseheaders.go:109 | done | `gateway.tov` cacheHeaders. |
| x-bifrost-cache-id | responseheaders.go:107 | done | Direct hits: the key's sha-256. Semantic hits: the entry's sha-256 of scope and body (`semcache.tov` lookup), or the vector store's entry id. |
| x-bifrost-cache-provider-used, -model-used, -input-tokens | responseheaders.go:114-116 | done | On every cache hit, from the provider, model and prompt tokens that first served the cached answer (`cache.tov` CacheOrigin, `semcache.tov`, the vector store's `origin_*` payload; `gateway.tov` originHeaders). Also on an upstream answer after a semantic miss. Entries cached before this change read as having no origin. |
| x-bifrost-pricing-request-type | responseheaders.go:126 | n/a | Bifrost sets it only for realtime transcription turns and the live meter (`handlers/realtime_turn_pipeline.go`, `handlers/livemeter.go`). Raiju prices each request by its own type and has no pricing mode to report. |
| x-bifrost-converted-request-type | responseheaders.go:127 | done | `gateway.tov` serveInner (compat conversions). |
| x-bifrost-dropped-compat-params, x-bifrost-dropped-unsupported-tools | responseheaders.go:128-129 | done | Sent on non-streamed and streamed answers. A stream's compat headers are decided when the upstream is shaped, before the stream starts (`gateway.tov` attempt and compatHeaders). Raiju sends them whatever the placement, as its non-streamed answers always did; Bifrost sends them only in headers mode. |
| x-bifrost-passthrough-path | responseheaders.go:130 | done | Passthrough routes answer with the provider path they forwarded to, without the passthrough prefix (`passthrough.tov` passthroughRoute). |
| x-bifrost-error-type | responseheaders.go:131 | done | `gateway.tov` serveInner. |
| x-bifrost-retry-after-ms | responseheaders.go:132 | done | `gateway.tov` serveInner, on errors when the upstream gave a retry hint. |
| `extra_fields` in the body, or in headers with `client.extra_fields_placement` | lib/responseheaders.go:161-170; config.schema.json client | done | Body by default: raw request and response go in `extra_fields` when send-back is on (`gateway.tov` withRawFields). With `client.extra_fields_placement: "headers"` the body has no `extra_fields`, and the scalars go out as headers (latency, converted and dropped compat, passthrough path, error type, retry hint). The raw fields have no header and are dropped, as Bifrost does. |
| Access-Control-Expose-Headers for the x-bifrost-* headers | lib/responseheaders.go ExposedResponseHeaders | done | `server.tov` EXPOSED. |
| Webhook delivery headers: webhook-id, webhook-timestamp, webhook-signature, x-bifrost-event | framework/configstore/tables/webhooks.go:100-101; framework/webhooks/client.go:115 | done | `webhooks.tov` (signed Standard Webhooks deliveries; these names cannot be overridden by custom headers). |
| x-bf-attempts | not in Bifrost | done (Raiju-only) | `gateway.tov` attempt and serveInner. |
| x-bf-fallback-used | not in Bifrost | done (Raiju-only) | `gateway.tov` serveInner. |
| x-bf-overhead-us | not in Bifrost | done (Raiju-only) | `gateway.tov` serveInner. |
| x-bf-cache (hit or semantic-hit) | not in Bifrost | done (Raiju-only) | `gateway.tov` serveInner. |
| x-bf-plugin-short-circuit, x-bf-agent-steps, x-bf-agent-tool-calls | not in Bifrost | done (Raiju-only) | `gateway.tov` chatOnce and chat. |

## (c) config.json

### c1. Top-level sections

Bifrost: top-level properties of `transports/config.schema.json`. Raiju: `Config` in `src/config.tov`, the Bifrost-to-Raiju mapping in `src/config_compat.tov` (`normalize`), and the startup notes in `config_compat.tov` (`noteTable`, which says why each ignored key is ignored). Keys Raiju does not act on are reported at startup, so none are dropped silently.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| version, source_of_truth, env_label | config.schema.json (top) | done | Accepted silently (`config_compat.tov` topKeys); no effect, as Raiju reads its config file as written (L97g). |
| $schema | config.schema.json (top) | done | Accepted and skipped (`config_compat.tov` topKeys). |
| encryption_key | config.schema.json (top) | partial | Done with a different key derivation: `store.tov` cipherFromConfig seals provider key values, virtual key values, and the admin password and token with AES-256-GCM. The key is PBKDF2-HMAC-SHA256 (100,000 rounds, fixed salt); Bifrost uses Argon2id, so sealed files do not open in the other product. `env.NAME` is allowed. (commits ae6f1db, G39) |
| setup_token | config.schema.json (top) | done | While no admin account exists, `POST /api/users` needs the `X-Bifrost-Setup-Token` header when setup_token is set (`ops.tov` users, L97g). `/api/session/is-auth-enabled` reports `setup_required` and `setup_token_configured`. env.NAME is allowed. The one-time bootstrap token is not used. |
| server.* (read_buffer_size, a2a_*, plugin_download_*) | config.schema.json server | done (accepted) | Accepted silently (L97g). Raiju takes `-host` and `-port` on the command line; the other keys have no Raiju counterpart. |
| auth_config (admin_username, admin_password, is_enabled, disable_auth_on_inference) | config.schema.json auth_config | done | P0 (G2). `config_compat.tov` mapAuth; `config.tov` AdminAuthConfig. `is_enabled: false` turns admin auth off, and `disable_auth_on_inference` leaves inference open unless `client.enforce_auth_on_inference` says otherwise. |
| client.* | config.schema.json client | partial | See c2. |
| providers.* | config.schema.json providers | partial | See c3. |
| governance.* | config.schema.json governance | partial | See c4. |
| alerting | config.schema.json alerting | done | `config_compat.tov` mapAlerting; rules as CEL (commit 8e98ea5). history_retention_days and webhook_network are reported as ignored. |
| webhooks[] | config.schema.json webhooks | done | `config.tov` WebhookEndpoint; `webhooks.tov` (Standard Webhooks signing, retries, `allow_private_network`). Deliveries are kept (at most the last 500; persisted with logs_store, L97i) and older than `client.webhook_config.delivery_history_retention_days` (default 30, L97g). |
| agents[] | config.schema.json agents | out-of-scope | The agent gateway (A2A) is in SCOPE.md Out. Reported as ignored (`config_compat.tov` noteTable). |
| mcp.* | config.schema.json mcp | partial | See c5. |
| vector_store | config.schema.json vector_store | partial | Types qdrant, redis, weaviate, pinecone and chromem are mapped (`config_compat.tov` mapVectorStore; G30). Bifrost's connection-pool and timeout fields are reported as ignored (L97g LIMITS). A type outside this list is dropped, and the semantic cache keeps entries in memory. |
| config_store (sqlite, postgres) | config.schema.json config_store | partial | Raiju saves its config as a JSON file (the file given by `-config`), with a `.bak` (`store.tov`). `config_store` is reported as not used. sqlite and postgres are missing. |
| logs_store.* | config.schema.json logs_store | partial | Raiju's own block: enabled, dir, retention_days, max_memory_entries, content_logging (`config.tov` LogsStoreConfig; `logstore.tov` prunes by retention_days). Bifrost's `type` (sqlite, postgres, clickhouse) and `config` are not used. Log sinks are configured as plugins or Raiju's `log_exports` and `exporters` (see plugins[]). |
| skills_registry | config.schema.json skills_registry | out-of-scope | The skills marketplace is in SCOPE.md Out (L88). Reported as ignored. |
| plugins[] | config.schema.json plugins | partial | Mapped by `config_compat.tov` mapPlugins: otel, logging, telemetry, governance, routing, compat, prompts, semantic_cache (or semanticcache), and the sink plugins bigquery, pubsub, kafka and maxim (`mapSinkPlugin`, which turns them into exporters). Other names are reported as unknown and not loaded. |
| websocket | config.schema.json websocket | missing | Reported as accepted but not applied: Raiju's WebSocket limits are fixed in `src/ws.tov`. L101/L102 in flight: the multi-worker live registry and /ws (L102) change this row when it merges. |
| guardrails_config | config.schema.json guardrails_config | done | `guardrails_compat.tov`; `main.tov` withBifrostGuardrails (commit 0c999ff). L101/L102 in flight: the secrets engine (L101: capture groups, entropy filter, allowlists and generic-api-key) changes this row when it merges. The full Gitleaks set is in place from L93. |
| audit_logs | config.schema.json audit_logs | partial | Read as `audit` (`config_compat.tov` mapAudit). retention_days, omit_ip_addresses, archive_interval, archive_grace_period, archive_max_object_bytes and object_storage are reported as ignored (L97g LIMITS). |
| cluster_config | config.schema.json cluster_config | partial | Read as `cluster` (`config_compat.tov` mapCluster). `type: broker` is supported as Raiju's HTTP relay (`-mode broker`, L94), not Bifrost's gRPC relay. Discovery and leader election are in (L87, L92, L94). region, gossip and grpc are reported as ignored. |
| load_balancer_config | config.schema.json load_balancer_config | partial | Mapped into `health.adaptive` (`config_compat.tov` mapHealth). tracker_config, bootstrap, direction_selection_enabled, append_fallbacks_to_pinned, reroute_failed_directions and prune_failed_fallbacks are reported as ignored (L97g LIMITS). |
| circuit_breaker_config | config.schema.json circuit_breaker_config | done | Mapped to `health.circuit_breaker` (`config_compat.tov` mapHealth). Breaker policies (`circuit_breaker_policies`, L91) are Raiju's own. |
| large_payload_optimization | config.schema.json large_payload_optimization | missing | Reported as not implemented. Raiju buffers request bodies up to `client.max_request_body_size_mb` (both servers, L97g). Spooling bodies to disk is not built (LIMITS of L97g). P2. |
| scim_config | config.schema.json scim_config | out-of-scope | SCIM is in SCOPE.md Out. |
| access_profiles (top-level) | config.schema.json access_profiles | missing | Reported as not read. Raiju reads `governance.access_profiles`, in its own shape (see c4). P2. |
| feature_flags | config.schema.json feature_flags | done | `config.tov` FeatureFlagsConfig, boot-time overrides of the flags in `flags.tov` (L88). |
| proxy_config (global outbound proxy) | config.schema.json proxy_config | done | `config.tov` GlobalProxyConfig; GET and PUT on `/api/proxy-config`. Used by a provider with no proxy of its own when `enable_for_inference` is set. Bifrost's schema allows only type `http`; other types give no proxy. Startup warning bug: see LIMITS. |
| framework.pricing (pricing_url, pricing_sync_interval) | config.schema.json framework; framework/modelcatalog/config.go:109 (default URL) | partial | `pricing_url` and `pricing_sync_interval` become `pricing_sync` (`config_compat.tov` mapPricing). Sync runs only when a pricing section is set. model_parameters_url, mcp_library_url, mcp_library_sync_interval and live_models_sync_interval are reported as not implemented (L97g LIMITS). |
| Raiju-only top-level keys (cache, prompt_cache, health, pricing, otel, semantic_cache, session_affinity, complexity_router, mcp_server, virtual_mcps, log_exports, exporters, cluster, oidc, alerts, audit, secrets, guardrails, circuit_breaker_policies, prompt_repo, auth_proxy) | not in Bifrost (several correspond to Bifrost sections above) | done (Raiju-only) | `config.tov` Config type. Bifrost configs that use the Bifrost names for these will not load into the Raiju fields. |

### c2. client.*

Bifrost: `transports/config.schema.json` `$defs/client` (and `client.*` properties). Raiju: `ClientConfig` in `src/config.tov`, the mapping in `src/config_compat.tov` (`mapClient`, `mapGovernancePlugin`, `mapLogging`), and the consumers named below.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| allowed_origins | client.allowed_origins | done | `server.tov` cors. |
| enable_logging | client.enable_logging | done | `config.tov` ClientConfig; read in `gateway.tov`. |
| enforce_governance_header | client.enforce_governance_header | partial | `governance.tov` govConfig. Gates the VK requirement when enforce_auth_on_inference is unset (its older name in Bifrost), default false. |
| enforce_auth_on_inference | client.enforce_auth_on_inference | done | Read as the gate (`governance.tov` govConfig, commit 32da2e6). When unset, it is on when any credentials exist. |
| required_headers | client.required_headers | done | `governance.tov` govConfig. |
| max_request_body_size_mb | client.max_request_body_size_mb | done | `main.tov` passes it to both servers: http1 (`startFront`) and Bun (`server.tov` limitedBody: a declared length or the read body over the limit gets a 413; L97g). |
| async_job_result_ttl | client.async_job_result_ttl | done | `server.tov` dispatch (the `/v1/async/*` TTL). The per-request header is missing (see b1). |
| mcp_agent_depth | client.mcp_agent_depth | done | `gateway.tov` Engine constructor; `agent.tov` (the depth limit for the tool loop). |
| mcp_tool_execution_timeout | client.mcp_tool_execution_timeout | partial | Mapped to `mcp.tool_execution_timeout_seconds` (`config_compat.tov` mapClient). That is a single global timeout; per-client timeouts are missing. |
| mcp_tool_sync_interval | client.mcp_tool_sync_interval | done | Read as `mcp.tool_sync_interval` (`config_compat.tov` mapClient), the global default (c5). |
| mcp_auto_execute | not in Bifrost (Bifrost: per-client tools_to_auto_execute) | done (Raiju-only) | `gateway.tov` withMcpTools and chat. Per-client `tools_to_auto_execute` is in c5. |
| disable_content_logging | client.disable_content_logging | done | `gateway.tov` contentOff (commit 12757de). |
| prometheus_labels | client.prometheus_labels | done | `metrics.tov` baseValues and customValues (commit cbd6ad3). |
| drop_excess_requests | client.drop_excess_requests | done | `gateway.tov` limitersFor: a full provider queue sheds the request with a 503. A provider with no concurrency_and_buffer_size gets Bifrost's default queue (1000 running, 5000 queued) when this is on (L97g). |
| allow_direct_keys | client.allow_direct_keys | done | `governance.tov` directKeyFrom (gates `x-bf-direct-key`, commit cbd6ad3). |
| allow_per_request_raw_override | client.allow_per_request_raw_override | done | `gateway.tov` sendBackRaw. |
| allow_per_request_content_storage_override | client.allow_per_request_content_storage_override | done | `gateway.tov` contentOff and storeRawOn. |
| compat | client.compat | partial | Compat plugin (G37, L82, L100): `compat.tov` settingsOf and withHeader. Streamed-answer headers and native-decision model checks are open (L100). |
| log_retention_days | client.log_retention_days | partial | Read as `logs_store.retention_days` (`config_compat.tov` mapClient). The section is created when it is absent, but the request log is on only with `logs_store.enabled` (L97g). P2. |
| refuse_unpriced_models | client.refuse_unpriced_models (not in Bifrost) | done (Raiju-only) | Owner switch (L95): budgeted requests to an unpriced model are refused with 403. Off by default. `gateway.tov` serveInner. |
| scope_by_virtual_key | cache.scope_by_virtual_key (not in Bifrost) | done (Raiju-only) | Owner switch (L95): the exact-match cache is scoped per virtual key. Off by default. `gateway.tov` serveInner. |
| mcp_disable_auto_tool_inject | not in Bifrost | done (Raiju-only) | `gateway.tov` withMcpTools: MCP tools are added to a chat request only when it names its clients (`x-bf-mcp-include-clients`). |
| extra_fields_placement | client.extra_fields_placement | missing | Reported as not implemented. Body only (see b2). P2. |
| dual_credential_conflict_behavior | client.dual_credential_conflict_behavior | missing | Reported as not implemented: Raiju's identity-token login is OIDC, and an inference request with both a token and x-bf-vk is not checked for the conflict (L97g LIMITS). P2. |
| allowed_headers, header_filter_config, whitelisted_routes | client.* | done | `headerfilter.tov` (header_filter_config: x-bf-eh-* and allowlisted headers, security denylist always on; L97g). `ops.tov` gate (whitelisted_routes: exact paths skip admin login; L97g). allowed_headers: Raiju's CORS allows every request header, so the list adds nothing. |
| logging_headers | client.logging_headers | missing | Reported as not implemented. P2. |
| hide_deleted_virtual_keys_in_filters, delete_expired_virtual_keys, vk_rotation_cooldown, enforce_vk_object_ownership, hidden_request_types | client.* | missing | Reported as not implemented: Raiju has no virtual key rotation or expiry (L97b), does not record which key created a provider object, and the log reads do not filter request types (L97g LIMITS). P2. |
| routing_chain_max_depth | client.routing_chain_max_depth | done | Bounds key alias chains (`aliases.tov` resolveKeyAlias, `router.tov` resolveAlias; default 10). Bifrost's setting is for routing-rule chains, which Raiju takes as its key aliases (L97g). |
| dump_errors_in_console_logs | client.dump_errors_in_console_logs | done | `gateway.tov`: an upstream error response is written to the server console in full (L97g). |
| retain_content_in_object_storage | client.retain_content_in_object_storage | missing | Reported as not implemented. Raiju has no object storage. P2. |
| webhook_config | client.webhook_config | partial | Deliveries are the last 500 (`webhooks.tov`), persisted in the logs_store folder when logs_store is on (L97i). delivery_history_retention_days is applied. The rest of the setting is reported as not implemented. P2. |
| mcp_server_auth_mode, mcp_enable_temp_token_auth, mcp_oauth_private_allowlist, oauth2_server_config | client.* | missing | Reported as not implemented. Raiju's MCP OAuth flow is client-side (L91). P2. |
| mcp_external_client_url, skills_external_client_url | client.* | out-of-scope | The skills marketplace is in SCOPE.md Out (L88). MCP external URLs are reported as not implemented. |
| a2a_external_client_url, a2a_store_raw_request_response | client.* | out-of-scope | A2A agent gateway is in SCOPE.md Out (L88). |
| mcp_code_mode_binding_level, mcp_code_mode_limits | client.* | out-of-scope | MCP code mode is in SCOPE.md Out. Reported as not implemented. |
| initial_pool_size | client.initial_pool_size | n/a | Go connection-pool setting. |
| disable_db_pings_in_health | client.disable_db_pings_in_health | n/a | Raiju has no database. |
| enforce_scim_auth | client.enforce_scim_auth | out-of-scope | SCIM (SCOPE.md Out). |

### c3. providers.*

Bifrost: `$defs/provider`, `base_key`, `network_config`, `custom_provider_config`, `proxy_config`, `azure_key`, `bedrock_key`, `vertex_key`, `openai_config`, `prompt_cache`. Raiju: `src/config.tov` (`KeyConfig`, `NetworkConfig`, `ProxyConfig`, `CustomProviderConfig`, `ProviderConfig`) and `src/config_compat.tov` (`providerChildKeys`, `keyChildKeys`).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| keys[]: name, value, models, weight, aliases | base_key | done | `config.tov` KeyConfig; `router.tov` pickKey. |
| keys[].use_for_batch_api | base_key | done | `media.tov` providerTarget: file and batch routes use only keys with this set; a provider with keys and none flagged answers 404 (L97g). Existing configs need `use_for_batch_api: true` on the keys that serve batches or files. |
| keys[].oauth_key_config | base_key | missing | Reported as not implemented. P2. |
| keys[].azure_key_config (endpoint, deployments, api_version) | azure_key | done | `config.tov` AzureKeyConfig. |
| Azure Entra ID: client_id, client_secret, tenant_id, scopes | azure_key (docs/providers/supported-providers/azure.mdx) | done | `config.tov`; `cloud_auth.tov`. Client credentials, tokens cached (commit 6aeb7f2). |
| bedrock_key_config (access key, secret key, session token, region, deployments) | bedrock_key | done | `config.tov` BedrockKeyConfig. Mantle keys (`bedrock_mantle_key_config`) are read too (2c31e06). |
| Bedrock: role_arn, external_id, session_name | bedrock_key | done | Assumed through STS (`config.tov`, commit 6aeb7f2). |
| Bedrock: inference-profile arn, use_openai_endpoints | bedrock_key | done | `config.tov` BedrockKeyConfig; `providers/bedrock.tov` (the arn joins the model in the URL path; use_openai_endpoints selects OpenAI and xAI endpoints) (commit 2c31e06). |
| Bedrock: batch role and S3 | bedrock_key | done | `media.tov` batch_role; batches and files over S3 (commit e572dc3). |
| vertex_key_config (project_id, region, auth_credentials) | vertex_key | partial | `config.tov` VertexKeyConfig. aws_workload_identity (audience, service_account_email, token_lifetime_seconds) is not implemented: it needs AWS-to-GCP federation with a real cloud account (L97g LIMITS). project_number and force_single_region are not read. |
| watsonx_key_config | not in Bifrost | done (Raiju-only) | `config.tov`. |
| network_config: base_url, extra_headers, default_request_timeout_in_seconds, max_retries, retry_backoff_initial, retry_backoff_max | network_config | done | `config.tov` NetworkConfig; `router.tov`. |
| network_config: insecure_skip_verify, ca_cert_pem | network_config | done | `providers/types.tov` tlsOf (commit b66cf96). |
| network_config: allow_private_network | network_config | done (no effect) | Accepted. Raiju never blocks private provider addresses, so private addresses are always reachable. |
| network_config: enforce_http2, http2_ping_interval, keep_alive_timeout, max_conns_per_host, stream_idle_timeout, beta_header_overrides | network_config | missing | Reported as not implemented (L97g LIMITS: Tov's fetch exposes none of these knobs, and beta_header_overrides is not built). P2. |
| concurrency_and_buffer_size | provider.concurrency_and_buffer_size | done | `gateway.tov` limitersFor; `limiter.tov` (per-provider concurrency and queue). |
| proxy_config (provider): http with credentials and ca_cert_pem | proxy_config | done | `config.tov` ProxyConfig; `providers/types.tov`. Bifrost's schema allows only type `http`. Other types give no proxy (`proxyOf`). |
| send_back_raw_request, send_back_raw_response | provider.* | done | `gateway.tov` sendBackRaw (commit cbd6ad3). |
| store_raw_request_response | provider.store_raw_request_response | done | `gateway.tov` storeRawOn; overridden per request when `client.allow_per_request_content_storage_override` is on. |
| ignore_provider_cost | provider.ignore_provider_cost | partial | Accepted. Raiju always prices from its own table and never reads the provider's cost, so the setting has no effect (as Bifrost's `true`, but not its `false`). |
| injected_tools | provider.injected_tools | done | `gateway.tov` injectedNames and injectedDef: the provider's MCP tools join each chat request it serves. Needs MCP clients (startup note). |
| custom_provider_config.base_provider_type, is_key_less | custom_provider_config | done | `config.tov`; `router.tov` kindOf. |
| custom_provider_config: request_path_overrides | custom_provider_config | done | `providers/openai.tov` pathOverride. |
| custom_provider_config: allowed_requests | custom_provider_config | done | `gateway.tov` allowedRequest; a fallback takes a request type the provider does not allow. |
| custom_provider_config: does_not_send_done_marker, wait_for_usage | custom_provider_config | done | `gateway.tov` (the stream ends at finish_reason when `does_not_send_done_marker` is set without `wait_for_usage`). |
| openai_config.disable_store | provider.openai_config | done | `providers/openai.tov` (store is forced to false when set). |
| prompt_cache (provider): auto_inject, ttl, cache_control_injection_points | provider.prompt_cache | done (Anthropic) | Raiju has a top-level `prompt_cache.auto_inject` (`config.tov` PromptCacheConfig). Provider-level ttl (5m or 1h) and cache_control_injection_points (message role or index) are applied by `providers/anthropic.tov` messagesBody; a request that carries its own cache_control gets no injected marker (L97g). Other providers ignore them. |

### c4. governance.*

Bifrost: `config.schema.json` governance properties. Raiju: `GovernanceConfig` in `src/config.tov`, consumed by `src/governance.tov` and `src/store.tov`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| budgets, rate_limits, customers, teams, virtual_keys, routing_rules | governance.* | partial | Core fields done. VK `mcp_configs` (`virtual_key_mcp_config`) is read and enforced: `config.tov` VirtualKeyConfig, `mcp.tov` keyRuleAllows and McpManager.allToolsFor/mayRun. A key without the field is not limited, as before. |
| governance.auth_config | governance.auth_config | done | `config.tov` AdminAuthConfig. |
| business_units, projects, roles | governance.* | partial | Business units and projects are done, with x-bf-project-id and x-bf-customer-id (L84). Custom roles are in the management API. Open: project members API, split policies, entity_dac overrides and Bifrost's role-id API shape (L84). |
| access_profiles (governance) | not in Bifrost's governance schema (top-level access_profiles, see c1) | done (Raiju-only) | `profiles.tov` applyProfiles, validateProfile. Raiju's own shape. |
| pricing_overrides | governance.pricing_overrides | done | `store.tov` pricingRoute; config `governance.pricing_overrides` (commit 31f4aaa). |
| model_configs | governance.model_configs | done | `store.tov` modelConfigRoute (commit 31f4aaa). |
| providers (provider-level governance) | governance.providers | done | `store.tov` providerGovRoute (commit 31f4aaa). |
| complexity_analyzer_config | governance.complexity_analyzer_config | partial | Raiju has top-level `complexity_router` (`config_compat.tov` mapComplexityAnalyzer). The governance path is reported as not read. |

### c5. mcp.*

Bifrost: `config.schema.json` `mcp` and `$defs/mcp_client_config`. Raiju: `src/mcp.tov` (`McpClientConfig`, `McpConfig`), `src/mcpapi.tov` (management routes), `src/mcpauth.tov` (auth).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| client_configs[]: name, connection_type (http, sse, stdio), connection_string, headers, stdio_config, tools_to_execute | mcp_client_config | done | `mcp.tov` McpClientConfig; `mcpapi.tov` validates connection_type. |
| connection_type inprocess, openapi | mcp_client_config.connection_type | partial | openapi done: `openapi.tov` and `mcp.tov` McpSession `loadOpenApi`/`callOpenApi`. inprocess is missing. |
| openapi_config | mcp_client_config | partial | `openapi.tov` parseSpec, inputSchema, requestFor, callOperation. JSON 3.x documents from `spec` or `spec_url`; each operation is a tool, with `security_credentials` applied. `$ref` is not resolved, YAML and Swagger 2.0 are refused, and per-operation security and the framework's schema flattening are not done. |
| auth_type: none, headers, oauth | mcp_client_config.auth_type | done | `mcpauth.tov`. oauth is the authorization-code flow with PKCE, dynamic registration and `client_id` (L91). |
| auth_type: per_user_oauth, per_user_headers, token_exchange; per_user_header_keys | mcp_client_config.auth_type | missing | Routes refuse with Bifrost's messages (`mcpapi.tov` verifyRoute). L91 open for per_user_*. P2. |
| tools_to_auto_execute (per client) | mcp_client_config | done | `mcp.tov` (per-client list; `*` for all). Global `client.mcp_auto_execute` is Raiju-only (c2). |
| tools_to_execute | mcp_client_config | done | `mcp.tov` McpClientConfig. |
| endpoint_slug, allow_by_default, allow_on_all_virtual_keys, disabled | mcp_client_config | done | `mcpapi.tov` (CLIENT_KINDS; management API); allow_by_default from L76. |
| is_ping_available, needs_session_stickiness | mcp_client_config | partial | Stored and returned (`mcpapi.tov` CLIENT_KINDS). needs_session_stickiness false makes an http client connect fresh before each call (`mcp.tov` McpSession.callTool); new http clients default to false, as Bifrost. No ping health check runs, so is_ping_available changes nothing. |
| require_public_target (SSRF guard) | mcp_client_config | done | `netguard.tov` targetProblem (private and metadata hosts, shared with webhooks' `urlProblem`), checked in `mcp.tov` McpSession.send and callOpenApi. The host allow list is `mcp.oauth_private_allowlist` (exact hosts; CIDR ranges are not matched). A client registered over the API while dashboard auth is off gets it set (`mcpapi.tov` createClient, `server.tov` passes `!ops.authOn`). |
| tls_config | mcp_client_config | done | `mcp.tov` McpTlsConfig. |
| allowed_extra_headers | mcp_client_config | done | `mcp.tov` McpSession.forwardable: the request headers the allow list names (`*` for all) reach the server on a tool call; `gateway.tov` toolGate and `ops.tov` `mcp` pass the request's headers into McpManager.execute. Framing headers are never forwarded. |
| tool_pricing | mcp_client_config | partial | `mcp.tov` McpManager.priceOf; `gateway.tov` chargeTool debits the caller's budgets (`governance.tov` record) after each successful call, and a tool call is refused with 402 when those budgets are used up (`governance.tov` admitTool). The cost is not written to the MCP log entry (`mcp.tov` McpToolCall has no cost field), and team and customer budgets are debited only when the key is known. |
| tool_execution_timeout (per client) | mcp_client_config | done | `mcp.tov` `durationMsOf` (Go durations, or a bare number of seconds); McpSession's constructor uses it over the global `mcp.tool_execution_timeout_seconds`. Integers are turned into duration strings in `config_compat.tov` clientItems. |
| tool_sync_interval (per client) | mcp_client_config | done | `mcp.tov` refresh timers, one per client (G22, L76). |
| max_instructions_length, is_code_mode_client | mcp_client_config | out-of-scope | MCP code mode is in SCOPE.md Out. |
| mcp.tool_groups | mcp.tool_groups | done | Bifrost's OSS schema calls these enterprise and stores them as virtual MCPs. `config_compat.tov` mapMcp reads each group as a virtual MCP, and its team_ids, customer_ids and provider_names reach the virtual keys they name (groupKeyIds). user_ids and api_key_ids are noted as not applied (Raiju's keys have no user or API key ids). |
| mcp.tool_manager_config | mcp.tool_manager_config | partial | `config_compat.tov` mapToolManager: tool_execution_timeout, oauth_private_allowlist, max_agent_depth and disable_auto_tool_inject are applied. max_instructions_* is noted as not implemented (no instruction forwarding) and code_mode_* as out of scope. |
| mcp.virtual_mcps | mcp.virtual_mcps | done | `config_compat.tov` mapMcp; read as top-level `virtual_mcps` (commit 0c999ff). |
| mcp.tool_sync_interval (global) | mcp.tool_sync_interval | done | `mcp.tov` McpManager.startToolSync: a client's own interval, else this default (`config_compat.tov` also maps the legacy client.mcp_tool_sync_interval). Deviation: with neither set there is no periodic re-list; Bifrost falls back to 10 minutes. |

## (d) Providers

### d1. Provider list

Bifrost: provider constants `core/schemas/bifrost.go:49-82`, and per-provider pages in `docs/providers/supported-providers/`. Raiju: `src/providers/openai.tov` (`makeEndpoints`), `longtail.tov` (`longtailTable`), `index.tov` (`supportsChat`, `supportsEmbeddings`, `supportsDecisions`, `CHAT_ONLY`), `anthropic.tov`, `gemini.tov`, `bedrock.tov`, `bedrock_mantle.tov`, `vertex.tov`, `cohere.tov`, `watsonx.tov`, `typesafe.tov`, `cloudflare.tov`, `databricks.tov`, `githubcopilot.tov`, `replicate.tov`. Routing of files, batches, images, speech and transcription is in `src/media.tov` (`matchRoute`, `providerTarget`, `nativeMedia`, `supported`), `media_native.tov` (Anthropic, Gemini), and `media_cloud.tov` (Vertex, Bedrock).

The notes list only the operations that differ from the "Supported Operations" table in the Bifrost docs. Where a row says a media route is "passed through", the OpenAI-compatible media routes send the request to the provider's own endpoint for any OpenAI-format provider (`media.tov:supported`); that is not checked against each provider's API.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| openai | supported-providers/openai.mdx: chat, responses, responses lifecycle, text, embeddings, decisions, speech, STT, images, image edit, files, batch, videos, compaction, models | partial | Raiju: chat, streaming, responses (lifecycle, compaction, input_tokens), text, embeddings, speech, STT, images (generate, edit, variation), files, batch, realtime, models (`openai.tov:makeEndpoints`, `media.tov:matchRoute`). Decisions: no native OpenAI route. `extras.tov:decisionRoute` answers OpenAI only by emulation, and only when `client.compat.decisions` is on (off by default, `decision_emulate.tov`). Videos out-of-scope. |
| azure | supported-providers/azure.mdx: chat, responses, embeddings, files, images, image edit, models, compaction, decisions, batch | partial | Raiju serves Azure through `openai.tov` and `media.tov` (deployment routes: `deploymentRoute`). Entra ID is done (commit 6aeb7f2). Decisions: emulation only, as for openai. |
| anthropic | supported-providers/anthropic.mdx: chat, responses, text, files, batch, models | partial | Raiju: chat, streaming, responses (bridged), count tokens (exact, `extras.tov:countTokens`), models (`server.tov:upstreamModels`), files and batches (`media_native.tov`, routed by `media.tov:nativeMedia`). Missing: legacy text completions. |
| bedrock | supported-providers/bedrock.mdx: chat, responses, text, embeddings, files, batch, models, images, image edit and variation, count tokens | partial | Raiju: Converse chat and streaming, responses (bridged), embeddings (Titan and Cohere), role_arn, count tokens (exact through Bedrock CountTokens, `extras.tov:bedrockCountTokens`; an estimate where Bedrock cannot count the model), rerank (`extras.tov:rerankText`), files and batches over S3 (`media_cloud.tov:s3Object`, `media.tov:nativeMedia`), image generation (Titan and Stability, `media_cloud.tov:bedrockImage`). Model list: foundation models and inference profiles, SigV4 signed on the control plane (`server.tov:nativeModelIds`, `providers/bedrock.tov:listRequest`; L97h). Missing: legacy text, image edit and variation. |
| bedrock_mantle | supported-providers/bedrock-mantle.mdx: chat (+stream), responses, tool calling, vision, reasoning, structured outputs, prompt caching, models, count tokens | partial | Chat through the Bedrock OpenAI-compatible endpoint (`bedrock_mantle.tov`, commit 6aeb7f2). Anthropic-family models are refused in `bedrock_mantle.tov`. No model list or count tokens. |
| cohere | supported-providers/cohere.mdx: chat, responses, embeddings, models | done | Raiju: chat, streaming, embeddings, native rerank (`extras.tov:rerankText`), responses (bridged). Cohere SDK routes missing (a2). |
| vertex | supported-providers/vertex.mdx: chat, responses, embeddings, images, image edit, video (out), models, text, batch and files through genai routes | partial | Raiju: chat, streaming, embeddings, responses, images (Imagen and Gemini image models, `media_cloud.tov:vertexImage`), batches and files over GCS (`media_cloud.tov:vertexJobCreate`, `gcsUpload`). Count tokens are exact for Claude (count-tokens:rawPredict) and Gemini (:countTokens) (`providers/vertex.tov:countRequest`, `extras.tov:countTokens`; L97h). Model list: the google, anthropic and mistralai publishers, every page (`server.tov:nativeModelIds`; L97h). Missing: image edit. |
| mistral | supported-providers/mistral.mdx: chat, responses, STT, OCR, embeddings, models | done | Raiju: OpenAI-compatible (`openai.tov:makeEndpoints`); STT and OCR routed through `media.tov`. |
| ollama | supported-providers/ollama.mdx: chat, responses, text, embeddings, models, decisions | done | Raiju: `openai.tov:makeEndpoints`. Decisions by emulation only, under `client.compat.decisions`. |
| opencode-go | supported-providers/opencode.mdx: chat, responses, models | done | OpenAI-compatible base (`longtail.tov:longtailTable`). |
| opencode-zen | supported-providers/opencode.mdx: chat, responses, models | done | OpenAI-compatible base (`longtail.tov:longtailTable`). |
| groq | supported-providers/groq.mdx: chat, responses, models | done | `openai.tov:makeEndpoints`. |
| sgl | supported-providers/sgl.mdx: chat, responses, text, embeddings, models, count tokens | done | `openai.tov:makeEndpoints`. Count tokens estimated. |
| parasail | supported-providers/parasail.mdx: chat, responses, models, embeddings | done | `openai.tov:makeEndpoints`. |
| perplexity | supported-providers/perplexity.mdx: chat, responses, models, decisions | done | `openai.tov:makeEndpoints`. Decisions by emulation only, under `client.compat.decisions`. |
| cerebras | supported-providers/cerebras.mdx: chat, responses, text, models | done | `openai.tov:makeEndpoints`. |
| deepseek | supported-providers/deepseek.mdx: chat, responses, text, models | done | `openai.tov:makeEndpoints`. |
| gemini | supported-providers/gemini.mdx: chat, responses, speech, STT, images, image edit, video (out), embeddings, files, batch, models, count tokens | partial | Raiju: chat, streaming, responses, embeddings, count tokens (exact), models (`server.tov:upstreamModels`), speech (`media_native.tov:geminiSpeech`), STT (`media_native.tov:geminiTranscription`, audio sent inline), images (`media_native.tov:geminiImageGeneration`, Imagen and Gemini image), files and batches (`media_native.tov`). Missing: image edit. Video out-of-scope. |
| github-copilot | supported-providers/github-copilot.mdx: chat, responses, models | partial | Chat through a Copilot token or a GitHub App (`githubcopilot.tov`). Chat only (`CHAT_ONLY` in `index.tov`). Model listing is missing (`server.tov:upstreamModels` covers OpenAI-compatible, Anthropic and Gemini only). |
| huggingface | supported-providers/huggingface.mdx: routes to 19 inference backends (fal-ai, hf-inference, cerebras, sambanova and others) with chat, embeddings, speech, transcription and image operations | partial | Raiju uses only the single Hugging Face router as an OpenAI-compatible endpoint (`longtail.tov:longtailTable`). No multi-backend routing and no model aliasing. Speech and images reach the router only through the OpenAI-compatible media routes. |
| nebius | supported-providers/nebius.mdx: chat, responses, text, embeddings, images, models | done | `openai.tov:makeEndpoints`. |
| xai | supported-providers/xai.mdx: chat, responses, text, images, compaction, models | partial | Raiju: `openai.tov:makeEndpoints`; images through the media routes. Missing: xAI realtime (Raiju realtime is OpenAI and Azure only, `realtime.tov`). Compaction missing. |
| replicate | supported-providers/replicate.mdx: chat, responses, text, images, image edit, video (out), files, models | partial | Chat only, as synchronous predictions (`replicate.tov`, `CHAT_ONLY` in `index.tov`). Text, images, image edit, files and models are missing. |
| openrouter | supported-providers/openrouter.mdx: chat, responses (beta), text, embeddings, models, decisions | partial | OpenAI-compatible base (`openai.tov:makeEndpoints`): chat, responses, text, embeddings, models. Decisions native: `providers/openrouter.tov:decisionUpstream` posts to `/alpha/decisions` with the safety identifier as `user` (`extras.tov:decisionRoute`; L97h). Missing: the billed cost on usage, and the decision models in the listing (`/v1/models?output_modalities=decisions`). Not in the table before this audit. |
| vllm | supported-providers/vllm.mdx: chat, responses, text, embeddings, rerank, STT, count tokens, models, OCR | done | OpenAI-compatible (`openai.tov:makeEndpoints`). Rerank calls vLLM's rerank API (`extras.tov:rerankText`). Count tokens are estimated, as for sgl. |
| runway | supported-providers/runway.mdx: video only | out-of-scope | `SCOPE.md` Out: videos, media providers. |
| runware | supported-providers/runware.mdx: image, video, other media tasks | out-of-scope | `SCOPE.md` Out: media providers. |
| fireworks | supported-providers/fireworks.mdx: chat, responses, text, embeddings, models, count tokens | done | `openai.tov:makeEndpoints`. Count tokens are an estimate (`extras.tov:countTokens`), not Fireworks' own counter. |
| sarvam | supported-providers/sarvam.mdx: chat, responses, speech, STT, models, text, embeddings | partial | Chat only, through the OpenAI-compatible endpoint (`longtail.tov:longtailTable`). Speech and STT are sent to that endpoint by the media routes, not checked against Sarvam's API. Text, embeddings and models are missing. |
| wafer | supported-providers/wafer.mdx: chat, responses, text, file upload, models | partial | Chat only (`longtail.tov:longtailTable`, `CHAT_ONLY`). File upload, text and models are missing. |
| databricks | supported-providers/databricks.mdx: chat, responses, embeddings, models, decisions | partial | Chat and embeddings (`databricks.tov`; `supportsChat`, `supportsEmbeddings`). Decisions by emulation only, under `client.compat.decisions`. Model listing is empty by design, as Bifrost's is (`server.tov:nativeList`, Bifrost `databricks/models.go`; L97h). |
| cloudflare | supported-providers/cloudflare.mdx: chat, responses, embeddings, decisions, models, rerank | partial | Chat and embeddings (`cloudflare.tov`). Rerank not built: Bifrost's cloudflare.mdx marks it "Not yet", so Raiju refuses it as it refuses other providers without rerank (`extras.tov:rerankText`). Decisions by emulation only. Model listing: the Workers AI search, text generation and embeddings models (`server.tov:nativeModelIds`, `model_list.tov:cloudflarePage`; L97h). |
| typesafe | supported-providers/typesafe.mdx: decisions, models | done | `typesafe.tov`: `/v1/decisions` and `/typesafe/v1/systemone` (`extras.tov:decisionRoute`), and `/typesafe/v1/models`. Chat is refused (`index.tov`). Commit 4c6eacb (L81). |
| elevenlabs | supported-providers/elevenlabs.mdx: speech, sound effects, STT, models, realtime | out-of-scope | `SCOPE.md` Out: media providers. |
| Raiju-only providers: together, lmstudio, nvidia, sambanova, deepinfra, novita, hyperbolic, lambda, moonshot, zhipu, dashscope, ai21, upstage, baseten, featherless, inception, friendli, siliconflow, github (GitHub Models), watsonx | not Bifrost constants (Bifrost reaches OpenAI-compatible endpoints through custom providers) | done (Raiju-only) | `openai.tov:makeEndpoints`, `longtail.tov:longtailTable`, `watsonx.tov`. Each is an OpenAI-compatible base URL plus prefix. |
| custom OpenAI-compatible providers | custom_provider_config | done | `config.tov`, `router.tov`. See c3 for the missing options. |

### d2. Operations across providers

Bifrost: `core/schemas/bifrost.go:135-200` (request types), `core/providers/<name>/` (implementations). Raiju: `src/providers/index.tov` (chat and embeddings dispatch), `src/extras.tov` (rerank, count tokens, decisions), `src/media.tov` and its cloud and native modules (files, batches, images, speech, transcription).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Chat completions (non-stream) | core/providers | done | `index.tov:supportsChat` and the chat dispatch in `index.tov`. |
| Chat completions (stream) | core/providers | done | `index.tov` dispatch; `server.tov` and `front.tov`. Native SSE for OpenAI-format and Azure; converted for Anthropic, Gemini, Bedrock, Cohere, Vertex (`streams.tov`, `streams_cohere.tov`). |
| Text completions | ChatCompletion-style text (text_completion) | partial | OpenAI-format providers only (`gateway.tov`, text completion route). |
| Responses API (create) | responses | done | Native OpenAI, translated others (`native.tov`). |
| Responses lifecycle (retrieve, delete, cancel, input_items) | responses_retrieve, responses_delete, responses_cancel, responses_input_items | done | `media.tov:matchRoute` (commit 12757de). OpenAI and Azure. |
| Responses input_tokens and compaction | responses_* | done | `media.tov:matchRoute` (commit 12757de). |
| Responses over WebSocket (GET /v1/responses upgrade) | responses (wsresponses.go) | partial | `wsresponses.tov:ResponsesSocket`: each response.create runs the responses path; events go out after the upstream finishes, not as they arrive. response.cancel missing. L101/L102 in flight. |
| Live sessions (WebSocket and WebRTC create) | livesession.go, livecontrol.go, wslive.go, webrtclive.go | partial | `live.tov:LiveSocket`: GPT Live over WebSocket, OpenAI only; attach and content restricted to the owning virtual key. Other providers, and POST /v1/live/sessions (WebRTC create), missing. L101/L102 in flight. |
| Embeddings | embedding | done | `index.tov:supportsEmbeddings` and `embeddingsUpstream`. Anthropic has no embeddings upstream in Bifrost either. |
| Speech (TTS) | speech, speech_stream | partial | OpenAI-compatible (pass-through), Azure and Gemini (`media_native.tov:geminiSpeech`). Other native providers are not routed. |
| Transcription (STT) | transcription, transcription_stream | partial | OpenAI-compatible (pass-through), Azure and Gemini (`media_native.tov:geminiTranscription`). Streamed transcription missing. |
| Images (generate, edit, variation) | image_generation, image_edit, image_variation | partial | Generation: OpenAI-compatible, Azure, Gemini (Imagen and Gemini image), Vertex (`media_cloud.tov:vertexImage`), Bedrock (`media_cloud.tov:bedrockImage`). Edits and variations: OpenAI-compatible and Azure only. |
| Files | file_upload, file_list, file_retrieve, file_delete, file_content | partial | OpenAI-compatible, Azure, Anthropic, Gemini, Vertex (GCS) and Bedrock (S3) (`media.tov:nativeMedia`, `media_cloud.tov`). Cohere missing. |
| Batches | batch_create, batch_list, batch_retrieve, batch_cancel, batch_results, batch_delete | partial | OpenAI-compatible, Azure, Anthropic, Gemini, Vertex and Bedrock. The results route is served (`media.tov:matchRoute`, `batches/{id}/results`). Cohere missing. batch_delete: not in the route table. |
| Rerank | (provider rerank) | done | Cohere, vLLM and Bedrock natively (`extras.tov:rerankText`). `raiju/lexical` is a local lexical ranking (`extras.tov`). Others error. |
| Count tokens | count_tokens | partial | Exact for Anthropic, Gemini and Vertex (`extras.tov:countTokens`, `providers/vertex.tov:countRequest`) and for Bedrock models Bedrock can count (`extras.tov:bedrockCountTokens`). Estimated elsewhere, marked `"exact": false`. G33. |
| List models | list_models | partial | Upstream listing for OpenAI-format, Anthropic and Gemini (`server.tov:upstreamModels`), and for Bedrock, Vertex and Cloudflare (`server.tov:nativeModelIds`, L97h). Databricks lists none, as Bifrost does. Typesafe lists its own models. Others return the configured models only. |
| Retrieve model | model_retrieve | partial | Route exists (`server.tov:retrieveModel`). Returns a stub with `listed`, not provider metadata. Bedrock and Vertex have no retrieve in Bifrost (`ModelRetrieve` is unsupported in `bedrock/bedrock.go` and `vertex/vertex.go`), so they answer from the list. |
| OCR | ocr | done | Mistral and OpenAI-compatible (`media.tov`). |
| Realtime (WebSocket) | realtime (provider-specific) | partial | OpenAI and Azure only (`realtime.tov`). L101/L102 in flight covers live sessions for more providers, not this route. |
| Realtime (WebRTC, client secrets, sessions) | realtime calls and client secrets | partial | Client secrets, sessions and SDP calls are routed (`media.tov:matchRoute`, `/v1/realtime/*`, commit 12757de), OpenAI-compatible providers. WebRTC create on `/v1/live/sessions` is missing (L101/L102 in flight). |
| Videos and containers | video_*, container_* | out-of-scope | `SCOPE.md` Out. |
| Passthrough (raw upstream proxy) | Passthrough, PassthroughStream | partial | Six of seven prefixes (`passthrough.tov:PASS_ROUTES`, commit 6b82d47). `/runware_passthrough` is missing (media provider, out of scope). |
| Decisions | Decision (typesafe, openai, openrouter, cloudflare, databricks, perplexity, ollama) | partial | Native route for TypeSafe and custom providers on the TypeSafe base format (`extras.tov:decisionRoute`, `providers/typesafe.tov`, L81), and OpenRouter's `/alpha/decisions` (`providers/openrouter.tov`, L97h; billed cost not carried to usage). Other providers answer only by emulation under `client.compat.decisions` (`decision_emulate.tov`, off by default). Unprefixed `/decisions` routes and decision pricing overrides open (L81). |
| Async jobs | core/schemas/async.go | done | See a1. |
| Prompt caching (automatic injection) | prompt_cache.auto_inject, cache_control_injection_points | partial | Anthropic and Bedrock auto-inject (`anthropic.tov`, `bedrock.tov`; SCOPE). `cache_control_injection_points` is read and reported, not applied (`config_compat.tov`). |
| Reasoning / thinking parameters | docs/providers/reasoning.mdx (provider conversions) | done | `reasoning.tov`, `providers/anthropic.tov`, `gemini.tov`, `bedrock.tov` (commit ac4bf4f). |
| Retries with backoff and Retry-After | network_config.max_retries and backoff | done | `router.tov`, `gateway.tov` (retry loop). |
| Fallback chains | fallbacks in request, routing rules | done | `router.tov`, `cel.tov`, `gateway.tov`. |
| Weighted key balancing and per-key model lists | keys[].weight, keys[].models | done | `router.tov` (weighted pick), `keyAllows` (`router.tov`). |
| Key pinning | x-bf-api-key, x-bf-api-key-id | done | `gateway.tov`. |
| Session affinity | x-bf-session-* | done | `affinity.tov`. |
| Model aliases (static, per key) | keys[].aliases | done | `config.tov` KeyConfig.aliases; `router.tov`. |
| Model aliases (dynamic, scoped, chained) | docs/providers/aliasing-models.mdx | partial | Chained key aliases with cycle and depth checks (`aliases.tov`, commit ebc25c7). Dynamic and scoped aliases are missing. |
| Default provider resolution for unprefixed names | docs/providers/provider-routing.mdx (model catalog) | done | `router.tov`: key model lists, then the model family, then the model catalog (commit ebc25c7). Bifrost's modelcatalogresolver plugin is this behaviour (see e). |
| Custom pricing and model catalog sync | framework/modelcatalog; docs/providers/custom-pricing.mdx | partial | Built-in datasheet (`pricing_data.tov`). Sync from a URL when configured (`ops.tov`). Pricing overrides exist (see f). Models outside the datasheet cost 0 with a warning; `client.refuse_unpriced_models` (L95) refuses budgeted requests to them, off by default. |

## (e) Plugins

Bifrost: `plugins/<name>/main.go` (plugin names at `PluginName` constants). Raiju: plugin chain and built-in plugins in `src/plugins.tov` (`makePlugin`, `buildChain`); Bifrost plugin config is mapped by `src/config_compat.tov` (`mapPlugins`); feature code in `src/`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| governance plugin | plugins/governance (store.go, resolver.go, tracker.go, mcp.go) | done (built in) | `governance.tov`, `profiles.tov`, `rbac.tov`. Built in rather than loaded as a plugin; its config maps onto the client section. |
| logging plugin | plugins/logging (writer.go, costrecalc.go, live.go) | partial | `logstore.tov` (JSONL files, in-memory index, analytics, MCP logs), `gateway.tov` (log writes). The live feed is the `/ws` UI socket (`ops.tov`, `ws.tov`), scoped by data access. Missing: cost recalculation (`POST /api/logs/recalculate-cost`, costrecalc.go) and a SQL store (Raiju's is files). The multi-worker /ws registry is L101/L102 in flight. |
| telemetry plugin (Prometheus) | plugins/telemetry/main.go | partial | Families and labels follow Bifrost (`metrics.tov`). Enrichment labels are recorded. The routing-classifier families and the push gateway are done (L97i, h1). Custom labels on the http_* families and overhead_breakdown_enabled / user_labels_enabled remain. |
| otel plugin | plugins/otel (traces and metrics, gRPC or HTTP, span filters) | partial | Traces and metrics over OTLP HTTP and OTLP gRPC (plaintext h2c; TLS through the ALPN patch, L92) (`otel.tov`, `otel_metrics.tov`, `grpc.tov`). Plugin options `excluded_attributes`, `request_headers` and `disable_content_logging` are applied. Ignored with a note (`config_compat.tov`): `plugin_span_filter`, `export_overhead_spans`, `trace_type`, `overhead_breakdown_enabled`, `group_traces_by_session`, `disable_root_span_content`. |
| maxim plugin | plugins/maxim | partial | Mapped to the Maxim log sink (`sink_maxim.tov`, L89; `config_compat.tov` maps `plugins[maxim]`). Traces and generations are pushed to the SDK log endpoint. The plugin's own tracing hooks are not built. Not in `SCOPE.md`. |
| mocker plugin | plugins/mocker/main.go | partial | `plugins.tov:MockerPlugin` (L97i): Bifrost's rule shape: `name`, `enabled`, `priority` (higher first), `conditions` (`providers`, `models`, `message_regex` through `regex.tov`, `request_size`), `probability`, weighted `responses` (success with `message`, `message_template`, `model`, `usage`, `finish_reason`; error with `status_code`, `type`, `code`), `latency` and `global_latency` (Go duration strings, fixed or uniform), and `default_behavior` (passthrough, error, success). Raiju's own `model`, `contains`, `status`, `response`, `content` and `latency_ms` still work. Missing: faker template variables, `allow_fallbacks` (a plugin error is final), `GetStats`, integer nanosecond durations, and the provider when the request names none (taken from a `provider/model` name only). |
| jsonparser plugin | plugins/jsonparser | partial | `plugins.tov:JsonParserPlugin`: `strip_markdown_fences` only. Other Bifrost plugin options not checked. |
| compat plugin | plugins/compat (convertparams, dropparams, azure, requestcopy) | done | `compat.tov` (settings, Bifrost defaults, x-bf-compat), `decision_emulate.tov`, stream converters in `gateway.tov`. Covers convertparams, dropparams, azure_deepseek, text-to-chat, chat-to-responses, reasoning-only models and decisions (L82, L100). requestcopy.go is an internal clone, not a feature. Open: compat headers on streamed answers, native-decision model checks (L100). |
| modelcatalogresolver plugin | plugins/modelcatalogresolver | done (built in) | The unprefixed-model default provider lookup is in `router.tov` (key model lists, model family, catalog). Not loaded as a plugin. |
| prompts plugin | plugins/prompts | done (built in) | Raiju's prompt repository and deployments (`prompts.tov`, L88). `config_compat.tov` maps Bifrost's prompts plugin onto it. |
| routing plugin | plugins/routing (complexity classifiers, decision models) | partial | CEL variables and RE2 `matches` (`cel.tov`, `regex.tov`). Complexity classifiers heuristic, decision (decision-model, L81), llm and semantic (`complexity.tov`). Missing: chain_rule (Raiju's routing rules do not chain; `config_compat.tov:mapRouting` says so). |
| semanticcache plugin | plugins/semanticcache/main.go | done | `semcache.tov`, with Qdrant, Redis, Weaviate, Pinecone and chromem through `vectorstore.tov` (commits d91ef07, 0d24b99). cache_tool_call_responses and disable_identity_scoping are applied (L77). Options are read by `config_compat.tov`. |
| circuit-breaker (docs/features/plugins/circuit-breaker.mdx) | docs | done | `health.tov`. Config location differs (c1). |
| header plugin (set_request_headers) | not in Bifrost | done (Raiju-only) | `plugins.tov` (`header`). |
| blocklist plugin | not in Bifrost | done (Raiju-only) | `plugins.tov` (`blocklist`). |
| maxtokens plugin | not in Bifrost | done (Raiju-only) | `plugins.tov` (`maxtokens`). |
| Dynamic plugins (Go shared objects, WASM) | docs/plugins/getting-started.mdx, writing-go-plugin.mdx, writing-wasm-plugin.mdx | missing | Raiju plugins are compiled in (`SCOPE.md` notes). P2. |
| Plugin ordering | docs/plugins/sequencing.mdx | partial | `plugins.tov:buildChain`: config order. |

## (f) Governance

Bifrost: `docs/features/governance/*.mdx`, `docs/enterprise/*.mdx`, and `handlers/governance.go`, `virtualkeyrotation.go`, `virtualkeyexpiry.go`, `logvisibility.go`. Raiju: `src/governance.tov`, `src/profiles.tov`, `src/rbac.tov`, `src/pricing.tov`, `src/guardrails.tov`, `src/store.tov` (management routes).

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Virtual keys (create, list, update, delete) | features/governance/virtual-keys.mdx | done | `store.tov` (`handleApi`, virtual-keys routes), `governance.tov`. |
| VK key rotation and cooldown | handlers/governance.go (rotate), virtualkeyrotation.go, vk_rotation_cooldown | partial | Rotate routes and `client.vk_rotation_cooldown` (duration string) done (L97b, see a3). Open: MCP OAuth grant revocation on rotate. |
| VK expiry and expired-key cleanup | virtualkeyexpiry.go; client.delete_expired_virtual_keys | partial | `expires_at` (RFC 3339) on virtual keys, refused with 403 from then on (`governance.tov` `expired`, L97b). Open: the cleanup tick that deletes expired keys (client.delete_expired_virtual_keys is still reported as ignored). |
| VK budgets and rate limits per provider config | budget-and-limits.mdx "Provider-Level Governance" | done | `governance.tov` (provider configs). |
| VK allowed providers and models | routing.mdx "Provider/Model Restrictions" | done | `governance.tov` (provider and model checks). |
| Budgets (USD, reset durations) | budget-and-limits.mdx | done | `governance.tov` (budgets, `durationMs`), `store.tov` (budgets routes). |
| Budget hierarchy: VK, team, customer | budget-and-limits.mdx | done | `governance.tov` (team and customer budgets). |
| Budget hierarchy: business unit, project | enterprise/projects.mdx; teams-business-units-customers.mdx | done | `governance.tov` (business unit and project budgets, L84); `store.tov` (projects and business-units routes). |
| Budget overrides per VK | handlers/governance.go (budget override) | missing | No `/api/governance/virtual-keys/{vk_id}/budgets/{budget_id}/override` routes. P2. |
| Rate limits (request and token windows) | budget-and-limits.mdx | done | `governance.tov` (rate-limit windows). |
| Model limits (model-level budgets and rate limits, scope system) | features/governance/model-limits.mdx | done | `model_configs` (`store.tov`, commit 31f4aaa). |
| Provider-level governance (global) | budget-and-limits.mdx | done | `governance.providers` and `/api/governance/providers` (`store.tov`, commit 31f4aaa). |
| Customers | teams-business-units-customers.mdx | done | `store.tov`; attribution in `governance.tov` (`Attribution`). |
| Teams | teams-business-units-customers.mdx | done | `store.tov`; attribution in `governance.tov`. |
| Required headers (global and per profile) | features/governance/required-headers.mdx | done | `governance.tov` (required headers). |
| Access profiles (reusable permission sets) | enterprise/access-profiles.mdx | partial | `profiles.tov`. No versions, clone, activate or deactivate, role binding, propagate. |
| RBAC (fixed roles) | enterprise/rbac.mdx | partial | `rbac.tov`: built-in roles admin, editor, viewer, auditor. Bifrost's role-id API shape is open (L84). |
| RBAC (custom roles, permission editor) | handlers/governance.go (rbac roles and permissions) | partial | Custom roles under `governance.roles`, holding (resource, operation) pairs (`rbac.tov`, L84), via the management API. Open: Bifrost's role-id API shape. Permission editor UI not checked. |
| Data access control (scopes per role) | enterprise/data-access-control.mdx | partial | Data access scopes on logs and analytics (`logstore.tov`, `ops.tov`, L84). Open: project members API, split policies, entity_dac overrides. |
| Users and tokens | enterprise/user-provisioning.mdx (SCIM excluded) | partial | `rbac.tov`, `ops.tov`. Basic and Bearer user tokens. |
| SSO: generic OIDC (PKCE, groups to roles) | enterprise/setting-up-generic-oidc | done | `oidc.tov`. Provider guides (Okta, Entra, Keycloak, Auth0, Zitadel, Google Workspace) are configurations of the same protocol, not verified individually. |
| SSO: Google and GitHub | features/sso-with-google-github.mdx | n/a | Bifrost marks it "Coming soon". |
| SCIM and user provisioning | enterprise/user-provisioning.mdx | out-of-scope | `SCOPE.md` Out: SCIM. |
| Audit logs (hash chain, HMAC, export, verify) | enterprise/audit-logs.mdx | partial | `audit.tov` (`actionFor`, `maskDetail`, chain, export, verify). Missing: archive to object storage, retention, omit-IP option, per-entity routes. |
| Pricing overrides | governance.pricing_overrides; docs/providers/custom-pricing.mdx | done | `pricing.tov` (installed from `governance.pricing_overrides`), `store.tov` (`/api/governance/pricing-overrides`). Was P1 (G21); the code has it on HEAD. |
| Cost tracking (price table) | docs/providers/custom-pricing.mdx; framework/modelcatalog | partial | Built-in datasheet, overrides and sync (see d2). Models outside it cost 0, and budgets skip them with a one-time warning (`gateway.tov`, `unpriced`). `client.refuse_unpriced_models` (L95) refuses budgeted requests to them with 403; off by default. |
| Complexity analyzer config | governance.complexity_analyzer_config; docs/features/complexity-router.mdx | partial | The routing plugin's analyzer maps to `complexity_router` (`config_compat.tov:mapRouting`). The governance key itself is not read. Classifiers are in `complexity.tov` (see e). |
| Adaptive load balancing (weights, held keys, incidents, API) | enterprise/adaptive-load-balancing.mdx | partial | `health.tov`: weights. No held-keys or incidents API. |
| Circuit breaker policies (API) | enterprise/circuit-breaker.mdx | partial | Policies in config and API, persisted, with breaker reset and policy rerouting (`health.tov`, `ops.tov`, L91). Open: per-key sub-circuits. |
| Routing rules (CEL) | providers/routing-rules.mdx | done | `cel.tov` with Bifrost's variables, and RE2 `matches` (`regex.tov`, commit abf4dbb). |
| Projects | enterprise/projects.mdx | done | `store.tov` (`/api/governance/projects`), `governance.tov` (access_rule, accounting_mode), `config.tov` (`ProjectConfig`), x-bf-project-id and x-bf-project-name (L84). Open: project members API and split policies. |
| Prompt deployments | enterprise/prompt-deployments.mdx | done | `prompts.tov`: prompt repository and deployments (L88). |
| Alerts on budget and rate-limit usage | enterprise/alerting/alert-rules.mdx (budget_usage_percent, rate_limit_*_usage_percent, cel_expression) | done | `alertapi.tov` and `alerts.tov`: CEL rules over budget and rate-limit usage (commit 8e98ea5). |
| Governance per request: x-bf-customer-id | budget-and-limits.mdx | done | `governance.tov` (attribution from x-bf-customer-id, L84). |
| Virtual key quota view (GET /api/governance/virtual-keys/quota) | handlers/governance.go | missing | No quota route. P2 (open after L97b). |

## (g) MCP

Bifrost: `docs/mcp/*.mdx`, `handlers/mcp*.go`, `core/mcp`, `config.schema.json` `mcp`. Raiju: `src/mcp.tov`, `src/mcpauth.tov`, `src/mcpapi.tov`, `src/mcpserver.tov`, `src/agent.tov`, `src/vmcp.tov`, `src/guard_mcp.tov`, `src/ops.tov`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| MCP client over HTTP (streamable) | mcp/connecting-to-servers.mdx | done | `mcp.tov`. |
| MCP client over SSE | mcp/connections.mdx | done | `mcp.tov` ("sse" uses the POST transport). |
| MCP client over stdio | mcp/connections.mdx | done | `mcp.tov` (`stdio_config`), one server per worker (SCOPE). |
| MCP client inprocess and OpenAPI-defined servers | mcp/openapi-servers.mdx | partial | OpenAPI done (`openapi.tov`, `mcp.tov` loadOpenApi and callOpenApi, `mcpapi.tov` openapiSpec for GET /api/mcp/client/{name}/openapi-spec). inprocess is missing. |
| Auth: bearer and static headers | mcp/auth | done | `mcpauth.tov`. |
| Auth: OAuth client credentials and refresh token | mcp/auth | done | `mcpauth.tov` (SCOPE: L36). |
| Auth: OAuth authorization code (client-level "oauth", PKCE, dynamic registration) | mcp/gateway-auth.mdx; handlers/mcpoauth2*.go | done | `mcpauth.tov`, `mcpapi.tov:oauthRoute` and `oauthCallback` (L91). Consent is for the client, not per user. |
| Auth: per-user OAuth (per_user_oauth, consent per user) | handlers/mcpsessions.go (per-user flows), mcpoauth2consent.go | missing | No per_user_oauth type; `mcpapi.tov` refuses reauthorize for it. No `/api/oauth/per-user/flows` routes. P2. |
| Auth: per-user headers | handlers/mcpheaders.go | missing | No per_user_headers type; `mcpapi.tov` refuses verify-headers. No `/api/mcp/per-user-headers/flows` routes. P2. |
| Auth: token exchange | mcp/auth; mcp_client_config.auth_type | missing | No token_exchange type; `mcpapi.tov` refuses verify-exchange. P2. |
| Temporary MCP tokens (client.mcp_enable_temp_token_auth) | handlers/temptokens.go | missing | Reported as ignored (`config_compat.tov`). P2. |
| Tool filtering: per client (`tools_to_execute`) | mcp/filtering.mdx Level 1 | done | `mcp.tov`. |
| Tool filtering: request headers (include clients) | mcp/filtering.mdx Level 2 | partial | x-bf-mcp-include-clients only. Missing: x-bf-mcp-include-tools. |
| Tool filtering: virtual key allow-lists | mcp/filtering.mdx Level 3 | partial | VK `mcp_configs` enforced in the tool list and at execution (`mcp.tov` mayRun, `gateway.tov` toolGate). A key that declares no mcp_configs is not limited (Bifrost denies it by default; kept as before). Access profiles take `mcp_configs` and `virtual_mcps`; projects' mcp_configs are not applied. Access profiles also keep `mcp_tools` (`profiles.tov`, `config.tov`). |
| Tool filtering: tool groups | config.schema.json mcp.tool_groups (no docs page) | done | `config_compat.tov` mapMcp and `mcpapi.tov` toolGroupRoute (`/api/mcp/tool-groups`, an alias of the virtual MCPs with the group's association fields). |
| Tool execution endpoint | handlers/mcpinference.go | done | `server.tov` (`/mcp` tool execution), `ops.tov`. |
| Agent mode (gateway runs allowed tool calls) | mcp/agent-mode.mdx | done | `agent.tov`; `gateway.tov` (agent loop). Per-client config differs (client-level `mcp_auto_execute`). |
| Tool execution timeout | mcp/tool-execution.mdx | done | `mcp.tov` (`tool_execution_timeout_seconds`), `config.tov`. |
| Gateway as MCP server (POST /mcp) | mcp/overview.mdx; handlers/mcpserver.go | done | `ops.tov` (`mcp`), `mcpserver.tov`. |
| Gateway as MCP server (SSE GET) | handlers/mcpserver.go | missing | `mcpserver.tov` has no GET stream. P2. |
| Virtual MCPs (named tool sets, renamed tools) | mcp/virtual-mcps.mdx | done | `vmcp.tov` (config-defined), `/mcp/{name}`. |
| Virtual MCPs management API | handlers/virtualmcp.go | done | CRUD and virtual-key attach and detach at `/api/mcp/virtual-mcps` (`mcpapi.tov`, commit 5c2c8af). |
| MCP sessions (list, reauth, revoke) | mcp/sessions.mdx; handlers/mcpsessions.go | missing | No `/api/mcp/sessions` routes. P2. |
| MCP logs (/api/mcp-logs) | handlers/logging.go | done | `logstore.tov` (MCP analytics), `ops.tov` (L79). |
| MCP client management API | handlers/mcp.go | partial | CRUD, reconnect, refresh-tools and openapi-spec (`mcpapi.tov`, commit 5c2c8af). Verify, reauthorize and reregister answer Bifrost's refusal for client types they do not apply to; per_user_* and token exchange are missing. |
| MCP OpenAPI import and preview | handlers/mcpopenapi.go | partial | `openapi.tov` and `mcpapi.tov` openapiRoute (POST /api/mcp/openapi/preview). JSON 3.x only; the library and the framework's schema flattening are not done. |
| MCP tool sync interval (periodic re-list) | mcp_client_config.tool_sync_interval | done | `mcp.tov` (`syncSeconds`, `startToolSync`; L76). Per client, and the global `mcp.tool_sync_interval` as the default. |
| MCP as an OAuth authorization server for MCP clients | mcp/gateway-auth.mdx; handlers/mcpoauth2issuance.go | missing | `mcpauth.tov` only consumes discovery documents; no issuance, consent or JWT routes. P2. |
| MCP guardrails (tool-call guard) | enterprise/guardrails.mdx "MCP Guardrails" | done | `guard_mcp.tov`, wired into the gateway (L86, L90). |
| MCP code mode | mcp/code-mode.mdx | out-of-scope | `SCOPE.md` Out: MCP code mode. |
| MCP SSRF guard (require_public_target) | mcp_client_config.require_public_target | done | `netguard.tov` targetProblem, used by `mcp.tov` McpSession.send and callOpenApi (see c5). |
| MCP pricing per tool | mcp_client_config.tool_pricing | partial | Charged to the key's budgets (see c5, tool_pricing). The cost is not in the MCP log. |

## (h) Observability

Bifrost: `plugins/telemetry/main.go` (metric definitions at lines 420-694), `core/schemas/enrichment.go` (label dimensions at lines 53-92), `docs/features/observability/*.mdx`. Raiju: `src/metrics.tov`, `src/gateway.tov` (call sites), `src/logstore.tov`, `src/otel.tov`, `src/otel_metrics.tov`, `src/exporters.tov`, `src/exports.tov`, `src/alerts.tov`.

### h1. Metrics

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| bifrost_upstream_requests_total | telemetry/main.go:459 | done | `gateway.tov`, with the enrichment label set (`metrics.tov`, commit 202c6e6). |
| bifrost_upstream_latency_seconds | telemetry/main.go:467 | done | `gateway.tov`, with `is_success` and the enrichment labels (commit 202c6e6). |
| bifrost_success_requests_total | telemetry/main.go:505 | done | `metrics.tov` (commit 202c6e6). |
| bifrost_error_requests_total (status_code, error_type) | telemetry/main.go:517 | done | `metrics.tov`, with status_code and error_type (commit 202c6e6). |
| bifrost_input_tokens_total | telemetry/main.go:525 | done | `gateway.tov` (token accounting). |
| bifrost_output_tokens_total | telemetry/main.go:533 | done | `gateway.tov` (token accounting). |
| bifrost_cache_hits_total (cache_type) | telemetry/main.go:541 | done | `metrics.tov` `cache_type` label (commit 202c6e6). |
| bifrost_cache_read_input_tokens_total, bifrost_cache_write_input_tokens_total (_5m, _1h) | telemetry/main.go:551-575 | done | `metrics.tov` (commit 202c6e6). |
| bifrost_cost_total | telemetry/main.go:583 | done | `gateway.tov` (cost recording). Values depend on the price table (f). |
| bifrost_routing_embedding_requests_total, bifrost_routing_embedding_cost_total, bifrost_routing_llm_requests_total, bifrost_routing_llm_cost_total | telemetry/main.go:598-627 | done | L97i: `complexity.tov` passes a phase ("request" or "warmup") with each classifier call; `gateway.tov` `classifierCall` and `recordClassifier` record the call and its price; `metrics.tov` `observeRoutingEmbedding` and `observeRoutingLLM`. The decision model is not counted (Bifrost has no family for it). Raiju's `raiju_routing_decisions_total` is a different family. |
| bifrost_stream_first_token_latency_seconds, bifrost_stream_inter_token_latency_seconds | telemetry/main.go:635-644 | done | `metrics.tov` (commit 202c6e6). |
| bifrost_request_retries | telemetry/main.go:653 | done | `gateway.tov` records the retries spent on each provider. |
| bifrost_key_rotation_events_total | telemetry/main.go:667 | done | `metrics.tov:observeRotation`, called from the retry loop in `gateway.tov` (L76 and the rotation work). |
| bifrost_active_requests | telemetry/main.go:675 | done | `gateway.tov` (in flight from routing until the answer, `metrics.tov`). |
| bifrost_provider_key_up | telemetry/main.go:683 | done | `metrics.tov:observeKeyUp`, called from `gateway.tov` after each attempt. |
| bifrost_mcp_client_operation_duration_seconds | telemetry/main.go:694 | done | `gateway.tov` (per tool call, `metrics.tov`). |
| bifrost_overhead_latency_microseconds | telemetry/main.go:479 | done | `metrics.tov`, with labels (commit 202c6e6). |
| bifrost_overhead_component_microseconds | telemetry/main.go:496 | done | `gateway.tov` records the components into `metrics.tov`, with `overhead_component` (L79). |
| http_requests_total, http_request_duration_seconds, http_request_size_bytes, http_response_size_bytes (path, method, status) | telemetry/main.go:420-449 | done | Recorded by the front ends (`front.tov`, `server.tov`, commit 0b03e53). |
| bifrost_request_duration_seconds | not defined by the Bifrost telemetry plugin | done (Raiju-only) | `gateway.tov`. |
| raiju_realtime_sessions, raiju_mcp_tool_calls_total, raiju_guardrail_checks_total, raiju_guardrail_findings_total, raiju_routing_decisions_total | not in Bifrost | done (Raiju-only) | `realtime.tov`, `gateway.tov`, `guard_*.tov`, `metrics.tov`. |
| Label dimensions: virtual_key_name, team_name, customer_name, business_unit_name, project_name, selected_key_name, routing_rule_name, complexity_tier, alias, app, fallback_index, and the id variants | core/schemas/enrichment.go:53-92 (MetricSafeEnrichmentDimNames) | done | `metrics.tov:RequestLabels` (L79, L84). |
| Custom labels: x-bf-dim-*, x-bf-prom-*, client.prometheus_labels | lib/ctx.go:443-449; config.schema client.prometheus_labels | done | `metrics.tov` custom labels (commit cbd6ad3, G49). |
| Telemetry push gateway (PUT /metrics/job/<job>/instance/<instance>, push_interval) | telemetry/main.go:1570-1720; docs/features/observability/prometheus.mdx | done | L97i: `pushgateway.tov` (settings, URL, headers with basic auth); `ops.tov` `configurePushGateway` and `pushMetrics` push the `metricsText()` every push_interval. Config is `telemetry.push_gateway`, mapped from `plugins[telemetry].config.push_gateway` by `config_compat.tov` `mapTelemetry`. Gaps: the instance defaults to the HOSTNAME env (Tov has no os.hostname); job and instance must use plain characters (no percent-encoding); no final push at shutdown; the first push comes one interval after start. |
| Default HTTP metric labels (custom labels on http_* families) | telemetry/main.go:387-443 | partial | `metrics.tov` `observeHttp` uses path, method and status only. Custom labels (`client.prometheus_labels`, x-bf-dim-*) are not applied to the http_* families. |
| Profiling endpoints (dev pprof) | handlers/devpprof.go | out-of-scope | Dev-only in Bifrost; not in `SCOPE.md`. |

### h2. Logs and traces

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Request log store (queryable) | plugins/logging; handlers/logging.go | partial | `logstore.tov`: JSONL files and an in-memory index, with analytics (histograms, stats, rankings). Per worker (README "Known gaps"). |
| Content logging: global switch | client.disable_content_logging | done | `logs_store.content_logging` and `client.disable_content_logging` (`gateway.tov`, commit 12757de). |
| Content logging: per request | x-bf-disable-content-logging | done | `gateway.tov` (commit 12757de). |
| Log retention (days) | logs_store.retention_days; enterprise/log-exports.mdx | done | `logstore.tov`. |
| Log sinks: Datadog, Splunk HEC, Elasticsearch, generic HTTP | docs/features/observability/datadog.mdx, splunk.mdx | done | `exporters.tov` (SCOPE). |
| Log sinks: BigQuery, Kafka, Pub/Sub | docs/features/observability/bigquery.mdx, kafka.mdx, pubsub.mdx | done | `sink_gcp.tov` (BigQuery, Pub/Sub), `sink_kafka.tov`, wired by L89. |
| Log sink: Maxim | docs/features/observability/maxim.mdx; plugins/maxim | done | `sink_maxim.tov`, wired by L89. |
| Log exports to S3 and GCS | enterprise/log-exports.mdx | done | `exports.tov`. |
| Log exports: Parquet payloads, retention policy, redaction on export | enterprise/log-exports.mdx | partial | Parquet (`sink_parquet.tov`) and export retention (L85) are done. Redaction (L97i): the content fields already hold the redacted text (`gateway.tov` chatOnce and the output guard); the raw upstream bodies (`raw_request`, `raw_response`) are now redacted too in redact mode (`gateway.tov` `redactRaw`), so exports carry them redacted. Not covered by e2e: a raw response that holds a secret the mock does not echo. Raiju has no logs-only mode. |
| OpenTelemetry traces | plugins/otel; features/otel.mdx | partial | `otel.tov`: OTLP HTTP and gRPC (plaintext h2c; TLS through ALPN, L92), sampling, batching, traceparent (commits 0d269dd, ada3c7e). Span filters missing. |
| OpenTelemetry metrics export | plugins/otel/metrics.go | partial | OTLP push (HTTP JSON and gRPC) of four families: upstream requests and latency, overhead and sessions (`otel_metrics.tov`, commit abf4dbb). Other families are not exported. |
| Latency breakdown (overhead components) | features/observability/latency-breakdown.mdx | partial | `x-bf-overhead-us`, `bifrost_overhead_latency_microseconds` and `bifrost_overhead_component_microseconds` (h1). `overhead_breakdown_enabled` on the otel plugin is ignored (e). |
| Dashboards, histograms and rankings (management API) | handlers/logging.go | done | `logstore.tov` (analytics: histogram, stats, rankings; L79). Routes in `ops.tov`. |
| Cost recalculation (POST /api/logs/recalculate-cost and status routes) | plugins/logging/costrecalc.go; handlers/logging.go | missing | No recalculation route (`ops.tov`, `logstore.tov`). P2. |
| Alerts: webhook and Slack | enterprise/alerting | done | `alerts.tov` (channel type is webhook or slack). |
| Alerts: Microsoft Teams and PagerDuty channels | enterprise/alerting/alert-channels.mdx | done | `alerts.tov` (commit abf4dbb). |
| Alert metrics: budget and rate-limit usage percent, CEL scoping | enterprise/alerting/alert-rules.mdx | done | CEL rules over budget and rate-limit usage (`alertapi.tov`, commit 8e98ea5). |

## (i) Enterprise

Bifrost: `docs/enterprise/*.mdx`, `handlers/notifications.go`, `handlers/webhooks.go`, `handlers/featureflags.go`, `handlers/livesession.go`.

| Feature | Bifrost | Raiju status | Notes |
|---|---|---|---|
| Audit logs | enterprise/audit-logs.mdx | partial | `audit.tov`. See f. |
| RBAC | enterprise/rbac.mdx | partial | `rbac.tov`. Built-in roles and custom roles (L84). See f. |
| Custom roles and data access control | enterprise/data-access-control.mdx | partial | Custom roles and data access scopes done (L84). Open: project members API, split policies, entity_dac overrides. See f. |
| SSO: generic OIDC | enterprise/setting-up-generic-oidc | done | `oidc.tov`. |
| SSO: Google, GitHub | features/sso-with-google-github.mdx ("Coming soon") | n/a | Not GA upstream. |
| SCIM and user provisioning | enterprise/user-provisioning.mdx | out-of-scope | `SCOPE.md` Out: SCIM. |
| Access profiles | enterprise/access-profiles.mdx | partial | `profiles.tov`. See f. |
| Projects | enterprise/projects.mdx | done | `store.tov`, `governance.tov` (L84). See f. |
| Teams, business units, customers | enterprise/teams-business-units-customers.mdx | done | Teams, customers and business units (`store.tov`, `governance.tov`, L84). |
| Prompt deployments | enterprise/prompt-deployments.mdx | done | `prompts.tov` (L88). |
| Virtual MCPs, enterprise access | enterprise/virtual-mcps.mdx | partial | `vmcp.tov`. Config and management API. No access-profile or project scoping. |
| Guardrails: built-in PII detectors | enterprise/guardrails/custom-regex.mdx (PII template) | done | `guardrails.tov` and `guard_regex.tov`: email, phone, ssn, credit_card, ipv4, api_key, aws_key, jwt, private_key (L86). |
| Guardrails: secrets detection (Gitleaks rule set) | enterprise/guardrails/secrets-detection.mdx | partial | `guard_secrets.tov`, rules in `guard_gitleaks_data.tov` (generated from gitleaks v8.30.1, L93). 220 rules are in the table (pkcs12-file, path-only, is not among them). generic-api-key is in the table but skipped at runtime until L101/L102 in flight, so 219 run. The generated file's header says "221 of 222"; it disagrees with the 220 rows and needs regenerating. No entropy filter, allowlists, stopwords or secret-group extraction until L101/L102 in flight. |
| Guardrails: custom regex | enterprise/guardrails/custom-regex.mdx | done | `guard_regex.tov` (`compileRules`, `applyRegex`), used by `guard_local.tov` (L86). |
| Guardrails: redaction modes (runtime, logs only, reversible reveal) | enterprise/guardrails/redaction.mdx | done | `guardrails.tov` (redact, block, log); `guard_reversible.tov` for reversible reveal (L86). |
| Guardrails: prompt guardrails (LLM judge) | enterprise/guardrails/prompt-guardrails.mdx | done | `guard_judge.tov` (L86, L90). |
| Guardrails: Presidio, Azure Language PII, Google Model Armor, CrowdStrike AIDR | enterprise/guardrails.mdx | done | `guardrail_providers.tov` (Presidio `/analyze`, Azure Language PII, Model Armor, CrowdStrike AIDR `guard_chat_completions`; L86). |
| Guardrails: AWS Bedrock Guardrails | integrations/guardrails/aws-bedrock | done | `guardrail_providers.tov`. |
| Guardrails: Azure AI Content Safety | integrations/guardrails/azure-content-safety | done | `guardrail_providers.tov`. |
| Guardrails: Patronus, generic webhook | not in Bifrost docs as listed here | done (Raiju-only) | `guardrail_providers.tov`. |
| Guardrails: streaming output | enterprise/guardrails.mdx "Streaming Output Guardrails" | partial | Output guard on streamed responses (`gateway.tov`). Scope of checks on partial text not verified. |
| Guardrails: MCP tool-call guard | enterprise/guardrails.mdx "MCP Guardrails" | done | `guard_mcp.tov`, wired into the gateway (L86, L90). |
| Secret managers: Vault KV v2, AWS Secrets Manager | enterprise/secret-management.mdx | done | `secrets.tov` (SCOPE). |
| Clustering | enterprise/clustering.mdx | partial | `cluster.tov` (CRDT budget and rate-limit state, HMAC-signed sync), `discovery.tov` (static peers, Kubernetes, DNS, Consul, etcd, mDNS, UDP; L87, L92), `leader.tov` (etcd lease leader lock; Bifrost elects by rank), broker mode (L94; Bifrost's is gRPC). The wire formats for UDP, mDNS and broker mode are Raiju's; Bifrost nodes cannot join a Raiju cluster. |
| Adaptive load balancing | enterprise/adaptive-load-balancing.mdx | partial | See f. |
| Circuit breakers | enterprise/circuit-breaker.mdx | partial | See f. |
| Auth proxies: AWS ALB, Cloudflare ZTNA, generic proxy | enterprise/auth-proxy/*.mdx | done | `authproxy.tov` (`aws-alb`, `cloudflare-access`, `generic`; L87). |
| InVPC deployments | enterprise/invpc-deployments.mdx | n/a | Managed offering. Raiju ships Docker, Helm and Terraform (SCOPE). |
| Self-hosted deployment artifacts | deploy/ (Bifrost helm-charts, terraform) | done | Raiju `deploy/`, `Dockerfile`, `docker-compose.yml` (SCOPE). |
| Warp (log-aware assistant) | features/warp.mdx; handlers/warp*.go | out-of-scope | Not built (L88 decision). Not in `SCOPE.md` yet: add to Out. |
| Skills marketplace | features/skills-repository.mdx; handlers/skills*.go | out-of-scope | Not built (L88 decision). Not in `SCOPE.md` yet: add to Out. |
| Webhooks (signed deliveries, retries, redeliver) | features/webhooks.mdx; handlers/webhooks.go | partial | `webhooks.tov`: Standard Webhooks signing, retries, redeliver (`/redeliver`), async job completion events (L88). Deliveries are the last 500, persisted (L97i) to `webhook-deliveries.jsonl` in the logs_store folder when logs_store is enabled (`DeliveryLog.persistTo`, set in `ops.tov` configure); memory only otherwise. |
| Notifications (in-app) | handlers/notifications.go | done | `notify.tov` (`notifyRoute`): list and create, plus Raiju's own sources (alerts, budget exhaustion, configuration saves). Bifrost's virtual-key-expiry source is absent, as there is no expiry (f). |
| Feature flags | handlers/featureflags.go | done | `flags.tov` (`flagRoute`): config-set flags are locked (409), API values are kept (L88). |
| Agent gateway (A2A) | features/agent-gateway/* | out-of-scope | Not built (L88 decision). Not in `SCOPE.md` yet: add to Out. |
| Sidekiq (Bifrost queue integration) | handlers/sidekiq.go | out-of-scope | Not built (L88 decision). Not in `SCOPE.md` yet. |
| Encryption of stored keys | encryption_key | done | `aesgcm.tov`: AES-256-GCM config encryption at rest (L80). |

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

- **G18. Metric names and label dimensions.** Add `bifrost_success_requests_total`, `bifrost_error_requests_total` (status_code, error_type), `bifrost_stream_first_token_latency_seconds`, `bifrost_stream_inter_token_latency_seconds`, `bifrost_cache_read_input_tokens_total` and `_write_`, and the `http_*` family. Add the enrichment label set (`virtual_key_name`, `team_name`, `customer_name`, `selected_key_name`, `routing_rule_name`, `complexity_tier`, `alias`, `app`, `fallback_index` and the id variants). Keep `raiju_*` as extras. Bifrost: `plugins/telemetry/main.go:420-694`, `core/schemas/enrichment.go:53-92`. Raiju: `src/gateway.tov` call sites, `src/metrics.tov:167-171`. Ledger task. **Status: Partial.** Families and labels done, plus active requests, provider key up, key rotation and MCP duration. Remaining: overhead components (off by default in Bifrost). The routing-classifier families and the push gateway were added in L97i.

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
