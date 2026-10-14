# Raiju scope

Bifrost feature parity in detail, with every gap: [docs/parity.md](docs/parity.md).

Priorities chosen in the [scoping form](https://claude.ai/artifact/E4vNoYy3CKL6SjdriReWQr) (P0 first release, P1 next, P2 later, Out not building). Status is what this repository does today.

## P0

| Feature | Status |
|---|---|
| Chat completions + streaming | done (chunk-by-chunk on the default server) |
| Embeddings | done (OpenAI-format, Cohere, Gemini, Vertex, Bedrock Titan and Cohere) |
| List models | done |
| Realtime (WebSocket) | done for WebSocket (OpenAI, Azure); no WebRTC calls, client secrets or sessions |
| Exact-match cache | done |
| Anthropic SDK route | partial: messages (any provider, streaming); no models, batches or files routes |
| Bedrock SDK route | partial: converse and invoke to Bedrock only; no streaming routes, count-tokens or rerank |
| Google GenAI SDK route | partial: generateContent family to Gemini only; no models, files, batches or cached contents |
| OpenAI SDK route | partial: chat, completions, embeddings, responses, models list; audio, images, files, batches and responses lifecycle not under /openai/v1 |
| Budgets | done |
| Rate limits | done |
| Cost tracking | done |
| Virtual keys | done |
| Request IDs | done |
| Prometheus metrics | partial: core bifrost_* series; Bifrost's label set and some series missing |
| config.json compatibility | partial: see docs/parity.md (c); several Bifrost section names are not read yet |
| Multi-core workers | done (budgets, rate limits and cache shared between workers) |
| Anthropic | done |
| Azure OpenAI | partial: API keys; no Entra ID |
| AWS Bedrock | SigV4 or API key |
| Gemini | done |
| Ollama / vLLM / SGLang | done |
| OpenAI-compatible family | done |
| Fallback chains | done |
| Weighted key balancing | done |
| Auto prompt caching | done |
| Retries with backoff | done |
| Timeouts | request timeout |

## P1

| Feature | Status |
|---|---|
| Async jobs | done |
| Audio (speech, transcription) | partial: OpenAI-format and Azure providers only |
| Text completions | done |
| Files and batches | partial: OpenAI-format and Azure providers only |
| Images | partial: OpenAI-format and Azure providers only |
| Rerank, OCR, count tokens | done |
| Responses API | done |
| Semantic cache | done |
| Adaptive load balancing | done |
| Circuit breaker | done |
| Native guardrails | done |
| Admin auth | done |
| Customers and teams | done |
| MCP client (HTTP/SSE) | done |
| MCP tool execution endpoint | done |
| Request log store | done |
| OpenTelemetry | done |
| Docker / Helm / Terraform | done (image built and run; Terraform validated) |
| Plugin hooks | done (compiled-in plugins) |
| Config store + management API | done |
| Web UI | done |
| Cohere | done |
| Custom providers | done |
| Vertex AI | done |
| Model aliases | done |
| Header/param forwarding | x-bf-eh-* done |
| Key pinning | done |
| Routing rules (CEL) | done |

## P2

| Feature | Status |
|---|---|
| LiteLLM / LangChain routes | done |
| Alerting | done (webhook, Slack) |
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
| Long-tail providers | done (18 OpenAI-compatible providers, IBM watsonx) |
| Session affinity | done |
| Complexity router | done |
| Outbound proxies | done (HTTP, with credentials; SOCKS5 isn't in Tov's fetch) |

## Out

| Feature | Status |
|---|---|
| Videos and containers | not built (out of scope) |
| Edge device agent | not built (out of scope) |
| SCIM | not built (out of scope) |
| MCP code mode | not built (out of scope) |
| Media providers | not built (out of scope) |

## Notes from the form

- Realtime: Tov may be able to use Node and other options too; investigate. (Done: WebSockets on both servers, natively on `Bun.serve`.)
