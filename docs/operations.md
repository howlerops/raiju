# Running several workers and nodes

This page covers what happens to configuration changes and state when Raiju runs as several
processes: workers of one node (`-workers N`) and nodes of a cluster (`cluster` in the config).

## Native worker startup

The native Bun server starts multi-worker gateways in fresh processes, not by
continuing inside a forked JavaScriptCore VM. DNS, secret resolution and MCP
initialization can start engine threads before listeners open; an ordinary fork
loses those threads and can deadlock later garbage collection.

Workers adopt the supervisor's main and optional cluster listeners. They retain
its node identity, private share directory and ephemeral sign-in state key, while
initializing their own engine and MCP connections. Those bootstrap values travel
through a private, immediately unlinked file descriptor, not environment values
or command-line arguments. Imported descriptors are close-on-exec so MCP child
processes do not inherit gateway listeners or bootstrap state.

Worker replacement retains the same listeners and identities. SIGTERM/SIGINT
still use the normal graceful drain; crash-loop replacement retains its backoff.
The `http1` server remains single-process.

## Native administration sign-in

Raiju serves its own first-admin setup and sign-in screens; an external identity
proxy is optional, not a prerequisite. Native sign-in is the default. Until the
selected gateway confirms its configured access mode and permissions, the console
does not mount navigation, dashboard components, configuration forms or live
sockets (including Fleet). An unavailable or malformed response fails closed.
Disabling credentials alone does not enable anonymous administration.

Without configured native OIDC, initial setup requires the operator's setup token
and creates an administrator, not a viewer/editor. The generated bearer is shown
once and verified before the console opens; creating this account does not create
a password. Keep the bearer securely for future token sign-ins, or configure an
appropriate password user. Enabled native OIDC can instead provide the initial
identity and role without a separate local account.

### Set an initial password login

There is no universal default username/password. An operator can preconfigure
the first administrator before starting Raiju:

```json
{
  "governance": {
    "auth_config": {
      "is_enabled": true,
      "username": "env.RAIJU_ADMIN_USERNAME",
      "password": "env.RAIJU_ADMIN_PASSWORD"
    }
  }
}
```

Provide those environment variables through your secret manager or container
environment; do not commit their values. This skips first-admin setup and allows
native password sign-in. The local preview separately generates synthetic
`preview` credentials at startup and writes them to
`build/console-preview-access.json`; they are not product defaults.

### Native single sign-on

Configure `oidc.enabled`, the issuer and client credentials, and the exact
`/api/oidc/callback` URI on each regional UI origin. Register those callbacks
with the identity provider before enabling the deployment. A configured OIDC-only
gateway shows sign-in, not first-admin setup; anonymous management calls remain
locked until the provider has verified the identity.

For providers carrying verified email claims, set `oidc.allowed_email_domains`
to the explicit company domains. This requires `email_verified:true`, a valid
email and an exact, case-insensitive domain match. Missing/unverified email,
suffix tricks and accounts outside the allowlist are refused. Omitting the
allowlist preserves existing provider policies; it is not a company restriction.

For Google Workspace membership, also set `oidc.allowed_hosted_domains` to the
explicit organization domains. A verified email alone does not prove managed
Workspace membership. This independent policy requires a nonempty string `hd`
claim in the signed ID token, matched case-insensitively to an exact allowed
domain before role assignment or session issuance (including refreshed ID
tokens). Subdomains, suffix matches, malformed domains and missing claims are
refused. Both allowlists must be nonempty lists of valid DNS domains when set;
neither has a default, and omitting either leaves that policy disabled.
Set both lists when both managed membership and verified company email are
required; a match in one list never bypasses the other. The authorization
request's `hd` hint, email suffix and access-token claims are not membership proof.

Use `role_claim:"email"` and exact `role_map` entries when the provider does not
send groups. Role-map keys may use `env.NAME` references for operator-managed
addresses; unresolved references fail closed. Select a deliberate `default_role`
(for example, viewer), never make every company user an administrator by default.
Native provisioned users retain their current local roles/scopes.

