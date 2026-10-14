# Work ledger

The lead keeps this file current. Workers build one self-contained module each
(in its own worktree, against `docs/agent-brief.md`); the lead reviews, tests,
integrates and commits. Priorities come from [SCOPE.md](SCOPE.md).

Status: `todo` → `assigned` → `review` → `done` (or `blocked`, `rework`).

## Waves 1–3 (all done)

| ID | Work | Pri | Files | Status | Verified by |
|---|---|---|---|---|---|
| L01 | Streaming HTTP/1.1 server on raw sockets | P0 | `src/http1.tov` | done | unit + e2e (slow upstream proves incremental chunks) |
| L19 | WebSocket server for http1 | P0 | `src/ws.tov` | done | unit (RFC vectors) + e2e realtime relay |
| L20 | Incremental stream converters | P0 | `src/streams.tov` | done | unit (byte-split streams, CRCs) + e2e Anthropic stream |
| L02 | Anthropic Messages in → any provider | P0 | `src/providers/anthropic_in.tov` | done | unit + e2e (plain and streaming to OpenAI) |
| L03 | Responses API | P1 | `src/responses.tov` | done | unit + e2e (passthrough, translated, streaming) |
| L04 | Circuit breakers + adaptive load balancing | P1 | `src/health.tov` | done | unit (router: breakers, adaptive weights) |
| L05 | Guardrails (PII, secrets) | P1 | `src/guardrails.tov` | done | unit + e2e (prompt redaction) |
| L06 | Vertex AI (RS256 JWT, OAuth, provider) | P1 | `src/base64.tov`, `src/jwt.tov`, `src/providers/vertex.tov` | done | openssl-matched signature; e2e token exchange + cache |
| L07 | Routing rules (CEL subset) | P1 | `src/cel.tov` | done | unit + e2e (header rule) |
| L08 | Docker, compose, Helm | P1 | `Dockerfile`, `deploy/**` | done (image build untested: no Docker daemon here) | helm lint/template, compose config |
| L09 | Request log store | P1 | `src/logstore.tov` | done | unit + e2e (/api/logs, stats, JSONL files) |
| L10 | OpenTelemetry | P1 | `src/otel.tov` | done | unit + e2e (OTLP export, traceparent, gen_ai.*) |
| L11 | Cohere | P1 | `src/providers/cohere.tov` | done | unit |
| L12 | MCP client + tool execution | P1 | `src/mcp.tov` | done | unit + e2e (mock MCP server) |
| L13 | Config store, management API, admin auth | P1 | `src/store.tov` | done | unit + e2e (CRUD, hot reload, redaction) |
| L14 | Semantic cache | P1 | `src/semcache.tov` | done | unit + e2e (near-duplicate hit, unrelated miss) |
| L15 | Audio, images, files, batches | P1 | `src/media.tov` | done | unit + e2e (binary audio) |
| L16 | Plugins | P1 | `src/plugins.tov` | done | unit + e2e (mocker, header, maxtokens) |
| L17 | Web UI | P1 | `ui/index.html`, `src/ui_assets.tov` | done | Chromium test against a real gateway (`make ui`) |
| L18 | Async jobs, rerank, count tokens | P1 | `src/jobs.tov`, `src/extras.tov` | done | unit + e2e |

## Lead-owned

| ID | Work | Status |
|---|---|---|
| X01 | Integrate each module; e2e coverage per feature | done for everything above |
| X02 | Model aliases | done |
| X03 | Keep SCOPE.md and README in sync | ongoing |
| X04 | Real streaming on the `http1` server (default), WebSocket realtime on it, binary bodies | done |
| X05 | Semantic cache in the request path (embed on exact miss) | done |

## Defects found in review (all fixed)

- Config saves dropped every section the store didn't list (auth_config, routing_rules, otel, logs_store, mcp, plugins): now copy-and-modify, with a regression test.
- Virtual key secrets came from Math.random: now the kernel CSPRNG (`crypto.secureHex`).
- UI expected `/api/providers` as a list and deleted keys by name: server fixed to match.
- Adaptive weights compared latency across unrelated models: now only among the candidates.
- Responses route echoed the upstream body instead of the request (shadowed variable).
- README claimed a static binary; it links glibc.
- scripts/check.py applied safe fixes at byte offsets; tov reports character columns (corrupted edits on non-ASCII lines).
- Interface-held class instances crashed (Tov bug): converters and the WebSocket sink are concrete classes now.

## Next (P2 from SCOPE.md)

Session affinity, complexity router, outbound proxies, LiteLLM/LangChain routes, stdio MCP, MCP agent mode, gateway as MCP server, clustering, SSO, RBAC, audit logs, log exports, secret managers, alerting.
