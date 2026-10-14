# Work ledger

The lead keeps this file current. Workers build one self-contained module each
(in its own worktree, against `docs/agent-brief.md`); the lead reviews, tests,
integrates and commits. Priorities come from [SCOPE.md](SCOPE.md).

Status: `todo` → `assigned` → `review` → `done` (or `blocked`, `rework`).

## Wave 1

| ID | Work | Pri | Files | Owner | Status | Acceptance |
|---|---|---|---|---|---|---|
| L01 | Streaming HTTP/1.1 server on `Bun.listen` (real SSE) | P0 | `src/http1.tov` | worker | assigned | Parses requests (Content-Length, chunked, keep-alive, pipelining), handler can write headers then chunks then end; tested parser + writer |
| L02 | Anthropic Messages in → any provider (Claude Code on any model) | P0 | `src/providers/anthropic_in.tov` | worker | assigned | Messages req → OpenAI chat req; chat completion → Message; OpenAI SSE → Anthropic SSE events; tools, images, system, tool_result |
| L03 | Responses API translation | P1 | `src/responses.tov` | worker | assigned | Responses req → chat req; chat completion → Response object; SSE → Responses events; tools, instructions |
| L04 | Circuit breaker + adaptive load balancing | P1 | `src/health.tov` | worker | assigned | Per-key EWMA latency + error rate; closed/open/half-open breaker; adaptive weights; deterministic tests with injected clock |
| L05 | Native guardrails (PII + secrets redaction) | P1 | `src/guardrails.tov` | worker | assigned | Detect/redact email, phone, SSN, credit cards (Luhn), IPv4, API keys/tokens, custom literal patterns; modes block/redact/log |
| L06 | Vertex AI: base64, JWT RS256, OAuth token, provider | P1 | `src/base64.tov`, `src/jwt.tov`, `src/providers/vertex.tov` | worker | assigned | RS256 matches a reference signature; service-account JSON → token request; Gemini + Anthropic on Vertex URLs |
| L07 | Routing rules (CEL subset) | P1 | `src/cel.tov` | worker | assigned | Lexer/parser/evaluator for the documented subset; rule matching → weighted targets; errors don't crash |
| L08 | Deployment | P1 | `Dockerfile`, `docker-compose.yml`, `deploy/helm/raiju/**` | worker | assigned | Multi-stage build to a small image; compose with config mount; Helm chart with config, probes, metrics |

## Wave 2 (queued)

| ID | Work | Pri | Files |
|---|---|---|---|
| L09 | Request log store (JSONL, retention, query) | P1 | `src/logstore.tov` |
| L10 | OpenTelemetry OTLP/HTTP exporter | P1 | `src/otel.tov` |
| L11 | Cohere provider | P1 | `src/providers/cohere.tov` |
| L12 | MCP client + tool execution | P1 | `src/mcp.tov` |
| L13 | Config store + management API + admin auth | P1 | `src/store.tov` |
| L14 | Semantic cache (embeddings + vector index) | P1 | `src/semcache.tov` |
| L15 | Audio, images, files, batches pass-through | P1 | `src/media.tov` |
| L16 | Plugin hooks | P1 | `src/plugins.tov` |
| L17 | Web UI | P1 | `ui/` (after L13) |
| L18 | Async jobs, rerank, count tokens | P1 | `src/jobs.tov` |

## Lead-owned

| ID | Work | Status |
|---|---|---|
| X01 | Integrate each module into gateway/server; e2e coverage per feature | ongoing |
| X02 | Model aliases (`aliases` on keys) | done |
| X03 | Keep SCOPE.md status and README in sync | ongoing |

## Log

- Wave 1 dispatched: L01–L08.
