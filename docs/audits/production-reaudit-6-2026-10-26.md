# Raiju production re-audit 6 (9b05724, after wave 29)

Verdict: not ready for multi-tenant production. Wave 29 fixed all four re-audit-5 findings (3 x 24 MB: 1 served,
261 MB peak; 8 x 12 MB: 4/8 complete; duplicate-name PUTs 200), and every earlier P0 and key P1 stays fixed (cluster
secret, 6 x 90 MB, 40/40 creates, lock across I/O, mixed versions, /mcp hog, vk_trickle, DCR spread, broker). Three
blockers remain.

## P0-A: every request body over 64 KB leaks its full size (since wave 26)

`src/bodybudget.tov:395-401` makes a `late` promise that settles only when a timer fires; `:405` races every chunk
against it (`Promise.race([readChunk(st), late])`); `:427-428` clears the timer at the end but never settles `late`.
In Tov a race against a promise that never settles keeps every raced value alive (30-line repro: 208 MB after racing
200 MB of chunks; flat at 12 MB once settled). Affects checked bodies (rate rules on by default), unchecked bodies
with a deadline and peer/broker bodies (`broker.tov:112`). Fresh 1-worker gateway: a 1 MB + 4 MB loop for 100 s grew
20 to 836 MB; 200 KB chats 20 to 557 MB in 30 s; 60 KB chats and rules off stay flat; the wave 25 binary stays flat,
waves 26-28 leak. The chart's 512Mi pod is OOM-killed after ~450 MB of cumulative large bodies. Fix: settle `late`
with a sentinel when the loop ends (or race each read against its own timer), and add a soak test asserting flat RSS
over many big bodies.

## P1-A: the declared-length reservation lets two tenant identities lock other tenants out (regression, L208)

`server.tov:1349` reserves the whole declared length at admission and keeps it until the rate rule or the 600 s
ceiling cuts it (`bodybudget.tov:143-146`, `:179`): 10 s with nothing sent, or up to 600 s at 32 KB/s. Tenants
within their share may fill the cap (`:285`); keys with no customer or team, MCP OAuth users and management actors
are separate tenants. 4 keys declaring 12 MB and sending nothing: 286/286 outsider 1-4 MB bodies 503 for 60 s (wave
28: 0/418); at 33 KB/s 579/579 for 120 s; two tenants at ~66-132 KB/s total: all refused. Fix: charge a declared
length as bytes received plus a bounded look-ahead, or keep the full reservation only while the body is on pace;
under contention cut the reservation furthest behind its pace instead of refusing the newcomer.

## P1-B: 36-48 MB bodies are never served while any other request is in flight (regression)

The lone-body rule (`bodybudget.tov:279-280`, `seen - own <= 0`) counts small bodies (added to `held` by `hold()`,
`:292-296`), unlike the unchecked branch (`:275`), so "always admitted when no other big body" is false beside any
small request; then a body over the 12 MB share or a growing chunked body is limited to cap - reserve (36 MB,
`:288`). With small chats in flight: 40 and 46 MB 0/8 (wave 28: 8/8); 40 MB beside one 100-byte chat 503; one key
30 + 12 MB: the 12 refused. Fix: exclude small bodies from the lone-body test, and apply the reserve only to a
tenant that already holds bytes, so a tenant's first body may use up to the cap.

## Checked and sound

Tenant grouping works as designed (MCP user header set only from a verified token); L209 name rules; the other
Promise.race sites race timers that always fire.

With P0-A, P1-A and P1-B fixed and a soak test showing flat RSS, the auditor knows of no other blocker for
multi-tenant production.

## Only real infrastructure can confirm

flock on EFS/NFS and the bridge's stale rule under clock skew; ECS/EKS rolling and stop-first upgrades; real memory
against 512Mi with real bodies, provider latency and worker respawn under the OOM killer; ALB with
RAIJU_TRUSTED_PROXIES; real IdPs and cookies behind TLS proxies; multi-node clusters and a broker over a real
network; the ECS terraform applied on AWS.
