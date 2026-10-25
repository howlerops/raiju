# Raiju production re-audit 3 (cd7cffb, after wave 26)

Verdict: not ready for multi-tenant production; single tenant on the default chart (1 worker, ReadWriteOnce,
Recreate, MCP OAuth off) is fine. Wave 26 fixed what it targeted and the re-audit 1 P0s stay fixed (literal-key
HMAC 401; 6 x 90 MB unauthenticated: 401 at 22.2 MB peak; 40/40 concurrent creates kept). No new P0; four P1s.

## Re-audit 2 findings

| Finding | Status |
|---|---|
| P1-1 lock wait freezes the worker | Fixed for the repro (/health 0.5-1.7 ms while a save waits 25 s; no stale takeover) — see P1-A, P1-C |
| P1-2 /api/oidc/login rewrites the flow file | Fixed (8.8k rps flood: /health 13.7k to 4.0k rps, was 26; nothing written) |
| P1-3 cluster listener reads 100 MB before the HMAC | Fixed for unsigned; partly overall (P2-A) |
| P1-4 one slow body holds the budget | Partly fixed (P1-D) |
| P2-1 leader replay, P2-2 lock.ok, P2-3 /metrics warning | Fixed |

## New P1

- **P1-A: the config lock is held across the whole management route, network calls included** (server.tov:795-950,
  scimRoute :723-725; refresh-models, pricing, MCP spec fetch and reconnect, agent cards, OAuth exchange). When the
  15 s wait fails the route still runs and saves fall back to a 500 ms sync sleep (store.tov:1393,
  filelock.tov:84-86). A refresh-models on 6 keys with a dead base_url held it 30 s: 19 of 24 concurrent creates on
  other workers got 500 and /health peaked at 3.5 s. Fix: lock only around reread-merge-save with an async wait,
  do I/O before it, answer 503 without running the route on timeout, never sleep synchronously in a request.
- **P1-B: unauthenticated /oauth2/register and /oauth2/authorize rewrite the whole MCP OAuth state file, with no
  client cap** (mcpissuer.tov:433-479, :532, persistGrants :235-279). With mcp_server_auth_mode "both" on 4 workers a
  register flood took /health from 14,984 to 14 rps; 4,660 clients in 30 s; real grants dropped ("locked by another
  process"). Fix: cap clients globally and per IP, expire unused ones, keep requests in memory or sealed in the
  consent link, stop rewriting the whole file per request.
- **P1-C: old and new versions on one volume lose acknowledged saves** (mkdir `config.json.lock` vs flock
  `config.json.flock`), and the ECS module (min healthy 100%, max 200% with EFS) and the helm RollingUpdate with
  ReadWriteMany overlap them: wave 25 + wave 26 binaries, 40 creates, only 26-28 kept. Fix: for one release take the
  old mkdir lock inside the flock (or refuse to start while a fresh old lock exists), or Recreate / min healthy 0.
- **P1-D: an unauthenticated client can still hold the body budget for 120 s** (server.tov:1158 sends /mcp,
  /v1/mcp/* and plugin-hooked or auth-off inference straight on; bodybudget.tov:49-53 admits a lone body). 48 MB
  sent fast to /mcp then 1 byte every 2 s: every POST over 64 KB got 503 for 120 s. Fix: a header credential check
  on /mcp before big bodies, or a small budget share and short deadline for unchecked bodies.

## P2

- **P2-A**: the cluster "signature first" check only checks the header's shape (cluster.tov:281-290): fake-signed
  15 MB bodies are read (4 workers: 984 MB peak). Fix: a header HMAC over method, path, timestamp and length before
  reading; a separate peer budget.
- **P2-B**: the fixed 120 s body deadline applies to authenticated clients (100 MB needs ~7 Mbps). Fix: a minimum
  average rate, or the fixed deadline only for unchecked bodies.
- **P2-C**: OIDC without an encryption key fails across nodes (main.tov:300-309). Fix: derive the state key from
  cluster.secret when clustered, or warn.
- **P2-D**: the OIDC state is not bound to the browser (login CSRF; ops.tov:5572-5585). Fix: an HttpOnly
  SameSite=Lax cookie with the state's hash, checked at the callback.

## Only real infrastructure can check

flock on EFS/NFS (POSIX locks; a crashed node's lock lasts until the lease expires), ECS/EKS rolling upgrades,
memory against 512Mi with real traffic, real IdPs with the sealed state, real provider latency (drives P1-A),
multi-node clusters over a real network, the ECS terraform applied on AWS.
