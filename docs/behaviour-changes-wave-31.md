# Behaviour changes in waves 31 and 32

Waves 31 and 32 (L212 to L219) closed the known gaps listed after wave 30, fixed the seventh production re-audit (docs/audits/production-reaudit-7-2026-10-31.md) and made the CI image job run on pull requests. Read this before upgrading a deployment.

- **Dashboard presentation**: desktop navigation is now a persistent sidebar,
  with a compact header, roomier cards/tables and a responsive horizontal
  navigation strip on smaller screens. Fleet summary counts come only from
  configured gateways and current public readiness probes; no regional
  inference or usage data is aggregated. Authentication and targeting are unchanged.
  Same-region hash routes preserve the sidebar/header, including during regional
  bootstrap. Screens are lazy-loaded JS chunks with a route-local loading/error
  boundary reset on navigation; existing widget boundaries let ready data render
  independently of slower widgets. Back/forward navigation stays client-side.
  Region and identity changes still deliberately reload the whole document.
  Appearance offers System/Light/Dark, persists locally and follows OS changes
  in System mode. Tailwind 4 and daisyUI 5 provide the actual buttons, form
  controls, badges, cards, statistics and tables. Canonical light/dark themes
  use restrained purple accents and standard corner radii; the earlier
  Party Rock hard-shadow styling and conflicting component CSS are removed.
  Solid 2 and the embedded static build remain; no React or component JS runtime
  is introduced. Both explicit and OS-following modes share the daisyUI tokens.
  Gateway selection, origin, health, isolation details, appearance and account
  controls live in a persistent sidebar; the content header shows only the page.
  Navigation scrolls independently on shorter desktops, while narrow screens
  keep all controls accessible in a stacked layout.
  Local frontend overrides are now published into disposable snapshots: new
  assets precede the new HTML, and previous hashed chunks remain available for
  open tabs. Rebuilding Vite's output alone no longer changes the running preview.
  Noncompact loading states use accessible daisyUI skeletons for pages, forms,
  tables and content, including bootstrap and pending Playground responses.
  Component-local boundaries remain independent. Buttons, compact status badges,
  empty states and errors retain their existing behavior; reduced-motion users
  receive static skeletons.

- **Breaking owned-name cutover**: configure `RAIJU_*` environment variables
  (including `RAIJU_SETUP_TOKEN` and `RAIJU_HOST`); bootstrap management with
  `X-Raiju-Setup-Token`. Request and response gateway headers now use `x-raiju-*`,
  generated virtual keys use `sk-raiju-`, agent access tokens use `ck-raiju-agent-`
  and agent refresh tokens use `rt-raiju-agent-`. Gateway metrics use `raiju_*`,
  plugin-owned names use Raiju, and owned error flags use `is_raiju_error`.
  MCP OAuth JWTs use the `raiju_mode` private claim. Grant responses use
  `raiju_mode`, `raiju_sub` and `raiju_sub_display`; the grant-list filter is `raiju_mode`.
  No previous owned env/header/token/metric/plugin/claim names are accepted as aliases.
  Update clients, secrets, dashboards and scrape queries together; existing
  old-prefix credentials must be replaced. This change is not a new successful
  infrastructure proof or a completed 24-hour soak.
  Cryptographic domain labels changed too: old encrypted values and sealed OAuth/OIDC
  clients, consent links and sign-in states are not portable across this boundary.
  Stop first; use a fresh config/state directory with securely recreated credentials
  and registrations. Retain the old directory for rollback. Do not run mixed versions
  over encrypted or OAuth state. The default unencrypted configuration can retain its
  ordinary settings, but credentials and clients still need the name cutover above.
  Exact third-party URLs, upstream source identifiers and benchmark product
  identities remain unchanged where needed for accurate sourcing/comparison;
  historical ledger and audit observations retain their recorded evidence.

