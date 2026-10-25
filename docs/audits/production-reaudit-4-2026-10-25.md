# Raiju production re-audit 4 (4ba8788, after wave 27)

Verdict: not ready for multi-tenant production yet. Wave 27 fixed what it targeted (7 of 8 re-audit-3 findings
fixed, P1-B partly); the earlier P0s stay fixed (6 x 90 MB: 401 at 22.0 MB peak; literal-key HMAC 401; 40/40
creates). No P0; two new P1s. Single tenant on the default chart (1 worker, ReadWriteOnce, Recreate, MCP OAuth
off) is fine.

## Re-audit 3 findings

| Finding | Status |
|---|---|
| P1-A lock across network I/O | Fixed: 24/24 creates while a 30 s refresh runs; held lock gives 503 at 15.03 s, 0 CPU while waiting |
| P1-B register/authorize rewrite the state file | Partly fixed: one-address flood 9 created, 57,746 429s, /health 15.1k to 13.4k rps; see P1-F |
| P1-C wave 25 + new on one volume | Fixed: 40/40 x 3 (wave 25 and wave 26 against wave 27) |
| P1-D unauthenticated body hold | Fixed for unauthenticated clients; see P1-E |
| P2-A fake-signed peer bodies | Fixed on the gateway (48 x 401, 22.9 MB peak); broker still reads them (P2-H) |
| P2-B fixed deadline for authenticated bodies | Fixed |
| P2-C OIDC across nodes | Fixed when clustered |
| P2-D login CSRF | Fixed |

## New P1

- **P1-E: the rate rule lets any tenant hold the node's whole body budget for ~26 minutes.** `rateDue = grace +
  got / rate` (bodybudget.tov:86-89) is a running average from the start, so early bytes earn credit; armRate
  (server.tov:1338-1350) reschedules against it; other checked bodies are refused once seen + n > cap
  (bodybudget.tov:135-136). A valid key declaring 100 MB, sending 48 MB at once then 1 byte every 2 s kept other
  callers' 200 KB chats at 503 for 200 s (bound 10 s + 48 MiB / 32 KiB/s = 1,546 s per connection). Fix: a sliding-
  window rate, a hard ceiling on body time, and a per-credential share of the cap.
- **P1-F: unauthenticated registrations evict other users' pending MCP OAuth clients** (mode "both" or "oauth").
  The oldest unused clients are dropped past max_unused_clients (1000) or 8 MB (mcpissuer.tov:527-538, :71); 150
  source addresses registered 1,500 clients in 1.4 s and a user's in-flight authorize then got 400 unknown
  client_id. Behind a proxy without trusted_proxies (the ECS module sets none) everyone shares one address. Fix:
  stateless registration (a sealed client_id carrying the metadata, persisted at the first grant), or never evict a
  client younger than the consent lifetime and answer 429; set trusted_proxies in the ECS module.

## P2

- **P2-G**: Math.random is seeded with 0 in every process (runtime tov.c:2502-2512), so ids built from it
  (schemas.tov:93-97, otel trace ids) collide across workers and nodes: 5/60 concurrent webhook creates on 4 workers
  got 409. Fix: seed from getrandom(2) and reseed after fork; build entity ids with secureHex.
- **P2-H**: broker mode reads unsigned 16 MB bodies before the HMAC (broker.tov:91-93; 32 x 15 MB: 471 MB peak) and
  its GET roster signature never changes. Fix: the head HMAC and peer budget in brokerRoute; a timed GET signature.
- **P2-I**: during a rolling update with MCP OAuth on, clients registered on wave 27 pods are unknown to wave 26 pods
  (mcp-oauth-state-clients.jsonl). Fix: document stop-first for this upgrade, or write both for one release.
- **P2-J**: every admin write rewrites the whole config (store.tov:1473-1500): with 5,000 keys 200 concurrent
  creates gave 37 x 503 (nothing lost). Fix: batch or group-commit saves, or an append log; document a ceiling.
- **P2-K**: a direct provider key is not "checked" (governance.tov:545-550), so allow_direct_keys callers get the
  unchecked 30 s deadline and the small share. Fix: count a direct key matching a configured provider key as checked.

## Only real infrastructure can confirm

flock on EFS/NFS (lease expiry), the bridge's 10 s stale rule on NFS with clock skew, ECS/EKS rolling upgrades,
memory against 512Mi with real bodies, real IdPs and the cookie behind real TLS proxies, real provider latency,
multi-node clusters over a real network, the ECS terraform applied on AWS.
