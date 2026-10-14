# Raiju

An LLM gateway written in [Tov](https://tov.sh), aiming to be a drop-in
replacement for [Bifrost](https://github.com/maximhq/bifrost): the same
`config.json`, the same `provider/model` names, the same `x-bf-*` headers and
`bifrost_*` metrics, compiled to one small native binary.

Scope and priorities: [SCOPE.md](SCOPE.md) (from the
[scoping form](https://claude.ai/artifact/E4vNoYy3CKL6SjdriReWQr)).

## Quick start

```sh
curl -fsSL https://tov.sh/install.sh | sh
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
- **Providers:** OpenAI, Azure OpenAI, Anthropic, Gemini, Vertex AI, Cohere, Bedrock (SigV4 or API key),
  Groq, Mistral, xAI, DeepSeek, Cerebras, Fireworks, Together, Nebius, Parasail,
  OpenRouter, Perplexity, Ollama, vLLM, SGLang, LM Studio, and custom
  OpenAI-compatible providers (`custom_provider_config`).
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

## Servers

The default server (`-server http1`) is Raiju's own HTTP/1.1 implementation on
raw sockets: answers stream to the client chunk by chunk (OpenAI-format,
Anthropic, Gemini and Bedrock streams are converted as they arrive), and
WebSockets serve `/v1/realtime`. It runs in one process, which handled about
16k requests/second in our tests; for more cores, run one process per core
behind a load balancer (or Helm replicas).

`-workers N` (N > 1) switches to Tov's built-in server, which forks N
processes but buffers streamed answers (they arrive complete, as SSE).

## Known gaps

- Governance, cache and metrics state is in memory per process.
- Vertex and Cohere streams are buffered (answered in one piece).
- See [LEDGER.md](LEDGER.md) for what's next.

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
catalog, telemetry, compat); Raiju also buffers streaming. Bifrost's published
11 µs is internal overhead on a dedicated t3.xlarge, not this end-to-end
measure. Raiju's internal overhead (`x-bf-overhead-us`) was ~40 µs mean at
5,000 RPS on a busier setup.

## Development

```sh
make check   # tov check --json on every file, applying "safe" fixes
make unit    # tov test (270 tests)
make e2e     # gateway against a mock upstream, on both servers
make ui      # the web UI in headless Chromium against a real gateway
make bench
```
