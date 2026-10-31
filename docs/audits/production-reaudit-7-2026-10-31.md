# Raiju production re-audit 7 (b135bc9, after wave 30)

Verdict: not ready for multi-tenant production. Wave 30 fixed P0-A (bun 6 min, ~40 GB of 200 KB-4 MB bodies:
RSS 82-100 MB, was 20 to 836 MB in 100 s) and P1-B (40/46 MB beside small chats 8/8), and partly P1-A. Every
earlier P0 and key P1 stays fixed. A fresh memory pass measuring RSS over time found two P0s.

## P0-1: every inference request leaves ~50 bytes resident, with no plateau

Small chats on bun, 10 min, 1.47M requests: 23 to 92 MB, linear (7.4 MB/min, ~49 B/request); same with stdout logging
off, streams, or a new connection per request; http1 ~70 B/request. /health and /v1/models stay flat, and so do a
plain Tov fetch loop and a bare Bun.serve: the growth is in the gateway's inference path. The log store adds to it
(content logging on ~0.24 KB/request over 500k). At 500 rps per worker the chart's 512Mi pod is OOM-killed in ~4-5 h.
Fix: bisect the chat path (credential check, governance admit/charge, dispatch, metrics, record) with a soak that
disables one stage at a time; add ~1M small chats to the CI soak asserting the RSS slope.

## P0-2: WebSocket sessions leave 2-5 KB each, reachable without a credential

Realtime sessions with a key: 22 to 538 MB over 98,957 sessions (~5.2 KB each), not returned when idle; live
sessions ~6 KB; /v1/responses open/close ~2.2 KB. With enforce_auth_on_inference on and no credential,
/v1/responses still upgrades (server.tov:2133 creates the session before any credential check) and leaks ~2.1 KB per
socket. Close style and server do not matter. A bare Bun.serve WebSocket is flat, so most of it is gateway code
(SocketExt/Session/Relay, realtime.tov:354-520, webrtc.tov Relay); the runtime client WebSocket keeps ~0.57 KB per
closed socket. Fix: find and break what keeps a closed session reachable, check credentials before upgrading
/v1/responses, add a WebSocket open/close soak to CI.

## P1

- **P1-1 (rest of P1-A)**: reservations younger than 1 s are never cut (bodybudget.tov:224, :329); four tenants
  declaring 12 MB, sending nothing and reconnecting every 0.9 s keep outsiders' 1-4 MB bodies at 503 (185/187). Fix:
  let a reservation that has received nothing be cut at any age; stop reserving the whole length for a tenant whose
  recent reservation was abandoned.
- **P1-2 (wave 30 regression)**: take() (bodybudget.tov:399-404) cuts behind-pace reservations then refuses the
  newcomer anyway; a cut body's further bytes are held to cap - reserve (:439); "behind" is a fixed 10 s, not the
  32 KB/s floor; a newcomer past its share may cut (:434). A 30 MB upload at 1 MB/s was refused at 12-24 MB in two
  scenarios that wave 29 served. Fix: cut only when cutting everything eligible lets the newcomer fit; only a newcomer
  within its share may cut; judge "behind" against the configured minimum rate.
- **P1-3**: MCP sessions are uncapped (mcpserver.tov:397-455) and every POST /mcp scans all of them (ops.tov:7218),
  living 30 min: one key looping initialize made 49k sessions in 150 s and another tenant's chat p50 went 2 to 202 ms.
  Fix: cap per caller and in total, evicting the oldest; expire from an ordered structure or a timer.
- **P1-4**: LiveRegistry.owners (live.tov:42, :81-111) is never cleaned and is capped at 10,000; after that every new
  live session is refused (20,521/20,521) until restart. Fix: delete the owner record (and its share-dir folder) when
  the session ends, or give it a TTL.

## P2

- **P2-1**: biggest() (bodybudget.tov:290-297) sums per tenant, so one tenant's several bodies get the "reserve past
  a lone body" allowance (60 MB in hand with a 48 MB cap). Fix: apply it only when one body is over the cap.

## Checked and sound

Per-read race settled; other Promise.race sites; the 3 s waiting window; the deadline queue; unauthenticated MCP and
SSE churn flat; cluster logs and feed bounded by the 10,000-row ring; broker; metrics label caches, affinity,
response cache and DCR state bounded.

## Only real infrastructure can confirm

flock on EFS/NFS and the bridge's stale rule under clock skew; ECS/EKS rolling and stop-first upgrades; real memory
against 512Mi with real bodies, provider latency, long uptimes and worker respawn under the OOM killer; ALB with
RAIJU_TRUSTED_PROXIES; real IdPs and cookies behind TLS proxies; multi-node clusters and a broker over a real
network; real provider realtime and live endpoints; the ECS terraform applied on AWS.
