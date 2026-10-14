# Raiju

An LLM gateway written in [Tov](https://tov.sh), aiming to be a drop-in
replacement for [Bifrost](https://github.com/maximhq/bifrost): the same
`config.json`, the same `provider/model` names, the same `x-bf-*` headers and
`bifrost_*` metrics, compiled to one native binary.

Scope and priorities: [SCOPE.md](SCOPE.md) (from the
[scoping form](https://claude.ai/artifact/E4vNoYy3CKL6SjdriReWQr)).

## Quick start

```sh
curl -fsSL https://tov.sh/install.sh | sh
make build                       # build/raiju (3 MB, static)
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

- **API:** `/v1/chat/completions` (tools, vision, JSON mode, streaming), `/v1/embeddings`,
  `/v1/completions`, `/v1/models`, `/v1/realtime` (WebSocket relay).
- **Drop-in SDK routes:** `/openai/v1/*`, `/anthropic/v1/messages`,
  `/genai/v1beta/models/{model}:{method}`, `/bedrock/model/{id}/{converse|invoke}`.
- **Providers:** OpenAI, Azure OpenAI, Anthropic, Gemini, Bedrock (SigV4 or API key),
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

## Known gaps

- **Streaming is buffered.** SSE output is correct but arrives in one piece:
  Tov's HTTP server can't stream bodies yet ([docs/tov-notes.md](docs/tov-notes.md)).
- Governance, cache and metrics state is in memory per worker process.
- `/anthropic/v1/messages` routes only to Anthropic and (non-streaming) Bedrock.

## Performance

`make bench` (the mock upstream, the load generator and the gateway on one machine):

| | this VM (4 shared cores) | Bifrost (README, t3.xlarge) |
|---|---|---|
| Gateway overhead at 5,000 RPS, mean | 40 µs | 11 µs |
| Success rate at 5,000 RPS | 100% | 100% |
| Single-worker ceiling (closed loop, 64 clients) | ~20,700 rps | not published |

Overhead is handler time minus upstream time (the same thing Bifrost reports);
end-to-end the extra local hop costs ~0.3 ms at p50 here.

## Development

```sh
make check   # tov check --json on every file, applying "safe" fixes
make unit    # tov test (30 tests)
make e2e     # gateway against a mock upstream (33 checks)
make bench
```