Successful native SSO writes a regional bearer into the callback origin's
tab-scoped storage. It does not add a second cookie-based authentication scheme.
When the selected gateway is the current UI origin, SSO continues in the same tab.
For a remote target the link opens that gateway's own console; no regional session
or credential is forwarded across origins. Native logout revokes the bearer
session and removes the tab credential, without logging the user out of the
shared identity provider.

### Explicit loginless administration

For self-managed access behind your own login gate, opt in before starting:

```json
{
  "governance": {
    "auth_config": {
      "is_enabled": false,
      "allow_unauthenticated_access": true
    }
  }
}
```

Both settings are required. This opens the management API and console as an
administrator to anyone who can reach the gateway; it is not merely a UI
preference. Restrict the listener/network and require your external gate on
**every** management path, including WebSocket upgrades. Do not expose a direct
origin that bypasses it. Raiju does not learn individual user identity or roles
from an external gate in this mode; actions share the loginless principal.
Use the existing signed `auth_proxy` integration instead when native per-user
identity, RBAC and attribution are required. A consolidated cross-origin console
must also be able to reach your externally protected regional APIs; it does not
forward browser cookies or invent an upstream SSO session.

The server declares loginless mode explicitly and supplies its permission set.
The console still verifies that response before opening and clears only the
selected origin's stored native credential. Inference authorization and the
separate metrics scrape policy are unchanged: explicitly configure
`client.enforce_auth_on_inference` and `server.metrics_token` as appropriate.

### Session and API enforcement

Native password sessions use the user's current role and data scope. Unknown
identities have no implicit administrator role. A protected management API 401
removes the authenticated UI; a permission-level 403 remains a denied operation.
Signing out revokes a native session and clears the tab's selected-origin
credential. Long-lived user/API tokens are not globally revoked by signing out
of a tab. Shared-file session caches may take up to one second to observe a
revocation on another worker.

These UI gates supplement, never replace, native API authorization. Public
health/auth/bootstrap and protocol-specific authorization routes remain
deliberate exceptions. Operators can still explicitly opt out through
`client.whitelisted_routes` or disable inference enforcement; do neither for
private administration/tenant traffic. Set `metrics_token` to protect scrapes:
the separately protected `/metrics` endpoint uses its own credential policy,
and a scrape-token refusal does not invalidate a native admin identity.


## Configuration changes

Raiju keeps its configuration in one JSON file (`-config`, or `config.json` in `-app-dir`). The
management API, the web UI and some background jobs (credential renewals, agent card fetches) save
changes to that file.

Each save puts a configuration generation on the replicated cluster state: the sha256 of the text
written, and the node that wrote it (`store.tov`, `CONFIG_NS`). Every other process takes that
generation as its configuration.

### Workers of one node

The workers of a node share the config file. A worker that sees a new generation rereads the file and
rebuilds its engine, exactly as the saving worker does.

- The generation travels through the node's share folder (`/tmp/raiju-<supervisor pid>`). The saving
  worker writes its share file at once, and the other workers read it at their next share tick (every
  100 ms).
- A management API request that changed the config is answered only once every other live worker
  runs the new generation. Each worker notes the generation it has applied in `gen/<pid>` in the share
  folder. The wait is capped at 2 seconds; past that, the request is answered anyway and a line is
  logged. So when `DELETE /api/governance/virtual-keys/{id}` answers, no worker of that node accepts
  the key any more.
