# Raiju scope

Bifrost feature parity in detail, with every gap: [docs/parity.md](docs/parity.md).

Priorities chosen in the [scoping form](https://claude.ai/artifact/E4vNoYy3CKL6SjdriReWQr) (P0 first release, P1 next, P2 later, Out not building). Status is what this repository does today.

## P0

| Feature | Status |
|---|---|
| Chat completions + streaming | done (chunk-by-chunk on the default server) |
| Embeddings | done (OpenAI-format, Cohere, Gemini, Vertex, Bedrock Titan and Cohere) |
| List models | done |
| Realtime | done: WebSocket relay (OpenAI, Azure); WebRTC calls, client secrets and sessions pass through |
| Exact-match cache | done |
| Anthropic SDK route | done: messages (any provider, streaming), models, message batches and files (passthrough or via an OpenAI-format provider) |
| Bedrock SDK route | done: converse, invoke, converse-stream and invoke-with-response-stream to any provider, count-tokens (estimated); no /bedrock/rerank |
| Google GenAI SDK route | partial: generateContent, streaming, embeddings and countTokens to any provider, models; no files, batches or cached contents routes |
| OpenAI SDK route | done: everything under /openai/v1, including the responses lifecycle |
| Budgets | done |
| Rate limits | done |
| Cost tracking | done |
| Virtual keys | done |
| Request IDs | done |
| Prometheus metrics | done: Bifrost's families and enrichment labels, http_*, custom labels; some families (active requests, key rotation, MCP) missing |
| config.json compatibility | done for the sections Raiju implements; unknown keys are reported at startup (docs/parity.md) |
| Multi-core workers | done (budgets, rate limits and cache shared between workers) |
| Anthropic | done |
| Azure OpenAI | done (API keys and Entra ID) |
| AWS Bedrock | done (SigV4, API key, assume-role; Bedrock Mantle) |
| Gemini | done |
| Ollama / vLLM / SGLang | done |
| OpenAI-compatible family | done |
| Fallback chains | done |
| Weighted key balancing | done |
| Auto prompt caching | done |
| Retries with backoff | done |
| Timeouts | done (request timeout; TLS options per provider) |

## P1

| Feature | Status |
|---|---|
| Async jobs | done |
| Audio (speech, transcription) | partial: OpenAI-format, Azure, Gemini speech |
| Text completions | done |
| Files and batches | partial: OpenAI-format, Azure, Anthropic, Gemini; not Bedrock, Vertex or Cohere |
| Images | partial: OpenAI-format, Azure, Gemini (Imagen and image models) |
| Rerank, OCR, count tokens | done: rerank on Cohere and vLLM (others error; raiju/lexical for a local ranking); count tokens exact on Anthropic and Gemini, estimated elsewhere (`"exact": false`) |
| Responses API | done |
| Semantic cache | done (in process, or Qdrant / Redis vector stores) |
| Adaptive load balancing | done |
| Circuit breaker | done |
| Native guardrails | done |
| Admin auth | done |
| Customers and teams | done |
| MCP client (HTTP/SSE) | done |
| MCP tool execution endpoint | done |
| Request log store | done |
| OpenTelemetry | done (traces and metrics over OTLP/HTTP; no gRPC) |
| Docker / Helm / Terraform | done (image built and run; Terraform validated) |
| Plugin hooks | done (compiled-in plugins) |
| Config store + management API | done |
| Web UI | done |
| Cohere | done |
| Custom providers | done |
| Vertex AI | done |
| Model aliases | done (chained key aliases; bare names resolved through the model catalog) |
| Header/param forwarding | x-bf-eh-* done |
| Key pinning | done |
| Routing rules (CEL) | done (Bifrost variables, RE2 regex) |

## P2

| Feature | Status |
|---|---|
| LiteLLM / LangChain routes | done |
| Alerting | done (webhook, Slack, Teams, PagerDuty; metric rules and Bifrost CEL rules, /api/alerting) |
| Audit logs | done (hash-chained, HMAC-signed, verify and export) |
| Clustering | done (budgets and rate limits gossiped as CRDT counters) |
| Log exports | done (S3, MinIO, GCS) |
| Guardrail integrations | done (Bedrock Guardrails, Azure Content Safety, Patronus, webhook) |
| Access profiles / projects | done (access profiles) |
| RBAC | done (admin, editor, viewer, auditor) |
| SSO (OIDC) | done (PKCE, groups to roles) |
| Secret managers | done (Vault KV v2, AWS Secrets Manager) |
| Virtual MCPs | done (`/mcp/{name}`) |
| Required headers | done (global and per access profile) |
| MCP agent mode | done |
| MCP auth | done (bearer, headers, OAuth client credentials and refresh) |
| Gateway as MCP server | done (`/mcp`) |
| stdio MCP servers | done (Tov patch 0002, one server per worker) |
| Exporters | done (Datadog, Splunk HEC, Elasticsearch, HTTP) |
| Long-tail providers | done (22 OpenAI-compatible providers, IBM watsonx, Databricks, Cloudflare, GitHub Copilot, Replicate) |
| Session affinity | done |
| Complexity router | done |
| Outbound proxies | done (HTTP, with credentials; SOCKS5 isn't in Tov's fetch) |
| Provider passthrough routes | done (OpenAI, Anthropic, Azure, Bedrock agent/guardrail, GenAI, ChatGPT Codex) |
| Direct keys, raw request/response echo | done |
| Reasoning parameters | done (Anthropic, Gemini, Bedrock Claude and Nova) |

## Out

| Feature | Status |
|---|---|
| Videos and containers | not built (out of scope) |
| Edge device agent | not built (out of scope) |
| SCIM | not built (out of scope) |
| MCP code mode | not built (out of scope) |
| Media providers | not built (out of scope) |

## Open product decisions (docs/parity.md, G36, G37, G40–G46)

Decisions API and the typesafe provider; the compat plugin; WebSocket responses and live
sessions; projects, business units and custom RBAC; more log sinks (BigQuery, Kafka,
Pub/Sub); more guardrail engines (Presidio, Model Armor, LLM judge); cluster discovery
and leader election; auth proxies; prompt repository, skills and the other Bifrost
products. A native UI (desktop and mobile) is a separate track in LEDGER.md.

## Notes from the form

- Realtime: Tov may be able to use Node and other options too; investigate. (Done: WebSockets on both servers, natively on `Bun.serve`.)
