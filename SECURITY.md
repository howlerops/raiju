# Security

## Reporting a vulnerability

Please report security issues privately, not in a public issue or pull request: use GitHub's private
vulnerability reporting on this repository (the **Security** tab, then **Report a vulnerability**). Include the
Raiju commit or image tag, the config sections involved (with secrets removed), and the steps or request that
show the problem.

Issues in a vendored library below are fixed by updating the library in the Tov runtime (`tov-patches/`, then
`make tov`); report them upstream as well.

## Outbound requests

Every outbound URL a user or caller controls goes through one address guard (`src/netguard.tov`), which matches
Bifrost's `core/network/ssrf.go`:

- Hosts are read the way the resolver reads them, so another spelling of an address is the same address: IPv4 in
  any `inet_aton` form (`2130706433`, `0x7f000001`, `0177.0.0.1` and `127.1` are all 127.0.0.1), IPv6 with an
  embedded IPv4 address (IPv4-mapped, IPv4-compatible, 6to4, NAT64), zones and trailing dots.
- Host names are resolved right before each request and every address they resolve to is checked, so a public
  name that points at a private address is refused like the address.
- The runtime checks again when it connects (`tov-patches/0013`, fetch's `peer` option): every address the host
  resolves to at that moment, for each redirect and each new pooled connection, under the same rules. A name that
  resolves to a public address when the guard looks and to a private one when the connection is made (DNS rebinding
  with a zero TTL) is refused, and connections made under different rules are never shared.
- Link-local (169.254.0.0/16, fe80::/10), unspecified (0.0.0.0/8, ::), Teredo and the cloud metadata addresses
  (169.254.169.254, 100.100.100.200, fd00:ec2::254, metadata.google.internal) are always refused.
- Private addresses (loopback, RFC 1918, 100.64.0.0/10, fc00::/7, fec0::/10, multicast) are refused unless the
  feature's own switch or allowlist allows them.

| Target | Private addresses | Switch or allowlist |
|---|---|---|
| Every provider connection (`base_url` from the config file or the API, key-level URLs, model listings, token endpoints configured on a key) | refused (loopback allowed) | the provider's `network_config.allow_private_network` (as Bifrost's `ConfigureDialer`) |
| A2A push callbacks (set by callers with a virtual key) | refused | `server.a2a_allow_private_push_callbacks` |
| A2A agents (card, OAuth endpoints, every call) | refused | the agent's `allow_private_network` |
| Webhook endpoints | refused | the endpoint's `allow_private_network` |
| MCP servers with `require_public_target`, OpenAPI `spec_url` with dashboard auth off | refused | `mcp.oauth_private_allowlist` (hosts, addresses, CIDR ranges) |
| MCP OAuth (discovery, client registration, code exchange and refresh, per-user OAuth), token exchange endpoints and the identity provider's discovery | refused | `mcp.oauth_private_allowlist` |
| Plugin downloads | refused | `server.plugin_download_private_allowlist` (hosts, addresses, CIDR ranges) |
| The MCP library catalog (`pricing_sync.mcp_library_url`), log exporters, vector stores (Qdrant, Weaviate, Pinecone) | allowed | (only link-local, unspecified and metadata addresses are refused) |

Redirects: webhooks, A2A push callbacks, agent cards and their OAuth endpoints, exporters, and OAuth and token
exchange POSTs follow none. Plugin downloads check each hop. A2A calls follow a redirect only on the origin they
were sent to (Bifrost's rule), and an MCP OpenAPI tool call that carries credentials (a query, or a header besides
`Accept` and `Content-Type`) gets a redirect to another host, or from https to http, back as the 3xx result.

Limits: through a proxy (a provider's `proxy_config`, the global proxy, `HTTP_PROXY`) the proxy resolves the host,
so only an address written in the URL is checked, as Bifrost does. Connections that do not go through `fetch` (raw
sockets) are not checked by the runtime: A2A agents called over gRPC are checked by the guard just before each call
(the rebinding window stays open there), and Redis or Valkey vector stores and realtime WebSocket connections to
providers are not checked.

## Sign-in

- **Passwords** are stored as bcrypt hashes (cost 10, Bifrost's form: `governance.users[].password_hash`, and
  `auth_config.admin_password` is hashed in memory unless it is already a bcrypt hash). A user still holding the
  old salted SHA-256 form (`salt` + `password_sha256`) signs in with it once and gets a bcrypt hash saved in its
  place. A password checked once is remembered in the process for ten minutes (by an HMAC with a per-process key),
  so Basic credentials on every request cost one bcrypt run; a wrong password is never remembered.
- **Unknown users** are checked against a dummy hash, so a sign-in takes as long whether or not the account exists.
- **Brute force:** failed sign-ins are counted per account name and per client address, for the whole node (the
  workers share the counts): past `server.sign_in_throttle.account_failures` (5) or `ip_failures` (20) failures
  within an hour, each attempt waits twice as long as the last (1 s up to `max_backoff_seconds`, 900) and is
  answered 429 with Retry-After without being checked. This covers the dashboard login, Basic credentials on `/api`
  and on inference (per account only there), the CLI's agent sign-in, the setup token and failed OIDC callbacks (the
  last two per address).
  Unknown names are counted like real ones. A lock that someone else caused does not cut off a client whose
  password the process verified lately. Counts are per node: several replicas each allow their own.
