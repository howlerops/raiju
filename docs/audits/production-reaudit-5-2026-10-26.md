# Raiju production re-audit 5 (198dfc5, after wave 28)

Verdict: not ready for multi-tenant production yet. Wave 28 fixed what it targeted (P1-E, P1-F, P2-G, P2-H, P2-J,
P2-K fixed; P2-I documented), and every earlier P0 and key P1 stays fixed (cluster secret; 6 x 90 MB: 401 at
21.3 MB; 40/40 creates; 24/24 creates while a refresh hangs; wave 25/27 + 28 bridges 40/40; /mcp hog; 100/100 mixed
admin writes). But the per-credential share added in L205 lets the default 512Mi pod be pushed past its limit by
three ordinary callers. Single tenant on the default chart is fine.

## Re-audit 4 findings

| Finding | Status |
|---|---|
| P1-E one key holds the body budget | Fixed for one key (408 at 40.3 s; others 200 throughout); partly overall (P1-B) |
| P1-F registrations evict pending MCP clients | Fixed (1,500 from 150 addresses; earlier authorize still 302) |
| P2-G Math.random seeded with 0 | Fixed (0 duplicate ids in 5 x 12 on 4 workers; respawned worker draws its own) |
| P2-H broker reads unsigned bodies | Fixed (32 x 15 MB: 401, RSS flat 19.4 MB) |
| P2-I MCP OAuth across versions | Documented: stop-first required |
| P2-J every admin write rewrites the config | Fixed (5,000 keys: 200 x 201, slowest 1.27 s) |
| P2-K direct keys not checked | Fixed |

## New findings

- **P1-A: the per-credential share lets bodies in hand reach about twice the cap** (bodybudget.tov:206-216 excess,
  :252-263; admitted while held - past <= cap, hard limit only held <= 2*cap). Three keys sending 46 + 24 + 24 MB
  while the provider takes 2 s: wave 28 admits all, 600 MB peak (wave 27: two refused, 358 MB); 3 x 24 MB: 488 MB
  vs 292 MB. The chart's 512Mi pod is OOM-killed by ordinary concurrent uploads. Fix: keep the cap as the hard bound
  (held - small + n <= cap, apart from the lone-body rule) and use the share only to choose who is refused first.
- **P1-B: several keys of one tenant can still lock other tenants out of big bodies.** The share is per virtual
  key (governance.tov:570) and the 32 KB/s floor is cheap: 4-11 keys reconnecting at 33 KB/s made 43-67% of
  outsiders' 1 MB and 91-106 of ~105 of their 4 MB bodies 503 for 60 s. Fix: count the share per tenant (customer,
  then team, then key), reserve part of the cap for credentials holding nothing, or raise the floor under contention.
- **P2-A: concurrent bodies that together exceed the cap mostly fail together** (refused mid-stream,
  bodybudget.tov:391; only the declared length is checked against what is held at admission, server.tov:1346):
  8 keys x 12 MB served 0-4 of 8 (wave 27: 2-4). Fix: reserve the declared length at admission so excess bodies get
  503 before sending.
- **P2-B: name uniqueness gives 409 on legitimate updates of configs with duplicate names from before wave 28**
  (store.tov:2178, :2315, :2338): a PUT keeping the name "prod" to deactivate a leaked key gets 409. Fix: skip the
  check when the name is unchanged from the stored record, and warn at start about existing duplicates.

## Checked and sound

Sealed client_ids (tamper 400; 9 KB id 400 in 1 ms; metadata cap; TTL and future dates checked; signing-key rotation
as documented); trusted proxies walked from the right; group commit loses nothing and isolates bad changes; broker
head signature.

## Only real infrastructure can confirm

flock on EFS/NFS and the bridge's stale rule under clock skew; ECS/EKS rolling and stop-first upgrades; real memory
against 512Mi with real bodies and provider latency; ALB with RAIJU_TRUSTED_PROXIES; real IdPs and cookies behind
TLS proxies; multi-node clusters and a broker over a real network; the ECS terraform applied on AWS.
