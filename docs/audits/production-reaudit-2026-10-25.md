# Raiju production re-audit (after waves 23 and 24)

Date: 2026-10-25. Repo: /home/user/raiju at f254621. This was read-only: nothing in the repo was changed. The binary
was built to /tmp/claude-0/reaudit/raiju with TOV_CFLAGS=-DTV_PLAIN_ALLOC. Gateways ran on ports 18150-18164, always
under `flock /tmp/raiju-e2e.lock`, and every process I started was stopped. Scripts and outputs are in
/tmp/claude-0/reaudit/ (cl/, body/, lu/, aj/, fuzz/, soak/, s2/).

## Verdict

**Not ready for multi-tenant production yet.** Most of the earlier P0s are really fixed, and I measured them: the
locked /api, flat streaming memory, bounded metrics, the graceful drain, and server timeouts on both servers. Three
new P0s remain:

1. **Cluster authentication can be bypassed.** `cluster.secret` is never resolved from `env.NAME`, and that is the
   form the docs and the chart tell operators to use. An empty secret is also accepted. Anyone who can reach the
   gateway port can then fetch the full config, with plaintext keys, from /api/cluster/config, and can also read
   logs and write counters through the other cluster routes.
2. **Unauthenticated memory DoS.** Request bodies up to 100 MB are buffered, and parsed, before any authentication.
   Six requests pushed one worker to 707 MB.
3. **Concurrent config saves lose writes with -workers > 1.** Forty creates were each answered 201, and 11 were kept.
   A revoked key can come back.

Several pieces of per-process state also break once there is more than one worker or replica: async jobs, dashboard
SSO sessions and agent tokens.

## Earlier findings: status

| Earlier item | Status | Evidence |
|---|---|---|
| P0-1 open /api, 0.0.0.0 bind, ECS on HTTP | **Fixed** | ops.tov:6075-6087 locks /api (403) with no admin and no setup token. main.tov:37 defaults host to 127.0.0.1. ECS needs ingress_cidr_blocks and certificate_arn, or allow_plain_http. Startup warnings seen in cl/gw.log. |
| P0-2 streaming leak | **Fixed** | 240 s soak at 647 rps, mixed streams, log store on: RSS 51.6 -> 51.8 MB (+1.0 MB over the second half). 100 open streams cost 159 KB each (soak/soak240.out, soak/soak.out). |
| P0-3 config reaching all workers | **Fixed for propagation.** Concurrent writes are broken (new P0-3). | 4 workers: six GETs all agreed (lu/lu.out). ops.tov settleConfig/workersBehind. |
| P0-4 metrics cardinality | **Fixed** | bench/metrics_cardinality.py with 5,000 junk requests: /metrics 0.05 MB, RSS +4.2 MB. server.tov:556-560, metrics.tov:348. |
| P0-5 SIGTERM drain | **Fixed** | "SIGTERM: draining ... stopped" in every run, per worker in 4-worker mode. |
| P1-1 netguard bypasses | **Fixed** (fetch paths) | `tov test src/netguard.tov`: 7/7, covering inet_aton forms, mapped IPv6 and trailing dots. The connect-time peer option is on provider fetches. Raw sockets remain unchecked (documented in SECURITY.md). |
| P1-2 async job IDs and ownership | **Fixed** | jobs.tov:124-139 uses secureHex(32) and an owner check. Jobs are per worker, though (new P1-1). |
| P1-3 masked-key round trip | Fixed according to store.tov and its tests; not re-run. | |
| P1-4 slowloris and connection cap | **Fixed** | bench/slowloris.py, 150 connections: 0 left open after 15 s, on both bun and http1. |
| P1-5 fetch timeouts | Fixed | No signal-less fetch at the five earlier sites. The fetch lint runs in `make unit`. |
| P1-6, P1-7 storage failure and /ready | **Fixed** | ops.tov storageProblems, lifecycle.tov:93-101. |
| P1-8 deploy persistence | Fixed for helm and compose. **Not for ECS** (new P1-5). | |
| P1-9 file modes | Fixed | atomicfile.tov:9-11. |
| P1-10 plugin integrity | Fixed | per SECURITY.md and plugindl.tov. |
| P1-11 log store | Fixed | segments, batched flush, max_disk_mb (logstore.tov:216-221, :656). |
| P1-12 cross-node config | Implemented (config_sync), but the cluster auth beneath it is broken (new P0-1). | |
| P1-13 WebRTC | Fixed | off by default. |
| P1-14 tail stalls | Not re-measured. | |
| P1-15, P1-16 config doc and image | Fixed | docs/config-reference.md, `raiju -healthcheck`, pinned digests. |
| P2-7 XFF trusted in the audit log | **Not fixed** | ops.tov:6181. |
| P2-11 TV_PLAIN_ALLOC self-check | **Not fixed** | A mock built without the flag segfaulted at 100 concurrent streams here. No check in src/. |
| P2-2 state file versions | **Not fixed** | |

