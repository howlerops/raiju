# Raiju

An LLM gateway written in [Tov](https://tov.sh), aiming to be a drop-in
replacement for [Bifrost](https://github.com/maximhq/bifrost): the same
`config.json`, the same `provider/model` names, the same `x-bf-*` headers and
`bifrost_*` metrics, compiled to one small native binary.

Scope and priorities: [SCOPE.md](SCOPE.md) (from the
[scoping form](https://claude.ai/artifact/E4vNoYy3CKL6SjdriReWQr)).

## Quick start

```sh
make tov                         # Tov with the patches in tov-patches/ (needs git and cargo)
make build                       # build/raiju (3 MB; links only glibc)
OPENAI_API_KEY=sk-... build/raiju            # no config: providers from env vars
build/raiju -app-dir ~/.config/bifrost       # or an existing Bifrost config.json
build/raiju -config config.json -port 8080 -workers 4
```

```sh
curl localhost:8080/v1/chat/completions -H 'content-type: application/json' -d '{
  "model": "openai/gpt-4o-mini",
  "messages": [{"role": "user", "content": "hi"}],
  "fallbacks": ["anthropic/claude-sonnet-4", "gemini/gemini-2.5-flash"]
}'
```

## What works

- **API:** `/v1/chat/completions` (tools, vision, JSON mode, streaming), `/v1/responses`,
  `/v1/embeddings`, `/v1/completions`, `/v1/models`, `/v1/realtime` (WebSocket relay),
  `/v1/rerank`, `/v1/count_tokens`, `/v1/async/*` jobs, audio, images, files and batches.
- **Drop-in SDK routes:** `/openai/v1/*`, `/anthropic/v1/messages` (to any provider),
  `/genai/v1beta/models/{model}:{method}`, `/bedrock/model/{id}/{converse|invoke}`.
- **Gateway features:** routing rules (CEL), circuit breakers and adaptive load
  balancing, guardrails (PII and secret redaction), semantic cache, MCP gateway,
  plugins, request log store, OpenTelemetry, management API with admin auth,
  web UI at `/`. Deployment: Dockerfile, compose and a Helm chart in `deploy/`.
- **Enterprise:** RBAC for the management API (admin, editor, viewer, auditor;
  `/api/users`), SSO with OIDC (PKCE, groups mapped to roles), a hash-chained
  HMAC-signed audit log (`/api/audit-logs`, `/export`, `/verify`), alerting
  to webhooks and Slack (`alerts`), secrets from HashiCorp Vault and AWS Secrets
  Manager (`vault.<path>#<field>`, `aws-sm.<id>`), log exports to S3, MinIO or GCS
  (`log_exports`), and clustering that shares budget and rate-limit usage
  between nodes (`cluster`).
- **MCP:** HTTP and stdio servers, with bearer, header or OAuth auth
  (`client_configs[].auth`); the gateway as an MCP server (`POST /mcp`); virtual
  MCPs that combine and rename tools (`virtual_mcps`, `/mcp/{name}`); and agent
  mode that runs allowed tool calls itself (`client.mcp_auto_execute`,
  `mcp_agent_depth`).
- **Policy:** access profiles shared by virtual keys (models, budgets, rate
  limits, MCP tools, `max_tokens`, required headers), global required headers,
  and external guardrails (AWS Bedrock Guardrails, Azure AI Content Safety,
  Patronus, any webhook) alongside the built-in PII and secret redaction.
- **Log exporters:** Datadog, Splunk HEC, Elasticsearch and any HTTP endpoint
  (`exporters`), next to the S3/GCS object exports.
- **Routing:** session affinity (`x-bf-session-id`, `session_affinity`) and a
  complexity router (`complexity_tier` in routing rules, tiers behind model `auto`).
- **Providers:** OpenAI, Azure OpenAI, Anthropic, Gemini, Vertex AI, Cohere, Bedrock (SigV4 or API key), IBM watsonx,
  Hugging Face, NVIDIA, SambaNova, DeepInfra, Novita, Hyperbolic, Lambda, Moonshot, Zhipu, Qwen (DashScope),
  AI21, Upstage, Baseten, Featherless, Inception, Friendli, SiliconFlow, GitHub Models,
  Groq, Mistral, xAI, DeepSeek, Cerebras, Fireworks, Together, Nebius, Parasail,
  OpenRouter, Perplexity, Ollama, vLLM, SGLang, LM Studio, and custom
  OpenAI-compatible providers (`custom_provider_config`).
- **Compat routes and proxies:** `/litellm/*` and `/langchain/*` prefixes, OCR
  pass-through (`/v1/ocr`), per-provider HTTP proxies (`proxy_config`, with credentials).
- **Reliability:** fallback chains, retries with jittered exponential backoff
  and `Retry-After`, key rotation on 401/403, weighted key selection with
  per-key model lists, key pinning (`x-bf-api-key`), timeouts, `x-bf-eh-*`
  header forwarding.
- **Governance:** virtual keys (`x-bf-vk`, Bearer, `x-api-key`, `x-goog-api-key`,
  `api-key`), provider/model allowlists, budgets and rate limits across the
  customer → team → key hierarchy, cost tracking with a price table and overrides.
- **Caching:** exact-match response cache (`x-bf-cache-key`, `x-bf-cache-ttl`,
  `x-bf-cache-no-store`); auto prompt caching for Anthropic and Bedrock
  (`prompt_cache.auto_inject`, `x-bf-prompt-cache-auto-inject`).
- **Observability:** Prometheus `/metrics` with Bifrost's metric names,
  `x-bifrost-request-id`, JSON request logs, `x-bf-overhead-us`.

## Inference auth

As in Bifrost, `client.enforce_auth_on_inference` makes inference require a virtual key, or
admin credentials. When it is omitted, Raiju turns it on if the config has credentials to
use (virtual keys, admin users or `auth_config`), and leaves it off otherwise. Set it to
`false` to serve anonymous inference with keys configured. `auth_config` takes Bifrost's
`admin_username`, `admin_password` and `is_enabled`, at the top level or under `governance`.

## Servers

The default server is Tov's built-in `Bun.serve`. `-workers N` forks N
processes that share the port, and each one serves WebSockets (`/v1/realtime`).
Streamed answers go to the client chunk by chunk as a `ReadableStream`
response body. OpenAI-format, Anthropic, Gemini, Bedrock, Vertex and Cohere
streams are converted as they arrive. Stream bodies need Tov with the patch in
[`tov-patches/`](tov-patches/), which `make tov` and the Dockerfile build. The
patch adds chunked responses on the runtime's existing raw-write path, and it is
small enough to send upstream.

| Server (mock upstream, 64 connections, 4-core VM) | Throughput | Gateway overhead |
|---|---|---|
| `-server bun -workers 2` | 31,000–36,000 rps | 40 µs mean |
| `-server bun` (1 process) | 16,300 rps | 68 µs mean |
| `-server http1` (1 process) | 14,300 rps | 100 µs mean |

`-server http1` is Raiju's own HTTP/1.1 server on raw sockets. It streams too,
but runs in one process. It stays as a fallback.

The workers of one node share budgets, rate limits, the response and semantic
caches, request-log queries and `/metrics` (summed) through `/tmp/raiju-<pid>` (the clustering CRDT, one slot per worker). Usage
reaches the other workers within about 200 ms, so a burst spread over several
workers can pass a limit by a few requests, as across cluster nodes. Each
worker starts its own stdio MCP servers.

## Known gaps

- SOCKS5 proxies: Tov's `fetch` supports HTTP proxies only.
- Out of scope (from the scoping form): videos and containers, the edge device
  agent, SCIM, MCP code mode and media providers.
- See [LEDGER.md](LEDGER.md) for the history.

## Performance

`bench/compare.sh` runs Raiju and Bifrost side by side against the same mock
upstream, with [vegeta](https://github.com/tsenart/vegeta) generating load.
Each gateway runs alone, pinned to the same 2 cores; the mock and the load
generator get their own cores. Logging, caching and governance are off on both.
"Added p50" is the gateway's median latency minus the direct (no gateway) median at the same rate.

Results from one 4-core cloud VM (single run, 15 s per rate, 100% success everywhere):

| | Raiju | Bifrost v1.3.10 | Bifrost v2.3.0 |
|---|---|---|---|
| Added p50 at 1,000 RPS | 198 µs | 338 µs | 816 µs |
| Added p50 at 2,500 RPS | 179 µs | 234 µs | 1,179 µs |
| Added p50 at 5,000 RPS | 99 µs | 139 µs | can't sustain (3,387 rps) |
| Max throughput, 2 cores | 27,700 rps* | 18,400 rps | 3,700 rps |
| Memory (RSS) | 10–13 MB | 100–120 MB | 280–470 MB |
| Binary | 3 MB | 49 MB | 134 MB |

\* Raiju's ceiling is the mock upstream and load generator (one core each), not Raiju.
At 10,000 RPS the load generator's own core saturates, so those rows (in
`bench/results/`) aren't meaningful for either gateway.

Caveats: Raiju passes request and response bodies through mostly untouched,
while Bifrost parses and re-serializes them and runs more plugins (model
catalog, telemetry, compat). Bifrost's published
11 µs is internal overhead on a dedicated t3.xlarge, not this end-to-end
measure. Raiju's internal overhead (`x-bf-overhead-us`) was ~40 µs mean at
5,000 RPS on a busier setup.

## Development

```sh
make check   # tov check --json on every file, applying "safe" fixes
make tov     # Tov with the patches in tov-patches/
make tov-test # the patches' own tests
make unit    # tov test (522 tests)
make e2e     # gateway against a mock upstream, on both servers
make ui      # the web UI in headless Chromium against a real gateway
make bench
```