- A worker whose share file has not moved for a second is taken for gone and is not waited for.
- Saves from several workers at once do not overwrite each other. A save takes the config file's lock
  (flock(2) on `config.json.flock`, a file that stays; the kernel gives the lock back when its holder exits
  or is killed, so a dead process never leaves it behind) and reads the file again. The lock is held only
  around that read, the merge and the write, never across network I/O: a request that reaches the network
  (refresh-models, a pricing or MCP library sync, an MCP server's spec, tools or authorization server, an
  agent card, a plugin download, a token exchange) does that first and takes the lock afterwards. A change
  waits for the lock (up to 15 seconds) without pausing its worker, which keeps serving other requests;
  when another process keeps it longer, the change answers 503 with `Retry-After: 1` and nothing of it runs
  (or is saved later). Background saves (renewed credentials and tokens, agent cards, directory sync, a
  change another node made) wait the same way; no save ever sleeps for the lock. A save that finds the lock
  taken without having waited for it (a credential renewed in the middle of a tool call, say) fails at
  once (503 for a request; a background save logs it and runs again when next due). When another worker saved since, its own change is reapplied to the file as it is now
  (a three-way merge: objects key by key, lists by id or name). Two changes that cannot both hold (the
  same value set differently, an element changed on one worker and deleted on another, two new elements
  with one name) answer 409, and the worker takes the file's config, so a retry starts from it. Nodes
  that share the file on a volume take the same lock (see "File locks on a shared volume" below). A
  change computed before network I/O is reapplied the same way to what other requests of the worker saved
  meanwhile.
- Concurrent changes on one worker are saved together (group commit). The management API changes that
  arrive on a worker while one of them waits for the lock queue behind it; the one that gets the lock
  rereads the file once, runs them all in arrival order on the config as each left it, and writes the file
  once: one generation, one `.bak`, one engine rebuild, one dashboard notice ("N changes (...) were
  saved"). Each request still gets its own answer: a change refused on its own (a bad body, a name another
  change of the group took first, a 409 from a rebase) changes nothing and the others are saved. If that one
  write fails, every change of the group that would have saved answers the failure (500, nothing kept).
  Routes that take the lock themselves (SCIM, the MCP OAuth and token-exchange routes, plugins, background
  saves) still save one at a time under the same lock.

### Write concurrency (provisioning scripts)

Every write rewrites the whole config file (about 120 bytes per virtual key: 5,000 keys is a 600 KB
file), so a write costs more as the config grows; group commit makes concurrent writes share that cost.
Measured on one node with 4 workers and a 5,000-key config (`bulk/run.sh` in the re-audit 4 scripts):

| Concurrent creates | Before group commit | With group commit |
|---|---|---|
| 1 | 0.17 s | 0.17 s |
| 200 | 178-200 x 201, up to 37 x 503, slowest 17-19 s | 200 x 201, slowest 1.7 s |
| 500 | | 500 x 201, slowest 3.1 s |
| 1,000 | | 1,000 x 201, slowest 6.4 s |

(One worker: 200 creates took 6.9 s before and 0.75 s after.) None were lost in either case. Guidance for
scripts that create or change many records:

- Send writes from a bounded pool: 8 to 32 requests in flight per node is enough to reach full
  throughput; more only queues on the workers. Spread them over the node's workers (any HTTP client with
  several connections does).
- Retry 503 (the lock was kept past 15 seconds, or the node is draining): wait the `Retry-After` seconds
  plus some jitter, and retry a few times. A 503 changed nothing.
- Treat 409 as an answer, not a transient error: "already exists" means the name or value is taken (look
  the record up instead of creating it), "changed by another process/request" means re-read and decide
  again.
- A change is answered once the node's other workers run it (up to 2 seconds more); there is no need
  to wait between writes.
- Several nodes writing one shared file serialize on its lock across the network: run provisioning
  against one node when you can (see "One writer" below).
- One write's cost grows with the file (about 40 ms for the 5,000-key config on one worker above). With
  tens of thousands of records, prefer fewer, larger changes over many small ones: a key created with its
  budgets and rate limit inline is one write, not three.

### File locks on a shared volume

The locks (the config file, the session files, the MCP OAuth state, webhooks, the MCP library and the
catalog) are flock(2) on `<file>.flock`. What that means where the file lives:

- Local disk, one node: the kernel holds the lock and gives it back the moment its holder exits or is
  killed (SIGKILL and the OOM killer included). Nothing is ever taken over or deleted.
