# Raiju scope

Priorities chosen in the [scoping form](https://claude.ai/artifact/E4vNoYy3CKL6SjdriReWQr) (P0 first release, P1 next, P2 later, Out not building). Status is what this repository does today.

## P0

| Feature | Status |
|---|---|
| Chat completions + streaming | done (chunk-by-chunk on the default server) |
| Embeddings | OpenAI-format providers |
| List models | done |
| Realtime (WebSocket) | done (OpenAI, Azure) |
| Exact-match cache | done |
| Anthropic SDK route | Anthropic + Bedrock (non-stream) targets |
| Bedrock SDK route | done |
| Google GenAI SDK route | done |
| OpenAI SDK route | done |
| Budgets | done |
| Rate limits | done |
| Cost tracking | done |
| Virtual keys | done |
| Request IDs | done |
| Prometheus metrics | done |
| config.json compatibility | done |
| Multi-core workers | done (state is per worker) |
| Anthropic | done |
| Azure OpenAI | done |
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
| Audio (speech, transcription) | done |
| Text completions | done |
| Files and batches | done |
| Images | done |
| Rerank, OCR, count tokens | rerank and count tokens done; OCR todo |
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
| Docker / Helm / Terraform | Docker, compose, Helm done; Terraform todo |
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
| LiteLLM / LangChain routes |  |
| Alerting |  |
| Audit logs |  |
| Clustering |  |
| Log exports |  |
| Guardrail integrations |  |
| Access profiles / projects |  |
| RBAC |  |
| SSO (OIDC) |  |
| Secret managers |  |
| Virtual MCPs |  |
| Required headers |  |
| MCP agent mode |  |
| MCP auth |  |
| Gateway as MCP server |  |
| stdio MCP servers |  |
| Exporters |  |
| Long-tail providers |  |
| Session affinity |  |
| Complexity router |  |
| Outbound proxies |  |

## Out

| Feature | Status |
|---|---|
| Videos and containers |  |
| Edge device agent |  |
| SCIM |  |
| MCP code mode |  |
| Media providers |  |

## Notes from the form

- Realtime: Tov may be able to use Node and other options too; investigate.
