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
make build                       # build/raiju (about 21 MB; links glibc, libstdc++ and JavaScriptCore)
OPENAI_API_KEY=sk-... build/raiju            # no config: providers from env vars
build/raiju -app-dir ~/.config/bifrost       # or an existing Bifrost config.json
build/raiju -config config.json -port 8080 -workers 4
BIFROST_SETUP_TOKEN=$(openssl rand -hex 16) build/raiju   # /api opens to this token until an admin exists
```

The gateway listens on 127.0.0.1 unless `-host` (or `BIFROST_HOST`) says otherwise; the image and the
deploy files pass `-host 0.0.0.0`. The management API is locked until an admin exists (see
[Secure defaults](#secure-defaults)).

```sh
build/raiju -healthcheck -port 8080          # exits 0 when the gateway on this host answers /health
```

Every `config.json` key, with its type and description: [docs/config-reference.md](docs/config-reference.md)
(generated from the source by `make config-doc`). Deployment (Docker, compose, Helm, sizing):
[deploy/README.md](deploy/README.md).

```sh
curl localhost:8080/v1/chat/completions -H 'content-type: application/json' -d '{
  "model": "openai/gpt-4o-mini",
  "messages": [{"role": "user", "content": "hi"}],
  "fallbacks": ["anthropic/claude-sonnet-4", "gemini/gemini-2.5-flash"]
}'
```

## What works

- **API:** `/v1/chat/completions` (tools, vision, JSON mode, reasoning, streaming),
  `/v1/responses` (and its retrieve, delete, cancel, input_items, input_tokens, compact;
  WebSocket mode for OpenAI), `/v1/embeddings`, `/v1/completions` (OpenAI-format providers),
  `/v1/models`, `/v1/realtime` (WebSocket for OpenAI, Azure and xAI, and WebRTC calls for OpenAI
  and Azure at `POST /v1/realtime/calls`) and GPT Live (`/v1/live/sessions`, WebSocket and
  WebRTC; the WebRTC calls need `server.webrtc_enabled`), each session metered, guarded and logged
  with its cost (client secrets and sessions are routed),
  `/v1/rerank`, `/v1/count_tokens`, `/v1/async/*` jobs, and audio, images, files and batches
  (which providers serve each one is in [SCOPE.md](SCOPE.md)).
- **Drop-in SDK routes:** `/openai/v1/*`; `/anthropic/v1/messages` (to any provider),
  models, message batches and files; `/genai/v1beta/models/{model}:{method}` to any
  provider; `/bedrock/model/{id}/{converse|invoke}` and their streaming forms (AWS
  event-stream) to any provider; `/cohere/v2/{chat|embed|rerank}`; `/litellm`, `/langchain`,
  `/pydanticai`; provider passthroughs (`/openai_passthrough/*` and the rest).
- **Bifrost compatibility:** reads Bifrost's `config.json` (section names, plugins,
  guardrails, alerting, vector store, otel) and reports what it ignores; sends the
  `x-bifrost-*` response headers and Bifrost's Prometheus families and labels.
- **Count tokens** are exact for Anthropic, Gemini and Vertex (their APIs) and for the Bedrock
  models Bedrock can count; everyone else gets an estimate, marked `"exact": false`. The
  management API spec (`docs/openapi/management.yaml`) does not cover `/v1/count_tokens`.
- **Gateway features:** routing rules (CEL), circuit breakers and adaptive load
  balancing, guardrails (PII and secret redaction), semantic cache, MCP gateway,
  plugins, request log store, OpenTelemetry, management API with admin auth,
  web UI at `/` (SolidJS, in `web/`, embedded in the binary). Deployment: Dockerfile, compose and a Helm chart in `deploy/`.
  The management API is specified in [`docs/openapi/management.yaml`](docs/openapi/management.yaml),
  and `make openapi-check` checks the routes against it. `clients/` holds a native client spike
  (gpui and Slint) that reads the same API; see [clients/README.md](clients/README.md).
- **WebAssembly plugins:** a `plugins[]` entry with `"path": "/path/to/plugin.wasm"` loads a plugin in
  Bifrost's JSON ABI (exports `malloc`, `free`, `get_name`, `init`, `pre_hook`, `post_hook`, `cleanup`) and
  runs it on an embedded interpreter (WAMR, added to the Tov runtime by `tov-patches/0005-wamr.patch`).
  `wasm_limits` on the entry caps its memory pages, stack and instructions per hook call. A plugin sees only
  its own memory; a hook that traps, loops or answers with an error is logged and skipped. Go shared-object
  plugins (`.so`) are not supported. `tests/wasm/plugin.c` is a small example. The chain runs Bifrost's LLM hooks
  (`pre_hook`, `post_hook`) on every request type (chat, completions, embeddings, Responses, rerank, speech,
  transcription, images, OCR) and on each chunk of a stream, and a `post_hook` answer with `has_error` turns a
  response into an error. A module that exports `http_pre_hook`, `http_post_hook` or `http_stream_chunk_hook`
  also gets Bifrost's HTTP transport hooks: before routing it can rewrite the request or answer it, after the
  response it can rewrite that, and for each event of a stream it can rewrite, drop or end (see `docs/parity.md`,
  section Plugins). A `path` may be a URL: it must be https unless the entry pins the file with `"sha256"`
  (checked on download and on every load), and the copy is kept in a private `plugin-cache` folder beside the
  config file (`RAIJU_PLUGIN_DIR` overrides).
- **Outbound safety:** every URL a user or caller sets (A2A agents and push callbacks, webhooks, MCP servers with
  `require_public_target`, plugin downloads, provider `base_url` through the API, exporters) is checked against
  private and metadata addresses in every spelling, with host names resolved before each request; see
  [SECURITY.md](SECURITY.md), which also lists the vendored native libraries and how to report a vulnerability.
- **Enterprise:** RBAC for the management API (admin, editor, viewer, auditor;
  `/api/users`), SSO with OIDC (PKCE, groups mapped to roles), a hash-chained
  HMAC-signed audit log (`/api/audit-logs`, `/export`, `/verify`), alerting
  to webhooks, Slack, Teams and PagerDuty (`alerts`, Bifrost's CEL alert rules), secrets from HashiCorp Vault and AWS Secrets
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
- **Crew routing** (Raiju-only; [docs/crew-routing.md](docs/crew-routing.md)): task-level routing of
  agent crews after S. K. Radha's *Pareto Crewing*. Model `crew/<pool>` with `x-raiju-task-id` and
  `x-raiju-crew-role`: the first call of a task picks a model per role (worker, planner, checker ...)
  by maximising quality − λ·cost for the task's class, with route-aware costs (API price, free local
  models, subscriptions free until their quota runs low), λ at the frontier's knee, fixed or paced to a
  per-task budget. `/api/crews` assigns and inspects tasks, takes outcomes (credibility-weighted
  learning) and decides escalation after a verifier signal (Pandora's index). Priors and the task
  classifier are fitted offline by `scripts/crew_priors.py`; the admin UI has a Crews tab.
- **A2A agent gateway:** agents behind `/agents/a2a/{name}` over JSON-RPC, REST and gRPC
  (`server.a2a_grpc_port`, `server.a2a_grpc_base_domain`; HTTP/2 cleartext served by Raiju itself),
  with push notifications relayed and shared across the cluster.
- **Large payloads** (`large_payload_optimization`): request bodies over the threshold stream to the
  provider, converted on the fly when its format differs (chat, Responses, Messages, embeddings).
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
  customer → team → key hierarchy, cost tracking with a price table and overrides (the built-in
  table is generated from the Bifrost datasheet by `scripts/gen_pricing.py`; audio is billed by
  tokens, seconds or characters as Bifrost bills it).
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
While inference is not authenticated the gateway says so at start-up.

## Secure defaults

- **The management API is locked until an admin exists**, as Bifrost's setup lock. With no admin
  account (no admin users, API keys or `auth_config`), every `/api` route but the public ones
  (`/api/session/is-auth-enabled`, login, setup, `/api/version`, OAuth callbacks) needs the
  operator's setup token in `X-Bifrost-Setup-Token`, or the setup session cookie that
  `POST /api/session/setup` trades it for: 401 without it, 403 with a wrong one. The token is
  `setup_token` in the config (`env.NAME` allowed), else the `BIFROST_SETUP_TOKEN` environment
  variable. With neither set, `/api` answers 403 to everything, and the start-up log says how to
  set one. Create the first admin with the token (`POST /api/users` with `X-Bifrost-Setup-Token`;
  the dashboard has no setup screen yet); from then on normal sign-in applies and the token opens
  nothing. `client.whitelisted_routes` stay open.
  In the deployments: `BIFROST_SETUP_TOKEN` in compose's `.env`, the chart's `setupToken.existingSecret`,
  or a `secret_arns` entry on ECS ([deploy/README.md](deploy/README.md)).
- **Bind address:** 127.0.0.1 by default (Bifrost's `localhost`); `-host` or `BIFROST_HOST` change it.
  The image, compose, the chart and the Terraform modules pass `-host 0.0.0.0`.
- **Metrics:** label values a caller chooses are bounded. A path no route serves (404, 405, 501), and
  a management path the gate refused, is labelled `other`; ids in paths become `{id}` (past the third
  segment for a failed request); methods outside the HTTP set are `OTHER`; a model (or alias) name
  becomes a label value once the provider served it or failed for its own reasons (429, 5xx), and is
  `other` until then; and each label keeps at most 1,000 distinct values, after which a new value is
  reported as `other`. `bench/metrics_cardinality.py` measures it (10,000 junk requests).
- **Async jobs:** ids are 128 random bits (`job_` and 32 hex digits). A job submitted with a virtual
  key is shown only to that key, and one submitted with another credential only to that
  credential; an anonymous job is open to any poll, as in Bifrost. Another caller's job reads as
  404.
- **Masked secrets:** provider reads return each key's effective id (its `id`, else its `name`), and a
  key sent back with its masked value keeps the stored secret (matched by id, then name, then
  position). A masked value (`****` or `abcd…wxyz`) that matches no stored secret is refused with
  400 instead of being saved as the key.
- **Files:** new config, backup, state, log, audit and cache files are created 0600 and their folders
  0700; `config.json.bak` is always 0600. The workers' share folder is
  `$TMPDIR/raiju-<pid>-<16 random hex digits>` (default `/tmp`), made by the supervisor with a fresh
  `mkdir` (a planted folder or symlink makes it fail rather than be used) and set to 0700.
- **MCP:** a virtual key with no `mcp_configs` gets no MCP tools but those of `allow_by_default`
  clients, as in Bifrost. Grant a key its tools with `mcp_configs` (`tools_to_execute: ["*"]` for
  all of a client's tools), an access profile, or a virtual MCP. A request without a virtual key is
  not limited by key rules.
- **WebRTC:** the WebRTC calls the gateway terminates on its own peer (`POST /v1/realtime/calls`,
  `POST /v1/realtime`, `POST /v1/live/sessions`) are off unless `server.webrtc_enabled` is `true`
  (403 otherwise). Bifrost has no such switch; Raiju adds it because the peer's DTLS and SCTP stack
  (libdatachannel, usrsctp) is C code any caller with a virtual key reaches. WebSocket realtime and
  live sessions are not affected.

## Owner switches

Two Raiju-only switches, both off by default (Bifrost's behaviour):

- `client.refuse_unpriced_models`: a request subject to a budget (virtual key, team,
  customer, provider or model budget) is refused with 403 when its model, or a fallback the
  key may use, has no price (no datasheet row, pricing override or config price). Requests
  with no budget pass as before, at cost 0. Settable through `PUT /api/config`.
- `cache.scope_by_virtual_key`: the exact-match response cache keeps each virtual key's
  entries apart, as the semantic cache does. On by default; `false` lets keys share
  exact-cache entries.

## Servers

The default server is Tov's built-in `Bun.serve`. `-workers N` forks N
processes that share the port, and each one serves WebSockets (`/v1/realtime`).
Streamed answers go to the client chunk by chunk as a `ReadableStream`
response body. OpenAI-format, Anthropic, Gemini, Bedrock, Vertex and Cohere
streams are converted as they arrive. Stream bodies need Tov with the patch in
[`tov-patches/`](tov-patches/), which `make tov` and the Dockerfile build. The
patch adds chunked responses on the runtime's existing raw-write path, and it is
small enough to send upstream.

Measured by the production audit (2026-10-24, before the fixes under Memory below: 4-core VM, a minimal mock that
answers at once, `hey -z 8s` for throughput and vegeta at a fixed rate for latency; the gateway
pinned to two cores):

| Server | Throughput (16 / 64 / 256 connections) | Added p50 latency (1,000 to 5,000 rps) |
|---|---|---|
| `-server bun -workers 2` | 18,600 / 10,800 / 8,900 rps | 190–320 µs |
| `-server bun` (1 process) | 8,800 / 9,000 / 9,600 rps | 250–400 µs |
| `-server http1` (1 process) | not re-measured | not re-measured |

Two workers fall back to about one worker's throughput at 64 connections and more (connections
are not balanced well across workers), and one worker's p99 had stalls of 40 ms to 0.5 s at
2,500 to 5,000 rps (the Memory section below has the p99 after the fixes). The earlier figures here (16,300 rps on one worker, 31,000 to 36,000 on two)
came from an older build and are not reproduced.

`-server http1` is Raiju's own HTTP/1.1 server on raw sockets. It streams too,
but runs in one process. It stays as a fallback.

Both servers stop gracefully on SIGTERM or SIGINT (every worker drains: `GET /ready` answers 503,
the listener closes, the requests and streams in hand get up to `server.shutdown_grace_seconds`,
25 by default, and queued exports are sent before the exit), and both time out slow clients
(`server.header_timeout_seconds` 10, `body_timeout_seconds` 60, `idle_timeout_seconds` 60) and cap
connections per process (`server.max_connections`, three quarters of the descriptor limit by
default; 503 past it). `GET /health` is liveness, `GET /ready` readiness. See
[deploy/README.md](deploy/README.md#stopping-and-slow-clients).

The workers of one node share budgets, rate limits, the response and semantic
caches and `/metrics` (summed) through a private share folder, `$TMPDIR/raiju-<pid>-<random>` (the clustering CRDT, one slot per worker).
Request-log queries are shared only when the log store is shared; otherwise each worker answers from its own log. Usage
reaches the other workers within about 200 ms, so a burst spread over several
workers can pass a limit by a few requests, as across cluster nodes. Each
worker starts its own stdio MCP servers.

A config change saved by one worker (through the API, say) is applied by every worker before the request is answered,
so a deleted virtual key stops working on all of them at once. Cluster nodes take each other's saves when they share
the config file, or pull them from a peer with `cluster.config_sync: "pull"`. The request log and audit folders default
to `logs` and `logs/audit` in the app dir, and a required store that cannot open stops the start. See
[docs/operations.md](docs/operations.md).

## Known gaps

- SOCKS5 proxies: Tov's `fetch` supports HTTP proxies only. OTLP export uses plaintext h2c
  for gRPC; TLS gRPC goes through the ALPN patch.
- Open items, and the partial parts of each feature: [SCOPE.md](SCOPE.md) and the
  "Remaining gaps" section of [docs/parity.md](docs/parity.md).
- Out of scope ([SCOPE.md](SCOPE.md), Out table): videos and containers, the edge device
  agent, media providers (Runware included), Warp, the skills marketplace, and Sidekiq.
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
| Memory (RSS) | 20 MB idle, 44 MB under load† | 100–120 MB | 280–470 MB |
| Binary | 21 MB | 49 MB | 134 MB |

\* Raiju's ceiling is the mock upstream and load generator (one core each), not Raiju.
The latency and throughput rows are from an earlier `bench/compare.sh` run and were not repeated on the
current build; the audit's throughput figures are under Servers.

† Re-measured (production audit, 2026-10-24): one worker, non-streaming load at 1,500 rps stays flat at
44 MB. Each open stream adds about 170 KB while it lasts (Memory, below; [deploy/README.md](deploy/README.md#sizing)).
At 10,000 RPS the load generator's own core saturates, so those rows (in
`bench/results/`) aren't meaningful for either gateway.

Caveats: Raiju passes request and response bodies through mostly untouched,
while Bifrost parses and re-serializes them and runs more plugins (model
catalog, telemetry, compat). Bifrost's published
11 µs is internal overhead on a dedicated t3.xlarge, not this end-to-end
measure. Raiju's internal overhead (`x-bf-overhead-us`) was ~40 µs mean at
5,000 RPS on a busier setup.

### Memory

`make soak` (`tests/soak/soak.py`) drives one worker with streamed and plain chat, slow streams held open and
the log store on, and fails when its RSS keeps growing or an open stream costs too much. CI runs it as its own
job. Measured on a 4-core VM (one worker, about 600 requests a second plus 100 slow streams):

| | Before L182 | After |
|---|---|---|
| RSS growth while streaming | about 0.8 MB a second, never given back (about 2 KB per stream) | flat once warm (under 2 MB over the last 30 s) |
| Plain chat at 3,000 RPS for 30 s: p99 / p99.9 / max | 4.6 / 20.5 / 32 ms | 2.3 / 8.7 / 19 ms |
| Memory per open stream | about 330 KB | about 165 KB (230 KB on http1) |

The leak was a reference cycle per streamed answer: the response body's callbacks reached the object that held
the body (`gateway.tov` LiveHead, headSink). Reference counting frees no cycles, so the head now lets go of the
body and its controller when the stream ends. Most of an open stream's memory is the frames of the async calls
that wait on it; whole-config arguments in those calls (the config record is about 6 KB) are made through plain
methods now, so the frames do not hold copies. Size a deployment from these figures: a worker holding 1,000 open
streams needs about 170 MB on top of its 20 to 50 MB base.

## Development

```sh
make check   # tov check --json on every file, applying "safe" fixes
make tov     # Tov with the patches in tov-patches/
make tov-test # the patches' own tests
make unit    # tov test, plus the Python tests (pricing, HTTP/2 and gRPC interop, crew priors)
make e2e     # gateway against a mock upstream, on both servers
make soak    # memory soak of one worker; fails when RSS grows (ports 18320-18321)
make smoke   # opt-in: real providers, for each one with credentials in the environment (below)
make openapi-check # docs/openapi/management.yaml against a probe gateway
make parity-count  # recount docs/parity.md and refresh its Summary table
make config-doc    # regenerate docs/config-reference.md from the config types (CI checks it is up to date)
make deploy-check  # the Dockerfile, compose file and Helm chart (helm template; needs helm)
make ui      # the web UI in headless Chromium against a real gateway
make web     # rebuild the web UI (web/) and embed it in src/ui_assets.tov
make web-check # rebuild it and fail when src/ui_assets.tov or the API types would change
make bench
```

### CI

`.github/workflows/ci.yml` runs on pull requests and pushes to `main`: it builds the patched
compiler once (cached by Tov's revision and a hash of `tov-patches/` and `scripts/build-tov.sh`),
then check, unit, openapi-check, web-check and the parity count in one job, e2e on Bun and on
http1, `make ui` in Chromium, and the memory soak (`make soak`); logs are uploaded when a job fails. Pushes to `main` also build
the Docker image (no push). `scripts/ci.sh` runs the same stages locally: `scripts/ci.sh` for all
of them, or name some (`scripts/ci.sh check unit`; `--help` lists them; `soak` runs only when named). It uses `TOV` and `BUN`
when set; with `CI_LOCK=/tmp/raiju-e2e.lock` the stages that bind fixed ports take that lock.

### Real-provider smoke tests

`make e2e` runs every provider against `tests/mock_upstream.tov`. `make smoke` (`tests/smoke.py`) runs
the real ones: it starts one gateway on port 18271 with a config built from the environment and, for
each provider that has credentials, runs a small matrix with a cheap model: chat whole and streamed,
a tool call, embeddings where the provider has them, its native route through Raiju (OpenAI
Responses, Anthropic Messages, GenAI generateContent for Gemini and Vertex, Bedrock Converse, Cohere v2
chat), a request just over `large_payload_optimization`'s threshold (set to 8 KiB there, so it takes
the streamed path), and the usage and cost of the log rows. Each check prints `ok`, `FAIL` or `skip`;
the exit status is 1 only when a check fails, so with no credentials everything skips and it exits 0.
Prompts are a few words and `max_tokens` is 16 to 64 (the large request is about 2,000 input tokens).

| Provider | Reads | Default model (embeddings) |
|---|---|---|
| openai | `OPENAI_API_KEY` | gpt-4.1-nano (text-embedding-3-small) |
| anthropic | `ANTHROPIC_API_KEY` | claude-haiku-4-5 |
| gemini | `GEMINI_API_KEY` | gemini-2.5-flash-lite (gemini-embedding-001) |
| mistral | `MISTRAL_API_KEY` | mistral-small-latest (mistral-embed) |
| groq | `GROQ_API_KEY` | openai/gpt-oss-20b |
| cohere | `COHERE_API_KEY` | command-r7b-12-2024 (embed-english-light-v3.0) |
| xai | `XAI_API_KEY` | grok-4.20-non-reasoning |
| openrouter | `OPENROUTER_API_KEY` | openai/gpt-4o-mini |
| bedrock | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_SESSION_TOKEN`, `AWS_REGION` (us-east-1) | amazon.nova-micro-v1:0 (amazon.titan-embed-text-v2:0) |
| azure | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, optional `AZURE_OPENAI_EMBED_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` (2024-10-21) | the deployments |
| vertex | `GOOGLE_APPLICATION_CREDENTIALS` (a service account key file), `VERTEX_PROJECT` or `GOOGLE_CLOUD_PROJECT` (else the key's project), `VERTEX_REGION` (us-central1) | gemini-2.5-flash-lite (text-embedding-005) |

`SMOKE_<PROVIDER>_MODEL` and `SMOKE_<PROVIDER>_EMBED_MODEL` (for example `SMOKE_OPENAI_MODEL=gpt-4o-mini`)
replace a default; `-`, `none` or `off` turn the provider (or its embeddings) off. `SMOKE_NO_BUILD=1`
uses the existing `build/raiju`. The config names every secret as `env.NAME`, so no key is written to
disk (the Vertex key file's content reaches the gateway in its environment only), and printed error
bodies have credential values masked. The gateway's own log is `build/smoke.log`. A rejected
credential fails the chat check and skips that provider's other checks.

### The web UI

The admin client is a browser app in [`web/`](web/): SolidJS 2.0 (release candidate), TypeScript,
Vite, built with [Bun](https://bun.sh). It talks to the gateway over HTTP and the `/ws` socket, and
its API types are generated from `docs/openapi/management.yaml` (`web/src/api/schema.d.ts`, by
`bun run gen`). The build is embedded in the binary through `src/ui_assets.tov`, which is generated
and committed, so building the gateway needs no Node or Bun.

```sh
cd web
bun install
bun run dev      # Vite dev server on :5173, proxying /api, /ws, /v1 to a running gateway
                 # (RAIJU_GATEWAY=http://127.0.0.1:8080 by default)
bun run check    # tsc --noEmit
bun run gen      # regenerate src/api/schema.d.ts after the spec changes
bun run build    # web/dist, hashed file names
cd .. && make web   # install + gen + check + build, then embed into src/ui_assets.tov
```

Commit `src/ui_assets.tov` and `web/src/api/schema.d.ts` with a UI change; `make web-check` fails
when they are stale. The gateway serves the page with `Cache-Control: no-cache` and an ETag, the
hashed files under `/assets/` as immutable, and gzip to clients that accept it. To serve the UI from
a directory instead of the binary (a dev build, or a CDN copy), set `RAIJU_UI_DIR=/path/to/dist`;
files there are revalidated on every request.