- NFS (v4, and v3 with the NLM lock manager running; Linux 2.6.12 and later): the client turns flock into a
  whole-file POSIX lock held by the server, so it serializes the nodes that mount the export. A node that
  crashes or is cut off keeps its locks until the server's lease (NFSv4, 90 s by default) or the NLM grace
  period expires: the other nodes' changes wait for it and answer 503 after 15 seconds until then. Mounts
  with `nolock` or `local_lock=flock`/`all` keep the lock on the client only: nodes do not see each other's
  lock, so do not share the config file across nodes on such a mount.
- Amazon EFS: NFSv4.1 with server-held advisory locks. A process killed while its NFS client remains connected
  can release promptly; a disconnected client can retain its lock until the server lease expires, with other
  gateway writes answering 503 after 15 seconds meanwhile. In an isolated leviosa-dev Fargate/EFS proof,
  separate-task waiters stayed blocked behind live holders; SIGKILL released a synthetic lock in 0.054 s.
  A dedicated-subnet NACL then cut only the holder's NFS traffic while its process stayed alive: the waiter
  acquired 67.389 s after the cut began. These are measured cases, not an EFS timing guarantee. The module's
  default mount keeps locks on the server. Evidence: `build/proof/2026-11-10/efs-faults/`.
- A file system without flock (some FUSE mounts): the lock guards nothing, and Raiju logs once that writes
  to that file are not guarded against other processes. Run one writer there.