- **Mantle streaming correction**: `bedrock_mantle` chat requests with `stream:true`
  now use the upstream incremental stream instead of replaying a completed answer.
  OpenAI-compatible models use the existing OpenAI SSE converter; Claude-family
  models use the native Messages converter. Usage remains accounted for when the
  caller hides usage events. Regional endpoints, bearer/SigV4 auth, project headers,
  prompt-cache controls and non-streaming calls keep their existing behavior.
  This does not add Mantle embeddings. Real dev Qwen exposed the buffering bug;
  final-image installed OpenAI/LangChain qualification passed 17 checks.

- **Shared MCP signing-state initialization**: nodes sharing a state directory
  serialize signing-key load/create/save under its bounded startup flock. A
  generated key is not activated until its private state file is durably written.
  With OAuth enabled, failure to open that state now fails startup before workers
  or readiness rather than leaving a healthy-looking node with OAuth disabled.
  The previous race issued client IDs that other live nodes rejected. Corrected
  real three-node startup produced one JWKS key and nine valid same/cross-node authorizations.

- **Shared MCP credential rotation**: a worker now awaits its pending config save
  before releasing the retained admin credential's renewal lease. Previously the
  save callback discarded that promise, so another worker could send the old
  rotating refresh token again before the saved replacement became visible.
  This does not share MCP transport sessions or make provider rotation and disk
  persistence one crash-atomic transaction. Corrected-image qualification is required.

- **Native environment references**: compiler patch 0024 supports computed
  `process.env[name]`, so `env.NAME` config references no longer depend on
  `/proc/self/environ` and work on macOS as well as Linux. Unset names remain
  unset and present empty values remain empty. Names containing NUL bytes are
  rejected rather than resolving a different, truncated name. This does not load
  `.env` files automatically; environment-backed rotation still requires restart.

- **Soak completion credit**: HTTP 200 alone is insufficient. Chat choices must
  contain typed message payloads; stream choices must contain typed deltas and
  end with `[DONE]`. Malformed nonempty choices no longer count as successful
  inference; usage-only chunks with empty choices remain valid within a stream.

- **Linux WebKitGTK GC crash**: compiler patch 0025 initializes WTF's main thread
  and run loop before creating the JavaScript VM. The observed Fargate full-GC
  crash dereferenced its missing main loop through the memory-pressure handler.
  The focused Linux proof now runs the real handler and full collector, including
  finalization callbacks. GC and memory-pressure handling remain enabled; macOS
  and the own-engine path are unchanged. The deployed 24-hour stability gate is
  still required.

- **Native multi-worker startup**: workers now re-execute the gateway with fresh
  JavaScriptCore/native state while adopting the supervisor's listeners and
  retaining its node identity, shared-state directory and sign-in state key.
  Previously, DNS or another JavaScript-backed startup operation could initialize
  a VM before the worker fork; garbage collection then waited indefinitely for a
  collector thread that did not survive the fork. This is separate from the
  WebKitGTK main-loop crash fixed by patch 0025. Worker respawn/backoff and graceful
  shutdown remain enabled; `http1` remains single-process.

- **Optional multi-gateway console**: `RAIJU_CONSOLE_CONFIG` names a read-only public
  manifest of gateway labels and origins; absent configuration retains the
  single-gateway UI. Fleet status aggregates only health/readiness. Regional
  sessions are scoped by origin in tab storage; switching identity or gateway
  reloads the page, clearing forms, data and sockets. Writes and Playground calls
  target one explicitly selected origin, without a cross-region proxy or fallback.
  Native CORS supports bearer/setup preflight while actual requests retain their
  authentication gates. Remote UI sockets require an explicitly permitted Origin
  and a one-use ticket. Those tickets now use private hashed files beside the
  configuration (`<config>.ws-tickets/`) so a different worker or replica sharing
  that directory can redeem them once; directory-operation failures deny access.
  Gateways without shared session storage still require appropriate session
  affinity. No cloud account, customer endpoint or geography is a product default.

