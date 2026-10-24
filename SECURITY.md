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
- Link-local (169.254.0.0/16, fe80::/10), unspecified (0.0.0.0/8, ::), Teredo and the cloud metadata addresses
  (169.254.169.254, 100.100.100.200, fd00:ec2::254, metadata.google.internal) are always refused.
- Private addresses (loopback, RFC 1918, 100.64.0.0/10, fc00::/7, fec0::/10, multicast) are refused unless the
  feature's own switch or allowlist allows them.

| Target | Private addresses | Switch or allowlist |
|---|---|---|
| A2A push callbacks (set by callers with a virtual key) | refused | `server.a2a_allow_private_push_callbacks` |
| A2A agents (card, OAuth endpoints, every call) | refused | the agent's `allow_private_network` |
| Webhook endpoints | refused | the endpoint's `allow_private_network` |
| MCP servers with `require_public_target`, OpenAPI `spec_url` with dashboard auth off, MCP OAuth discovery | refused | `mcp.oauth_private_allowlist` (hosts, addresses, CIDR ranges) |
| Plugin downloads | refused | `server.plugin_download_private_allowlist` (hosts, addresses, CIDR ranges) |
| Provider `base_url` set through `/api/providers` | refused (loopback allowed) | the provider's `network_config.allow_private_network` |
| Log exporters | allowed | (only link-local and metadata addresses are refused) |

Limit: the guard resolves a name itself just before the request, and the runtime's `fetch` resolves it again to
connect. A DNS server that answers differently within that moment (DNS rebinding with a zero TTL) is not stopped;
closing that gap needs the check inside the runtime's connect, which Tov's `fetch` does not offer yet.

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