Upgrade bridge (wave 27 only): the wave 25 release locked with a directory, `<file>.lock`, made with mkdir
and taken over once 10 seconds old; wave 26 moved to flock, and the two did not see each other's lock, so a
rolling update from wave 25 to 26 on one volume could lose saves. From wave 27 a lock holder also makes that
directory (with a marker file inside) and removes it before it gives the flock back, and waits, without
pausing its worker, while a wave 25 process holds it. A directory left by a killed wave 27 holder (it has the
marker) is taken over by the next flock holder at once; an empty one (a wave 25 process's) once it is 10
seconds old, as wave 25 itself does. So a wave 27 process excludes both wave 25 and wave 26 processes (wave
25 and wave 26 still do not exclude each other: never run those two on one volume).
The bridge can be dropped in the release after wave 27: once every node runs wave 26 or later, nothing takes
the mkdir lock. An upgrade from wave 25 straight to a release without the bridge must stop the old
processes first (deploy/README.md, "Upgrading on a shared volume").

### Nodes of a cluster

Other nodes get the generation at their next cluster sync (`cluster.interval_ms`, default 1 s), from
their peers or through the broker. What a node does with it is set by `cluster.config_sync`:

| `config_sync` | Behaviour |
|---|---|
| `file` (default) | If the node's own config file holds the saved text (the nodes share one file, for example on EFS or NFS), it rereads the file. Otherwise the change is not applied, and the node logs once that its file differs. |
| `pull` | As `file`, and when its own file differs it fetches the text from a peer (`POST /api/cluster/config`), writes it to its own file with its own `cluster` section put back (its `node_id`, `peers` and secret), and applies it. The node then also serves that generation to peers that ask. If the file cannot be written (a read-only ConfigMap), the configuration is still applied in memory. |
| `off` | Other nodes' saves are ignored. Each node keeps its own configuration. |

A node with a different configuration on purpose (other providers, other limits) should use `file`
or `off`. With `pull`, every save made on any node replaces the whole configuration on every other
node, except the `cluster` section.

`pull` needs peers. A cluster of type `broker` has none, so its nodes must share the file.

The pull request is signed with `cluster.secret` over a body that names the generation and the
current time. A request older than a minute is refused, so a captured request cannot be replayed
later. A node answers only for the generation it holds.

### One writer

Saves from different nodes are not merged: the last save wins, as a whole file. Two
administrators editing on two nodes at the same moment can overwrite each other's change. Send
management API traffic to one node (one Service endpoint, or a separate admin ingress) and let the
other nodes take its saves.

Nodes that share one file over a network file system each write it when they save. The writes are
atomic (written to a temporary file, then renamed), but the one-writer advice above applies all the
more.

## What a cluster shares, and what each node keeps

Shared between the workers of a node and between nodes:

- Budget and rate-limit usage (a CRDT per worker and per node; a burst spread over several
  processes can pass a limit by a few requests within one sync interval).
- Key holds under adaptive load balancing.
- The replicated state (`clusterstate.tov`): configuration generations, MCP token-exchange admin
  credentials (sealed), A2A push configurations and agent cards, and realtime client-secret mappings
  (provider tokens sealed).
- The live log feed (`/ws`), unless `cluster.feed.cluster_wide` is false.
- Failed sign-in counts (`signinguard.tov`): each process puts its own counts on the replicated state, keyed
  by a hash of the account or address, at most 4,096 entries, each kept an hour after its last failure; a
  check adds the other nodes' counts to its node's own, and a success clears the account on every node.
- Async and provisioning jobs: kept beside the config (`<config>.jobs/`, `<config>.provision-jobs.json`),
  so nodes that share the folder see each other's; a node with its own folder asks its peers for a job it
  does not hold (signed `POST /api/cluster/jobs`; not in broker mode). Both survive a restart; a job whose
  gateway stopped while it ran reads as failed once its beat is 45 s old.
- Leadership (the lowest live node id, or the etcd lock in `cluster.leader_lock`).

Shared between the workers of one node only:

- The response cache and the in-process semantic cache.
- Dashboard sessions and the CLI's agent sign-in codes and tokens, in `<config>.sessions.json` and
  `<config>.agent-sessions.json` beside the config file (0600, tokens by hash, refresh tokens sealed with
  the encryption key). They outlive a restart; nodes share them only when they share the config folder, so
  put several nodes behind sticky sessions or a shared volume for dashboard and CLI sign-ins. A write that
  cannot get its file's lock within half a second fails its request (503) and writes nothing.
- UI WebSocket tickets live for 30 seconds in `<config>.ws-tickets/` (0700, files
  0600 named by the ticket hash). A ticket issued on one worker can be redeemed on
  any worker or replica sharing that directory. A successful atomic unlink claims
  it once; an unreadable/unwritable store never falls back to a local grant.
  Independent data volumes need session affinity for ticket issuance and socket
  upgrade, just as for dashboard sessions. Do not share this state across
  independently administered regions.
- Single sign-on logins in flight are kept nowhere: `/api/oidc/login` seals the PKCE verifier, the nonce,
  the return path and a 10-minute expiry into the `state` value (AES-256-GCM), and the callback opens it on
  whichever worker takes it. The key is derived from the encryption key, so with `encryption_key` set every
  node opens every other node's states, across restarts too; without one each node makes a key at start,
  and a sign-in begun before a restart or on another node must be started again. A state is accepted once
  per worker.
- `/metrics` (each worker's series are summed when scraped).
- The request log files, when `logs_store` is on (one folder per node).

Kept per node:

- The request log files and the audit log. `/api/audit-logs` answers from the node that is asked. `/api/logs` (the
  list, one log, stats, sessions, histograms, rankings, dashboard, filterdata) and `/api/mcp-logs` answer with every
  node's rows: the node asked fetches its peers' rows for the read over the signed `POST /api/cluster/logs` (a few
  seconds at most per peer; a peer that does not answer is left out). `cluster.log_reads: false` answers with the
  node's own rows. Broker mode has no peer addresses, so each node reads its own rows there. Deletes and the cost
  recalculation act on the node asked.
- The MCP client connections and their tool lists. Each node connects to each MCP server itself.
- The config file itself, unless the nodes share it.

## Securing cluster traffic

Cluster traffic (`/api/cluster/sync`, `/api/cluster/feed`, `/api/cluster/config`, `/api/cluster/logs`, the broker) is
signed with HMAC-SHA256 using `cluster.secret`. Anyone who holds the secret can read every node's config (with the
values stored in the file), its request logs, and write budget and rate-limit counters, so the gateway checks it at
start: with `cluster.enabled` (or `-mode broker`) it refuses to start when the secret is empty, is an `env.NAME`
reference to a variable that is not set, or is shorter than 32 bytes (`openssl rand -hex 32` makes a good one). A
config saved while running with such a secret turns clustering off and logs why. `env.NAME` is resolved in
`cluster.secret`, `cluster.bind`, `cluster.broker.address`, `cluster.discovery.advertise_address` and
`cluster.discovery.consul_address`.

A peer POST is signed twice: over its body (`x-raiju-cluster-sig`) and over its head (`x-raiju-cluster-head`: the
method, the route, the time in `x-raiju-cluster-ts` and the Content-Length). A node checks the head, and that its
time is within a minute, before it reads the body, so a request no node sent is refused unread; the body's HMAC is
checked once it is read. Peer bodies have a body budget of their own (`cluster.max_body_mb`). Nodes from before
L204 sign only the body and their peers refuse them, so upgrade a cluster's nodes together.

The peer routes can have a listener of their own: `cluster.listen_port` (and `cluster.bind`, default the `-host`
address) opens a second port that serves only `/api/cluster/*`, `/health` and, with `cluster.serve_metrics: true`,
`/metrics`. The main listener then answers 404 for `/api/cluster/*` (and for `/metrics` with `serve_metrics`), so a
public load balancer in front of the main port never reaches them. Peers name that port (`peers`, or discovery,
whose `bind_port` defaults to it). Both are read at start. Bifrost's own cluster traffic is on separate gossip ports
too.

The traffic is plain HTTP. Anyone who can read the network
can read the usage data and, with `config_sync: "pull"`, the configuration text. That text keeps
`env.NAME` references as references. Values stored in the file itself are readable unless
`encryption_key` is set: then provider keys, virtual key values and admin credentials are sealed in
the file and on the wire.

- Run cluster traffic on a private network, or through a service mesh that adds mTLS between pods.
- Set `encryption_key` (or `RAIJU_ENCRYPTION_KEY`) to the same value on every node.
- Use a long random `cluster.secret` from a secret store (`"secret": "env.RAIJU_CLUSTER_SECRET"`), and set
  `cluster.listen_port` so `/api/cluster/*` is not on the public port at all.

## /metrics

`GET /metrics` is open by default, as in Bifrost. Its labels include virtual key, team, customer, business unit and
project names, so anyone who reaches the inference port can read every tenant's names, volume and errors. Two
settings close it, alone or together:

- `server.metrics_token` (`env.NAME` allowed): `/metrics` answers 401 unless the request carries
  `Authorization: Bearer <token>`. Prometheus sends it with `authorization: {credentials: ...}` in the scrape config
  (or a ServiceMonitor's `bearerTokenSecret`; the chart's `metricsToken` sets both sides).
- `cluster.serve_metrics: true` with `cluster.listen_port`: `/metrics` is served on the cluster listener only.

## Log and audit storage

The request log store (`logs_store`) and the audit log (`audit`) write to folders. Their paths are
read from the app dir (the folder that holds the config file), not from the working directory:

- `logs_store.dir` defaults to `<app dir>/logs`.
- `audit.dir` defaults to `<app dir>/logs/audit`.
- A relative `dir` is read from the app dir. An absolute one is used as written.

When either one is enabled and its folder cannot be created or written, the gateway does not start.
It logs `raiju: logs_store: ...` or `raiju: audit: ...` and exits with status 1. This matches
Bifrost, whose start fails when its log store does not open. Set `"required": false` in the section
to start without that store instead (the problem is still logged).

`Ops.storageProblems()` (`ops.tov`) returns the required stores that failed. A readiness check can
call it.

Two counters report write failures after the start:

- `raiju_log_store_dropped_total`: request log entries that could not be written to their day file.
- `raiju_audit_write_errors_total`: audit events that could not be appended.