- **Embedding SDK fidelity**: translated OpenAI embedding responses now honor
  `encoding_format:"base64"` as IEEE754 float32 little-endian bytes. This fixes
  silent vector corruption in the OpenAI SDK, which requests base64 by default.
  Numeric default/`"float"` responses and native AWS InvokeModel remain unchanged;
  already-encoded upstream strings are not encoded twice. Ordinary/large requests,
  both embedding API paths, batch order, dimensions, usage and metadata are covered
  by the independent `struct`/base64 wire regression on Bun and http1. Hugging Face
  large embeddings use the existing bounded buffered converter, not invalid
  OpenAI-wire passthrough. Shared float packing preserves signed zero and rounds
  ties to even. The new regression runs in CI and local E2E commands.

- **L215**: the CI image job runs on pull requests too: it builds the image, boots it as the chart runs it (read-only root, uid 65532, caps dropped) and scans it with trivy (database from ghcr.io, then public.ecr.aws, then mirror.gcr.io, cached); the runtime image now runs `apt-get upgrade` to take Debian security fixes released since the pinned base.
- **L212**: realtime and live WebSockets to a provider whose base_url resolves to a private non-loopback address need `network_config.allow_private_network`, as every other provider connection does (link-local, unspecified and metadata addresses are refused); a Redis/Valkey vector store on a link-local, unspecified or metadata address is refused; A2A gRPC connections are checked at connect under the agent's allow_private_network (tov-patches 0022); on Bun.serve a WebSocket client that stops reading is dropped after `server.idle_timeout_seconds`, as on http1.
- **L214**: the AWS default chain follows the SDK's order (environment keys before AWS_PROFILE; an AWS_PROFILE naming a missing profile is an error) and reads ~/.aws/config profiles (role_arn chains, credential_process, SSO, region) for Bedrock keys without credentials and Vertex workload identity; the Maxim exporter uploads attachments when include_content is on; an access profile naming one MCP client two ways across mcp_configs and the deprecated mcp_servers is not loaded; a Bedrock rerank fallback sends what its attempt's pre hooks made of the request.
- **L213**: async jobs are kept in `<config>.jobs/` and provisioning jobs in `<config>.provision-jobs.json` beside the config (keep it on the data volume): both survive restarts, and a poll on another node finds the job over the new peer route `POST /api/cluster/jobs` (older nodes answer 404 during a rolling upgrade); a job whose runner stopped (no heartbeat for 45 s) reads as failed with status_code 500; sign-in failures count across the cluster's nodes; an empty body reservation can be cut 200 ms after admission and a tenant reconnecting at once gets no fresh grace; two or more virtual keys with no customer or team give a start-up warning and a dashboard notice.
- **L218**: a declared body that has sent nothing can be cut to its look-ahead at any age, so a burst of empty declared bodies is admitted and may be refused part way when it sends; a body sending under 8x `server.body_min_kb_per_second` (256 KB/s by default) can be cut under contention and one above it never is (a newcomer that needs its room gets 503); a tenant that abandoned a declared body reserves only the look-ahead for 60 s; the reserve past the cap applies only beside a single body over the cap (46 + 12 MB at a 48 MB cap is refused).
- **L217**: closed WebSocket sessions are freed (realtime, Responses and live sessions no longer leave 2-16 KB each; `make soak-websockets` in the CI soak job fails on RSS growth); the /v1/responses WebSocket answers 401/403 before upgrading while inference auth is enforced, and the /v1/live/sessions primary answers 401 without a credential before upgrading; live session owner records expire 1 h after the session ends (24 h backstop) and the registry evicts ended records instead of refusing new sessions at 10,000.
- **L219**: MCP server sessions are capped per process (`mcp_server.max_sessions`, 10000) and per caller (`mcp_server.max_sessions_per_caller`, 1000); a new session past either cap drops the oldest idle one, whose next request gets 400 "missing or unknown Mcp-Session-Id"; expiry no longer scans every session on each request; new gauge `raiju_mcp_sessions`; unknown `mcp_server` keys are now reported as ignored.
- **L216**: no user-visible behaviour change: memory per inference request no longer grows (~50 B per request with a virtual key, ~100 B with content logging), from a Tov compiler fix (tov-patches 0023: `continue` now releases the loop body's locals); `make soak-slope` in the CI soak job fails when RSS grows past 10 B per request.