## New findings

### P0

**P0-1. `cluster.secret` is not resolved from `env.NAME`, and an empty secret is accepted. Anyone who reaches the
port can authenticate to the cluster routes.**

- Evidence:
  - config.tov:1337-1460 (resolveConfig) resolves env references for providers, auth, exporters and so on, but never
    cluster.secret. cluster.tov:237-249 signs with the raw string.
  - ops.tov:1393-1420 (configureCluster) enables clustering with no check that the secret is non-empty. Only broker
    mode checks (main.tov:151).
  - The docs prescribe the broken form: deploy/README.md:254 `secret: env.RAIJU_CLUSTER_SECRET`,
    deploy/helm/raiju/values.yaml:174 'secret as "env.NAME"', and tests/test_deploy.py:224.
  - The routes are on the main listener (server.tov:1387-1391): /api/cluster/sync, /feed, /leader, /config and
    /logs.
- Repro (cl/run.sh): with RAIJU_CLUSTER_SECRET=real-strong-secret-xyz set:
  - an HMAC keyed with the literal string `env.RAIJU_CLUSTER_SECRET` gets 200 on /api/cluster/leader;
  - an HMAC keyed with the real secret gets 401;
  - POST /api/cluster/config signed with the literal returned the whole config, provider key sk-test-123456789
    included.
  - aj/run.sh: with `"secret": ""`, an HMAC with an empty key gets 200.
- Scenario: an operator follows the chart docs. Any tenant, or anyone who reaches the Service, can:
  - pull the config with every plaintext secret (/api/cluster/config, ops.tov:1939);
  - read every node's request logs (/api/cluster/logs, ops.tov:2209);
  - inject counter state through /api/cluster/sync (ops.tov:1743), which exhausts budgets and rate limits for every
    key;
  - push fake live-feed events.
