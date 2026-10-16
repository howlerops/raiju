# Raiju scope

Bifrost feature parity in detail, with every gap: [docs/parity.md](docs/parity.md).

Priorities chosen in the [scoping form](https://claude.ai/artifact/E4vNoYy3CKL6SjdriReWQr) (P0 first release, P1 next, P2 later, Out not building). Status is what this repository does today. Each row agrees with the status of its features in docs/parity.md (L96d); "partial" rows say what is missing.

## P0

| Feature | Status |
|---|---|
| Chat completions + streaming | done (chunk-by-chunk on the default server) |
| Embeddings | done (OpenAI-format, Cohere, Gemini, Vertex, Bedrock Titan and Cohere) |
| List models | partial: upstream listing for OpenAI-format, Anthropic, Gemini, Bedrock, Vertex and Cloudflare; other providers list their configured models; Databricks lists none, as Bifrost does |
| Realtime | partial: WebSocket relay (OpenAI, Azure); client secrets, sessions and SDP calls pass through; live sessions are OpenAI only; POST /v1/live/sessions (WebRTC create) answers 501 |
| Exact-match cache | done |
| Anthropic SDK route | partial: messages (any provider, streaming), models, message batches and files (passthrough or via an OpenAI-format provider); legacy /anthropic/v1/complete has no streaming yet |
| Bedrock SDK route | done: converse, invoke, converse-stream and invoke-with-response-stream to any provider, count-tokens (exact where Bedrock counts, estimated elsewhere), /bedrock/rerank |
| Google GenAI SDK route | partial: generateContent, streaming, embeddings, countTokens, models, files, batches, cachedContents, /genai/v1/rank to any provider; cachedContents and operations are Gemini only, and non-Gemini batches convert generateContent requests only |
| OpenAI SDK route | done: everything under /openai/v1 and the deployment routes, including the responses lifecycle |
| Budgets | done |
| Rate limits | done |
| Cost tracking | done (models outside the built-in datasheet cost 0 and skip budgets, as in Bifrost; `client.refuse_unpriced_models` refuses budgeted requests to them, off by default) |
| Virtual keys | done |
| Request IDs | done |
| Prometheus metrics | partial: Bifrost's families and enrichment labels, http_* with custom labels, active requests, key rotation, MCP and the push gateway; the overhead components are Raiju's own four stages |
| config.json compatibility | partial: sections and keys mapped; keys Raiju does not apply are reported at startup (`websocket`, `large_payload_optimization`, top-level `access_profiles`, `network_config` transport knobs, Vertex workload identity; docs/parity.md section c) |
| Multi-core workers | partial: budgets, rate limits and caches shared between workers; `/metrics` is summed; request logs are per worker unless the log store is shared |
| Anthropic | partial: no legacy text completions |
| Azure OpenAI | partial: API keys and Entra ID; decisions by emulation only, as for OpenAI |
| AWS Bedrock | partial: SigV4, API key, assume-role, Bedrock Mantle, Converse and invoke with streaming, rerank, count-tokens, S3 files and batches, images and edits; no legacy text completions, and Stability variations are not served |
| Gemini | done: chat, streaming, embeddings, responses, speech, transcription, images and image edits, files, batches; count tokens exact |
| Ollama / vLLM / SGLang | done (decisions by emulation only, for Ollama) |
| OpenAI-compatible family | done |
| Fallback chains | done |
| Weighted key balancing | done |
| Auto prompt caching | partial: Anthropic and Bedrock inject; `cache_control_injection_points` are read and reported, not applied |
| Retries with backoff | done |
| Timeouts | done (request timeout; TLS options per provider) |

## P1

| Feature | Status |
|---|---|
| Async jobs | done |
| Audio (speech, transcription) | partial: speech and transcription on OpenAI-format and Azure, and Gemini speech and STT; other native providers are not routed; streamed transcription is missing |
| Text completions | partial: OpenAI-format providers; other providers answer "does not serve text completions" (use /anthropic/v1/complete for Anthropic) |
| Files and batches | partial: OpenAI-format, Azure, Anthropic, Gemini, Vertex (GCS), Bedrock (S3); batch delete is not routed; Cohere has no batch or file API upstream |
| Images | partial: generation on OpenAI-format, Azure, Gemini, Vertex and Bedrock; edits on OpenAI-format, Azure, Gemini, Vertex and Bedrock; variations on OpenAI-format, Azure and Bedrock; Bedrock Stability variations are not served |
| Rerank and OCR | done: rerank natively on Cohere, vLLM and Bedrock (others error; raiju/lexical for a local ranking); OCR on Mistral and OpenAI-compatible providers |
| Count tokens | partial: exact on Anthropic, Gemini, Vertex and the Bedrock models Bedrock can count; estimated elsewhere and marked `"exact": false` (see README) |
| Responses API | done |
| Semantic cache | done (in process, or Qdrant / Redis vector stores) |
| Adaptive load balancing | partial: weights, held keys, incidents and the API; Bifrost's refusal classes and wait ladder are not built |
| Circuit breaker | done |
| Native guardrails | partial: regex, secrets (Gitleaks rule set), reversible redaction, LLM judge, MCP tool-call guard; output guards on text completion and Responses streams are open |
| Admin auth | done |
| Customers and teams | done |
| MCP client (HTTP/SSE) | done (stdio: P2) |
| MCP tool execution endpoint | done |
| Request log store | partial: JSONL files with an in-memory index, histograms and filters; per worker unless shared; no SQL store |
| OpenTelemetry | done: traces and metrics over OTLP HTTP and gRPC (plaintext h2c; TLS through the ALPN patch), span filters and overhead spans |
| Docker / Helm / Terraform | done (image built and run; Terraform validated) |
| Plugin hooks | partial: compiled-in plugins with Bifrost's placement and order; dynamic (Go shared object and WASM) plugins are not built |
| Config store + management API | done (the config is a JSON file; Bifrost's sqlite and postgres config stores are not built) |
| Web UI | done |
| Cohere | done |
| Custom providers | done |
| Vertex AI | done: chat, streaming, embeddings, responses, images and image edits, batches and files over GCS, exact count tokens; the AWS workload identity is not built (needs a cloud account) |
| Model aliases | partial: chained key aliases and object-form aliases with model name and family; bare names resolved through the model catalog; provider override fields (api_version, region and similar) are not applied |
| Header/param forwarding | x-bf-eh-* done |
| Key pinning | done |
| Routing rules (CEL) | done (Bifrost variables, RE2 regex) |

## P2

| Feature | Status |
|---|---|
| LiteLLM / LangChain routes | done |
| Alerting | done (webhook, Slack, Teams, PagerDuty; metric rules and Bifrost CEL rules, /api/alerting) |
| Audit logs | partial: hash-chained, HMAC-signed, verify, export, retention and archive to object storage; the archive manifest and gzip are open |
| Clustering | partial: budgets and rate limits gossiped as CRDT counters; static, Kubernetes, DNS, Consul, etcd, mDNS and UDP discovery; etcd lease leader lock; the UDP, mDNS and broker wire formats are Raiju's, so Bifrost nodes cannot join |
| Log exports | partial: S3, MinIO, GCS, BigQuery, Kafka, Pub/Sub and Maxim sinks; Parquet payloads; raw bodies are redacted in redact mode; no logs-only mode |
| Guardrail integrations | partial: Bedrock Guardrails, Azure Content Safety, Patronus, webhook, Presidio, Azure PII, Model Armor, CrowdStrike and the local engines; streamed output guards on text and Responses streams are open |
| Access profiles / projects | partial: access profiles with versions, clone, activate, deactivate and propagate; projects with members and split policies; rate-limit splits and profile role binding are open |
| RBAC | partial: built-in roles (admin, editor, viewer, auditor) and custom roles with permission pairs; Bifrost's role-id API shape is not built |
| SSO (OIDC) | done (PKCE, groups to roles) |
| Secret managers | done (Vault KV v2, AWS Secrets Manager) |
| Virtual MCPs | partial: `/mcp/{name}`, config and management API; no access-profile or project scoping |
| Required headers | done (global and per access profile) |
| MCP agent mode | done |
| MCP auth | partial: bearer, headers, OAuth client credentials and refresh, authorization-code OAuth, per-user headers and per-user OAuth, temporary tokens; token exchange is not built |
| Gateway as MCP server | partial: POST /mcp; GET /mcp answers one connection event and does not hold the stream open; Raiju is an OAuth authorization server for MCP clients (virtual-key mode) |
| stdio MCP servers | done (Tov patch 0002, one server per worker) |
| Exporters | done (Datadog, Splunk HEC, Elasticsearch, HTTP) |
| Long-tail providers | partial: chat on the 22 OpenAI-compatible providers, IBM watsonx, Databricks, Cloudflare, GitHub Copilot and Replicate; operation coverage varies by provider (docs/parity.md section d) |
| Session affinity | done |
| Complexity router | done |
| Outbound proxies | done (HTTP, with credentials; SOCKS5 isn't in Tov's fetch) |
| Provider passthrough routes | done (OpenAI, Anthropic, Azure, Bedrock agent/guardrail, GenAI, ChatGPT Codex) |
| Direct keys, raw request/response echo | partial: direct keys and send-back of raw requests and responses are done; `x-bf-store-raw-request-response` is not built |
| Reasoning parameters | done (Anthropic, Gemini, Bedrock Claude and Nova) |

## Out

| Feature | Status |
|---|---|
| Videos and containers | not built (out of scope) |
| Edge device agent | not built (out of scope) |
| SCIM | not built (out of scope) |
| MCP code mode | not built (out of scope) |
| Media providers | not built (out of scope) |
| Runware (media provider and `/runware_passthrough`) | not built (out of scope: a media provider) |
| Warp | not built (out of scope: Bifrost's Warp integration) |
| Skills marketplace | not built (out of scope: git and zip skill marketplace, `/api/skills`) |
| A2A (agent-to-agent, registered agents) | not built (out of scope: agent cards, JSON-RPC tasks, `/agents/a2a` and `/api/agents`) |
| Sidekiq | not built (out of scope: Bifrost's Sidekiq job queue integration) |

## Open items

The P2 product decisions are taken, and their builds are in the tables above with their partial parts. The open items are listed in docs/parity.md under "Remaining gaps (current as of the L97 waves)". A native UI (desktop and mobile) is a separate track in LEDGER.md.

## Notes from the form

- Realtime: Tov may be able to use Node and other options too; investigate. (Done: WebSockets on both servers, natively on `Bun.serve`.)
