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

## Wave 5 (P2, done)

| ID | Work | Files | Status | Verified by |
|---|---|---|---|---|
| L21 | Session affinity | `src/affinity.tov` | done | unit + e2e (a session stays on the key that worked) |
| L22 | Complexity router | `src/complexity.tov` | done | unit + e2e (tier map behind `auto`, header override) |
| L23 | MCP agent mode | `src/agent.tov` | done | unit + e2e (tool call run by the gateway, final answer) |
| L24 | Gateway as an MCP server | `src/mcpserver.tov` | done | unit + e2e (initialize, tools/list, tools/call, session required) |
| L25 | Audit log | `src/audit.tov` | done | unit + e2e (actor, denied changes, verify, JSONL export) |
| L26 | RBAC | `src/rbac.tov` | done | unit + e2e (viewer reads, can't write, can't read audit) |
| L27 | Secret managers | `src/secrets.tov` | done | unit (SigV4 vectors) + e2e (Vault KV v2 key) |
| L28 | Alerting | `src/alerts.tov` | done | unit + e2e (webhook fires, state visible) |

## Wave 6 (done)

| ID | Work | Files | Status | Verified by |
|---|---|---|---|---|
| L29 | Log exports to S3/GCS-compatible storage | `src/exports.tov` | done | unit (AWS SigV4 S3 examples) + e2e (signed PUT of JSONL) |
| L30 | SSO (OIDC) for the UI and management API | `src/oidc.tov` | done | unit (RS256, claims) + e2e (test IdP: PKCE, role from groups, single-use state, audit actor) |
| L31 | Clustering: shared budget and rate-limit counters | `src/cluster.tov` | done | unit (CRDT laws) + e2e (two nodes share a 3-request limit) |
| L32 | Vertex and Cohere stream converters | `src/streams_cohere.tov`, `providers/vertex.tov` | done | unit (byte-split Cohere streams) |

Integration glue (lead): `src/ops.tov` (RBAC gate, audit, alert, cluster and export timers, `/mcp`, OIDC routes, secrets).

## Lead-owned (waves 5–6)

| ID | Work | Status |
|---|---|---|
| X06 | Patch Tov so `Bun.serve` streams `ReadableStream` bodies (`tov-patches/`, `scripts/build-tov.sh`); `Bun.serve` is now the default server, streaming in every worker | done: e2e on both servers, 2 workers 36k rps vs 16k for one process |
| X07 | Outbound proxies (`proxy_config`; Tov's fetch has `proxy`), LiteLLM/LangChain route prefixes, OCR pass-through | done: e2e (proxy request line and credentials, prefixed routes, `/v1/ocr`) |
| X08 | Not possible in this Tov: stdio MCP servers (no process spawning) | won't do |

## Defects found in review (waves 5–6, fixed)

- Agent mode dropped the last call's headers (request id, cache, attempts): it now keeps them.
- RBAC let viewers and editors read the audit log: it is now limited to admins and auditors.
- `scripts/check.py` applied "safe" fixes that cascaded from an unrelated error (it added `throws` and `try` across three files). Re-check after fixing the root error; don't apply fixes while it is red.
- A mock left running from a manual test made e2e flaky (port already bound). Kill stray processes before suites.

## Next (P2 from SCOPE.md)

Sharing budget, rate-limit and cache state between the workers of one node (today: per process). SOCKS5 proxies (Tov's fetch has HTTP proxies only).
