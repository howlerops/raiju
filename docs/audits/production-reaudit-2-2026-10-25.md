# Raiju production re-audit 2 (8099015, after wave 25)

Verdict: not ready for multi-tenant production yet; usable for a single tenant. All three earlier P0s are
fixed and measured (cluster secret: literal-key HMAC now 401; 6 x 90 MB unauthenticated bodies: all 401 at
21.8 MB peak RSS, was 707 MB; 40 concurrent creates on 4 workers: 40 kept, was 11). No new P0. Four new P1s,
all availability problems introduced by the wave 25 fixes.

## Earlier findings

| Item | Status |
|---|---|
| P0-1 cluster secret | Fixed: short, unset and empty secrets refused at start; literal-key HMAC 401, real key 200 |
| P0-2 body memory DoS | Fixed on the main listener for inference (gaps: new P1-3, P1-4) |
| P0-3 lost concurrent saves | Fixed (40/40) |
| P1-1 per-process state | Partly fixed: sessions, OIDC flows and agent tokens shared in 0600 files; jobs not across nodes or restarts |
| P1-2 sign-in hardening | Fixed (from the code): bcrypt cost 10, throttling, trusted proxies |
| P1-3 /metrics | Fixed, opt-in (server.metrics_token or cluster.serve_metrics) |
| P1-4 SIGKILL stops node | Fixed (0019; backoff 1 s doubling to 30 s) |
| P1-5 ECS module | Fixed in terraform, not applied on AWS |
| P2s | Fixed or explained (state versions, advertise_address and soak reads not re-checked) |

## New P1

1. **A waiting file lock freezes the worker for up to 10 s and burns CPU.** `filelock.tov:40-70` retries
   `mkdirSync` in a synchronous loop with no sleep (callers: store.tov:1392, sharedtable.tov:97 and :111,
   webhooks, mcpissuer, mcpuser). With a stale `config.json.lock`, a `/health` during the wait took 9.49 s.
   The stale takeover is racy (filelock.tov:58-66): two waiters can both delete and take it. Fix: async
   backoff or flock(2); take over a stale lock by rename so a waiter never deletes a fresh lock.
2. **Unauthenticated `GET /api/oidc/login` rewrites the whole shared flow file under the lock.**
   ops.tov:5528-5534 → `flows.begin` → `SharedTable.put` (oidc.tov:159) rereads, serializes every row (cap
   10,000) and fsyncs. Under steady requests `/health` fell from 15,377 rps to 26 rps on 4 workers, and real
   users' pending sign-ins are pushed out once the table fills. Fix: keep nothing at /login (a sealed, signed
   state value the callback checks) or keep it in memory with a per-IP limit; stop rewriting the whole file.
3. **The cluster listener reads bodies up to 100 MB before checking the HMAC** (main.tov:170,
   server.tov:1243-1262, front.tov:254-256), outside the body budget. Any host that can reach the cluster port
   can OOM the pod. Fix: cap cluster bodies at a few MB, refuse a missing signature before reading, charge the
   budget.
4. **One slow body can hold a worker's body budget so every other POST gets 503.** The budget admits a lone
   body over the cap (bodybudget.tov:43-50), a declared length is charged in full before reading
   (server.tov:1135-1140), and the body timeout limits only the gap between bytes. Routes that skip the header
   credential check (server.tov:1066-1072, :1109; /api/session, /api/agent, /api/oauth2, /api/oidc, /mcp,
   plugin-hooked or auth-off inference) let an unauthenticated client trickle a 100 MB declared body. Fix:
   charge bytes as they arrive, give charged bodies a total deadline, give public routes a small body limit.

## P2

1. `GET /api/cluster/leader`'s signature covers an empty body and can be replayed (cluster.tov:257): sign
   method, path and a timestamp.
2. `SharedTable.take` and `change` ignore `lock.ok` (sharedtable.tov:97-114): check it and fail the request.
3. /metrics open by default: warn at start when neither `metrics_token` nor `serve_metrics` is set.

## Checked and fine

Worker respawn backoff (no fork storm); shared session files 0600 with sealed secrets; chunked bodies get
the header credential check; every bad cluster secret refused at start.