- **Client addresses:** the audit log and the throttle use the TCP peer. `X-Forwarded-For` and `X-Real-IP` are read
  only from the proxies listed in `server.trusted_proxies` (addresses or CIDR ranges), from the right, skipping
  trusted hops. Behind a load balancer or ingress, list its addresses, or every client shares the proxy's address
  (and its throttle count). The MCP authorization server's open registration (`/oauth2/register`) counts clients
  by the same address (an IPv6 address by its /64): `client.oauth2_server_config.registrations_per_minute` (10) and
  `max_unused_clients_per_address` (20) answer 429 with Retry-After, `max_unused_clients` (1000) drops the oldest
  clients that hold no grant, and such a client lives an hour. Neither registration nor `/oauth2/authorize` writes
  the grants file (authorize stores nothing: the request is sealed into the consent link).
- **Single sign-on:** a login stores nothing (its state is sealed with AES-256-GCM under a key derived from
  `encryption_key`, else from `cluster.secret` with clustering on, else a key the node makes at its start, so set one
  of the first two when several nodes serve SSO). The state is bound to the browser that began the sign-in: the login
  sets an HttpOnly, SameSite=Lax cookie with the state's hash (Secure over https), and the callback refuses a state
  without it, so a link carrying an attacker's own state and code cannot sign a victim in as the attacker.

## Plugins

WebAssembly plugins see every request and response that passes through the chain. A plugin whose `path` is a URL:

- must be https; plain http is accepted only when the entry pins the file with `sha256` (64 hex digits);
- is checked against its `sha256` pin when it is downloaded and again each time it is loaded (a local `path` can be
  pinned the same way);
- is kept in a private cache folder (mode 0700): `plugin-cache` beside the config file, or `$TMPDIR/raiju-plugins`
  when that folder is read-only, or `RAIJU_PLUGIN_DIR`. The gateway refuses to write to, or load from, a cache
  folder that other users can write to.

## WebRTC

Realtime calls over WebRTC (`POST /v1/realtime/calls` and GPT Live's WebRTC sessions) terminate the peer inside
the gateway process with the C libraries below, so any caller with a virtual key reaches their DTLS, SCTP and SRTP
parsers. WebRTC is therefore off by default and must be enabled explicitly (WebSocket realtime is unaffected).
Enable it only if you need it, and track the advisories for these libraries, usrsctp above all: its upstream has
been inactive since about 2023.

## Vendored native dependencies

The gateway binary statically links these C and C++ libraries through the Tov runtime (`build/tov/vendor/`, each
with a `TOV.md` naming its source and digest). Versions are as of this commit; check them against the advisories
of each project when you deploy.

| Library | Version | Used for | Reached by | Advisories |
|---|---|---|---|---|
| BoringSSL | 0.20260929.0 | TLS for every upstream and listener, crypto | all TLS traffic | https://github.com/google/boringssl/security |
| nghttp2 | 1.64.0 | HTTP/2 to providers (`enforce_http2`), A2A gRPC | upstream responses | https://github.com/nghttp2/nghttp2/security |
| zlib | 1.3.1 | gzip and deflate bodies | upstream responses, request bodies | https://zlib.net |
| brotli | 1.2.0 | `br` bodies | upstream responses | https://github.com/google/brotli/security |
| zstd | 1.5.7 | `zstd` bodies | upstream responses | https://github.com/facebook/zstd/security |
| libdeflate | 1.24 | fast gzip and deflate | upstream responses, request bodies | https://github.com/ebiggers/libdeflate |
| WAMR (wasm-micro-runtime) | 2.4.5 (interpreter) | WebAssembly plugins | plugin modules (admin-configured) | https://github.com/bytecodealliance/wasm-micro-runtime/security |
| libdatachannel | 0.24.6 | WebRTC peer | WebRTC callers (off by default) | https://github.com/paullouisageneau/libdatachannel/security |
| libjuice | `b89c792` (pinned by libdatachannel 0.24.6) | ICE, STUN, TURN | WebRTC callers (off by default) | https://github.com/paullouisageneau/libjuice |
| usrsctp | `fec583d` (pinned by libdatachannel 0.24.6; release line 0.9.5) | SCTP for data channels | WebRTC callers (off by default) | https://github.com/sctplab/usrsctp (inactive upstream) |
| libsrtp | 2.8.0 | SRTP media | WebRTC callers (off by default) | https://github.com/cisco/libsrtp/security |
| plog | `94899e0` (headers) | logging inside libdatachannel | none from the network | https://github.com/SergiusTheBest/plog |

To update one: replace its files as its `TOV.md` describes, rebuild the compiler (`make tov`) and run
`make tov-test`, `make unit` and the e2e suite.
