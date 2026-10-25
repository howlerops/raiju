# Running several workers and nodes

This page covers what happens to configuration changes and state when Raiju runs as several
processes: workers of one node (`-workers N`) and nodes of a cluster (`cluster` in the config).

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
  or is killed, so a dead process never leaves it behind) and reads the file again. A management request
  that changes something waits for the lock (up to 15 seconds, then a save fails with 500) without pausing
  its worker, which keeps serving other requests; saves made outside a request wait at most half a second; when another worker saved since, its own change is reapplied to the file as it is now
  (a three-way merge: objects key by key, lists by id or name). Two changes that cannot both hold (the
  same value set differently, an element changed on one worker and deleted on another, two new elements
  with one name) answer 409, and the worker takes the file's config, so a retry starts from it. Nodes
  that share the file on a volume take the same lock.

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
- Leadership (the lowest live node id, or the etcd lock in `cluster.leader_lock`).

Shared between the workers of one node only:

- The response cache and the in-process semantic cache.
- Async jobs (one file per job in the share folder): a poll may reach any worker of the node that took
  the job, not another node.
- Dashboard sessions and the CLI's agent sign-in codes and tokens, in `<config>.sessions.json` and
  `<config>.agent-sessions.json` beside the config file (0600, tokens by hash, refresh tokens sealed with
  the encryption key). They outlive a restart; nodes share them only when they share the config folder, so
  put several nodes behind sticky sessions or a shared volume for dashboard and CLI sign-ins. A write that
  cannot get its file's lock within half a second fails its request (503) and writes nothing.
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
- Set `encryption_key` (or `BIFROST_ENCRYPTION_KEY`) to the same value on every node.
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