- Fix:
  - Resolve cluster.secret (and discovery.advertise_address) with resolveEnv.
  - Refuse to enable clustering when the resolved secret is empty, still starts with "env.", or is shorter than
    32 bytes.
  - Serve /api/cluster/* on a separate listener or port.

**P0-2. Request bodies up to 100 MB are buffered and parsed before any authentication: an unauthenticated memory DoS.**

- Evidence:
  - main.tov:350 and server.tov:1007-1011: the default limit is 100 MB, and with large-payload off,
    bodyStreamThreshold equals the limit, so every body under 100 MB is buffered by the server
    (server.tov:1857-1859).
  - Inference handlers parse JSON before the virtual-key check: the response was 400, not 401.
- Repro (body/run.sh): enforce_auth_on_inference true, six concurrent 90 MB POSTs to /v1/chat/completions with no
  key. Peak RSS was **707 MB** (idle 21 MB). All six answered 400.
- Scenario:
  - The chart's limit is 512Mi, and max_connections defaults to 3/4 of nofile. Six curl commands from anyone
    OOM-kill the pod, and a loop keeps it in CrashLoopBackOff.
  - /api reads the body after the gate (server.tov:769-774), so the management API is not affected.
- Fix:
  - Check the virtual key or credential from the headers before reading the body.
  - Lower the default max_request_body_size_mb (10-20 MB), or stream bodies above about 1 MB.
  - Add a per-process cap on buffered body bytes in flight, answered with 503.

**P0-3. Concurrent config saves on different workers lose acknowledged writes.**

- Evidence:
  - store.tov:1508-1516 (commit) and store.tov:1365-1390 (save) write this worker's in-memory config over the file,
    with no compare-and-swap against the file's current sha and no cross-process lock.
  - A sibling's save reaches this worker only at the next 100 ms share tick (ops.tov takeConfigGen). The later
    writer overwrites the earlier one, and the earlier worker then adopts the overwrite.
- Repro (lu/run.sh): 4 workers, 40 concurrent POST /api/governance/virtual-keys. All 40 answered **201**. The file
  and every GET then held **11** keys. 29 acknowledged keys were silently lost.
- Scenario:
  - An admin revokes a leaked key while a SCIM push (IdPs send in parallel), a credential renewal or a second admin
    saves on another worker. The revocation is undone and the leaked key works again.
  - The same race exists across nodes that share one file with config_sync "file".
  - It only applies with workers > 1 or a shared file. The chart default is 1 worker, but the docs recommend about
    one worker per core.
- Fix:
  - Take a lock file (flock on <config>.lock, or the existing FileLease) around read-modify-write.
  - Inside it, reread the file. If its sha differs from fileSha, adopt it and reapply the mutation, or answer 409.

### P1

**P1-1. Async jobs, dashboard SSO sessions and agent tokens live in one process, so they fail on most requests with
-workers > 1 or several replicas.**

- Evidence:
  - jobs.tov:101-103: JobStore is an in-memory Map.
  - oidc.tov:404-418: UiSessions.
  - agentsignin.tov:72-89: codes, access tokens and 30-day refresh tokens.
  - HANDOFF "What's next" admits the last two. Async jobs are undocumented.
- Repro (aj/run.sh, 4 workers): one x-bf-async job polled 12 times: 10 x 404, 2 found.
- Scenario:
  - SDK clients that poll async jobs get "not found".
  - SSO dashboard users and CLI agent users are logged out at random.
  - Every restart or rollout drops every session and agent refresh token.
- Fix: keep them in the share folder (workers) and the replicated cluster state (nodes), sealed, or make tokens
  stateless (HMAC over sub, expiry and family) with a revocation list on the cluster state.

**P1-2. No brute-force protection on password sign-in, and passwords use one salted SHA-256.**

- Evidence:
  - rbac.tov:32-34: hashPassword is sha256(salt:password).
  - rbac.tov:80-93 checks Basic credentials on every /api request. /api/session/login and /api/agent/auth/authorize
    (ops.tov agentRoute) are public.
  - A grep for lockout, attempts or rate limiting found nothing.
  - Unknown users return early (rbac.tov:88), which allows username enumeration by timing.
- Scenario: online guessing at line rate against admin accounts. A config leak (see P0-1) lets an attacker crack
  hashes offline at GPU speed.
- Fix: per-IP and per-user failure throttling with backoff, and PBKDF2, scrypt or argon2 for stored passwords
  (rehash on next sign-in).

**P1-3. /metrics is unauthenticated on the inference port and exposes tenant data.**

- Evidence: server.tov:1337. Labels include virtual_key_name, team_name, customer_name, business_unit_name and
  project_name (metrics.tov:425-427).
- Scenario: any tenant who reaches the port reads every other tenant's names, request volume, error rates and
  routing.
- Fix: a separate metrics port, or a bearer token or allowlist on /metrics. The chart should scrape the private port.

**P1-4. A worker killed by SIGKILL (the OOM killer) stops the whole node.**

- Evidence: build/tov/runtime/tov.c:5609-5613 treats a worker that died of SIGKILL as a stop: it sets
  tv_http_stop_sig and the supervisor stops every worker.
- Scenario: with 4 workers, the kernel OOM-kills the largest worker (for example via P0-2). The other three, and all
  their in-flight streams, are stopped and the container restarts. A crash by trap is respawned correctly.
- Fix: count SIGKILL of a worker as a crash and respawn it, unless the supervisor itself received a stop signal.

**P1-5. The ECS module cannot run a manageable or consistent deployment.**

- Evidence:
  - deploy/terraform/modules/aws-ecs/main.tf:298-300 mounts EFS at /app/data readOnly = true, with
    readonlyRootFilesystem true and no /tmp volume.
  - variables.tf:94-97 sets desired_count to 2 with no cluster configuration.
- Scenario:
  - With EFS mounted read-only, the first admin cannot be created (the save fails), so /api stays locked unless the
    admin was pre-seeded.
  - Each of the two tasks enforces budgets and rate limits alone, so every limit is effectively doubled.
  - The MCP OAuth signing key cannot persist.
- Fix: mount EFS read-write (or add ephemeral volumes for /app/data and /tmp), and either default desired_count to 1
  or wire cluster with config_sync "file" and a secret from Secrets Manager (after P0-1 is fixed).

### P2 (8)

1. **The audit IP is spoofable.** ops.tov:6181 trusts x-forwarded-for. Add server.trusted_proxies.
2. **No TV_PLAIN_ALLOC startup self-check.** A build without the flag segfaults under concurrency (seen live with the
   soak mock). Export the define as a constant and refuse to start without it.
3. **State files carry no version** (mcp-oauth-state.json, .adaptive.json, A2A push files). Add "version" and a
   migration hook.
4. **logs_store.max_disk_mb defaults to 0 (no cap)** (logstore.tov:216), while the chart's volume is 1Gi. Default it
   to a share of the volume.
5. **Upgrading flips defaults.** Loopback bind, locked /api, MCP deny-by-default and enforce_vk_object_ownership all
   change at once for bare-metal users with no flags. They are documented, but there is no startup notice.
6. **cluster.discovery.advertise_address "env.POD_IP" is used literally** (discovery.tov:313, :420), although
   deploy/README.md:259 documents it. Fix it together with P0-1.
7. **The helm default config has no virtual keys, so inference is open.** It is enforced automatically once a key
   exists (config-reference.md:93), and there is a startup warning. Say so in the chart NOTES.
8. **Soak errors.** The 240 s soak had 10 of 155,998 requests end in IncompleteReadError (the 60 s run had 0).
   Worth a look, but not reproduced as a pattern.

### Checked and fine

- No crash or uncaught error under fuzzing: 21 inference and MCP routes x 21 malformed bodies, including 100k-deep
  JSON nesting, wrong types and lone surrogates. 0 crashes (fuzz/fuzz.out).
- SCIM: bearer token with constant-time compare (scim.tov:52-56), off unless enabled.
- /ws needs a ticket or the gate (server.tov:1727-1745). CORS is off unless allowed_origins is set.
- Agent sign-in requires PKCE S256 and loopback redirects (agentsignin.tov:53-59).
- SSRF: no gateway-side fetch of caller-supplied media URLs. Fetches without `peer` go only to admin-set cloud token,
  guardrail and trace endpoints (gateway.tov:2040, 3546, 3569, 3596, 5529).
- Secrets in logs: no key, token or password values in console.error sites. Log rows hold the VK id, not its value.
- Config durability: atomic writes with fsync and directory sync (atomicfile.tov). A failed save rolls back memory
  (store.tov:1508-1516) and does not flip /ready.
- Helm: liveness and readiness split, a preStop and grace guard, a PVC, a /tmp emptyDir, a read-only root FS and
  non-root. The Dockerfile sets WORKDIR, VOLUME and HEALTHCHECK.
