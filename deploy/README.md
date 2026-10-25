# Deploying Raiju

Raiju is one binary. The image runs it as non-root on a slim Debian base (bookworm-slim with
JavaScriptCore, which the binary links). It takes a Bifrost-format `config.json` from `/app/data`
(its `-app-dir`), and provider keys come from environment variables that the config refers to as
`env.NAME`. Terraform modules (Helm release, AWS ECS Fargate) are in
[terraform/](terraform/README.md). Every config key is listed in
[docs/config-reference.md](../docs/config-reference.md).

Endpoints for probes and scraping: `GET /health` (liveness: 200, `{"status":"ok"}`),
`GET /ready` (readiness: 200 `{"status":"ready",...}`, or 503 while the process drains for a stop
or when a store that is on could not open) and `GET /metrics` (Prometheus text, Bifrost metric
names). `/metrics` is open, as in Bifrost, and its labels name virtual keys, teams and customers: set
`server.metrics_token` (a bearer token, `env.NAME` allowed) to keep tenants on the inference port from
reading it, or move it to the cluster listener with `cluster.serve_metrics` (a start with neither logs a warning). The image has no curl; its `HEALTHCHECK` runs `raiju -healthcheck`, which GETs `/health`
on 127.0.0.1 at `-port`, `PORT` or 8080 and exits 0 on a 2xx (`raiju -healthcheck /ready` probes
readiness instead).

## What Raiju writes

Raiju is not stateless. In the folder that holds `config.json` (`/app/data` in the image) it writes:

- `config.json` and `config.json.bak`, on every change made through the management API or the web
  UI (written to a temporary file, then renamed);
- `mcp-oauth-state.json` (the MCP authorization server's signing key and grants; without it, a
  restart changes the key and every token it issued stops working), `mcp-oauth-state-clients.jsonl`
  (the MCP clients registered and not yet granted: one line per registration, bounded by
  `client.oauth2_server_config.max_unused_clients`, rewritten when it holds twice that) and
  `mcp-flow-state.json` (MCP OAuth flows in flight);
- `config.json.sessions.json` and `config.json.agent-sessions.json` (dashboard sessions and CLI
  sign-in tokens, by hash). Single sign-on logins in flight are stored nowhere: their state is sealed
  with a key derived from `encryption_key`, else from `cluster.secret` with clustering on, else a key
  each node makes at its start (then a callback that reaches another node fails; a start with other
  nodes configured warns). Set `encryption_key` or clustering when several nodes serve SSO;
- `logs/` (the request log store, when `logs_store` is on) and `logs/audit/` (the audit log, when
  `audit` is on), private (0700 folders, 0600 files). An enabled store whose folder cannot be written
  stops the start;
- `plugin-cache/` (plugins downloaded from a URL; `RAIJU_PLUGIN_DIR` moves it).

In `/tmp` (or `TMPDIR`) it keeps `raiju-<pid>-<random>`, the private share folder through which the
workers of one process share budgets, rate limits, the caches and `/metrics` (without it each worker
counts alone).

So `/app/data` must be a writable volume that outlives the container, and `/tmp` must be writable.
The compose file and the chart below do both. A read-only `config.json` still serves traffic, but
every management write answers 500 "could not save config".

## Sizing

A worker starts at about 20 MB and settles at 40 to 60 MB under load; each open stream adds about
170 KB while it lasts (see [Memory and the request log](#memory-and-the-request-log); `make soak`
measures your build). Per container, plan for about `workers x (64 MiB + open streams x 0.17 MiB)`
with headroom. The chart asks for 128 MiB and limits the pod to 512 MiB, which holds about 2,000
open streams on its one worker; raise both with `workers` or more concurrent streams. Give the
process a descriptor limit (`nofile`) of at least four times the concurrent streams you expect.

The data volume (1Gi by default) holds the config and, when `logs_store` is on, the request log:
`logs_store.max_disk_mb` (default 512) keeps the log under half of it; set it from your volume's size.

A worker that dies, of a crash or of SIGKILL from the kernel's OOM killer, is replaced while the other
workers keep serving (a worker that keeps dying within 10 s of starting waits 1 s, then 2, 4, up to
30 s, between restarts; each restart is logged). Watch for `was killed by signal 9` in the logs: it
means a worker ran out of memory.

Throughput measured by the production audit (2026-10-24, 4-core VM, `hey -z 8s`, a mock that
answers at once): about 9,000 rps for one worker and 11,000 to 18,600 rps for two, at 16 to 256
connections.

## Stopping and slow clients

SIGTERM (and SIGINT) stop Raiju gracefully, in every worker: `/ready` answers 503 at once, the
listener closes after `server.shutdown_delay_seconds` (default 0), the requests and streams in hand
get up to `server.shutdown_grace_seconds` (default 25) from the signal, then queued exporter
batches, retained content and trace spans are sent (about 5 s at most) and the process exits 0.
Whatever is still open at the grace is cut. Give the orchestrator a kill timeout above the sum. The
chart sleeps 5 s in a preStop hook first (the pod keeps serving while the endpoints drop it), then
sends SIGTERM, and sets `terminationGracePeriodSeconds: 40`; it refuses a value below
`preStopSleepSeconds + shutdown_delay_seconds + shutdown_grace_seconds + 5`. Compose gives the
container `stop_grace_period: 35s`.

WebSocket and WebRTC sessions are part of the drain. The UI's live feed sockets (`/ws`) are closed
with code 1001 (going away) when the listener closes: the dashboard reconnects to another instance
and resumes from its cursor. Realtime, Responses and GPT Live sessions keep running until the grace
and are then closed with a 1001 close frame ("server shutting down"; a WebRTC call is closed), so
their usage is billed and logged before the exit; a session that does not close within 3 s more is
cut. Clients should reconnect on 1001.

Broker mode (`-mode broker`) stops the same way: `/ready` turns 503 (`/health` stays 200), the
listener closes after `shutdown_delay_seconds`, the exchanges in hand finish within
`shutdown_grace_seconds`, and it exits 0. Its timeouts and connection cap are the `server.*` keys
below.

Both servers time out slow or silent clients: a request head must arrive within
`server.header_timeout_seconds` (default 10; a half-sent head is answered 408), a body must not
go `server.body_timeout_seconds` (default 60) without a byte (408), and a keep-alive connection
with no request in hand closes after `server.idle_timeout_seconds` (default 60). A request being
handled (a slow completion, a stream) is never timed out by these, but a client that stops reading
is: output the client does not take for `server.idle_timeout_seconds` (a stalled download, an
abandoned stream or WebSocket on http1) ends the connection. `server.max_connections` caps
each process's open connections (default: three quarters of its descriptor limit, `ulimit -n`;
-1 for no cap): a request on a connection past it is answered 503, and so is a connection that
comes when the process is out of descriptors. 0 turns a timeout off. These keys are read at start.

## Behind a proxy or ingress

The audit log and the sign-in throttle use the client's address. Raiju believes `X-Forwarded-For` and
`X-Real-IP` only from the proxies in `server.trusted_proxies` (addresses or CIDR ranges). Behind a load
balancer, an ingress controller or the ECS ALB, list its addresses (for a cluster, the pod or node range the
ingress runs in), or every request is seen as coming from the proxy: the audit log then names the proxy, and
failed sign-ins from all clients count against one address (`server.sign_in_throttle.ip_failures`, 20 an hour).

A keep-alive connection that a client or proxy reuses just as the idle timeout closes it gets no
answer (the request finds the connection closed: an incomplete read, or a 502 from a load
balancer). Keep the idle timeout of whatever pools connections to Raiju below
`server.idle_timeout_seconds`, or raise the latter above it: an AWS ALB defaults to 60 s, the same as
Raiju, so the ECS module sets the ALB's to 55 s (`alb_idle_timeout`). `tests/soak/soak.py` drops a
pooled connection idle for 50 s for the same reason.

Request bodies: a body over 64 KB is not read before the caller's credentials are checked, so an
inference call without a valid virtual key (while `client.enforce_auth_on_inference` is on) or a
management call the gate refuses is answered 401 or 403 unread. `server.max_buffered_body_mb`
(default 48; -1 for no cap; read per request) caps the request-body megabytes each process reads at
once: a body that does not fit is answered 503 with `retry-after: 1` (unread when its declared length
cannot fit beside the bytes held), and is retried by well-behaved clients. Bytes are charged as they
arrive, so a client trickling a big declared body holds only what it has sent, and a body over 64 KB
must arrive whole within `server.body_deadline_seconds` (default 120, 0 off; 408 otherwise: raise it
for slow uploaders of big files). The public routes (`/api/session/*`, `/api/agent/*`, `/api/oauth2/*`,
`/api/oidc/*`, the MCP authorization server's `/oauth2/*`) read at most 64 KB. The cluster peer routes
refuse a body without a signature header before reading it and read at most `cluster.max_body_mb`
(default 16 MB; a node whose sync body outgrows it logs so, and every node needs the higher value).
A body is always read when the process holds no other, so a single request up
to `client.max_request_body_size_mb` (default 100) is still served; parsing a chat body costs about
six to eight times its size, so on a small pod lower `max_request_body_size_mb` too (on the chart's
512Mi limit a lone 90 MB body peaks near 700 MB; 32 MB keeps a lone body near 250 MB). The default of
48 keeps a worker near 320 MB with the cap full (`bench/body_memory.py`). With `-workers N` each worker
has its own cap.

## AWS credentials from the workload

A Bedrock key with neither an API key (`value`) nor `access_key`/`secret_key`, and Vertex's
`aws_workload_identity` (or an AWS `external_account` file), take the AWS SDK's default chain, as
Bifrost does: the environment (`AWS_ACCESS_KEY_ID`, ...), an EKS IRSA web identity
(`AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_ARN`, which the EKS webhook sets for a service account
annotated with `eks.amazonaws.com/role-arn`), the shared credentials file, ECS task roles and EKS
Pod Identity (`AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` or `_FULL_URI`, which ECS and the Pod
Identity agent set) and the EC2 instance profile (IMDSv2). The region falls back to the instance
metadata's. On ECS the module's task role is the identity; give it the Bedrock permissions the keys
need. `AWS_EC2_METADATA_DISABLED=true` skips the instance metadata.

## Docker

The image's bases are pinned by tag and digest (`ARG DEBIAN` in the Dockerfile), and rustup-init
is checked against its published sha256.

```sh
docker build -t raiju:local .

# Providers from environment variables, no config file (state in the container's anonymous volume):
docker run --rm -p 8080:8080 -e OPENAI_API_KEY=sk-... raiju:local

# With a config file kept in a named volume: copy it in once, then run with the volume
docker volume create raiju-data
docker run --rm -v raiju-data:/app/data -v "$PWD/deploy/config.example.json:/seed.json:ro" \
  --entrypoint cp raiju:local /seed.json /app/data/config.json
docker run -d --name raiju -p 8080:8080 -v raiju-data:/app/data --env-file .env raiju:local

curl localhost:8080/health
docker inspect --format '{{.State.Health.Status}}' raiju   # healthy, from raiju -healthcheck
```

The default command is `-app-dir /app/data -host 0.0.0.0 -port 8080`: the image binds every address
explicitly, as the binary binds 127.0.0.1 outside a container unless told otherwise. If you pass arguments,
pass all of them (including `-host 0.0.0.0`), because they replace the default command; if you change
`-port`, also set `PORT` to the same value so the HEALTHCHECK probes the right port. Use `-workers N` for
more processes per container. Do not bind-mount `config.json` read-only into `/app/data` for a gateway you
manage through the API or UI: saves would fail.

The management API (`/api` and the dashboard) is locked until an admin exists, as in Bifrost: pass a setup
token (`-e BIFROST_SETUP_TOKEN=...`, or `setup_token` in the config), create the first admin with it
(the dashboard's setup screen, or `POST /api/users` with the token in `X-Bifrost-Setup-Token`), and sign
in from then on. With no admin and
no setup token, `/api` answers 403. Inference is unaffected.

## Docker Compose

```sh
# optional: create .env with NAME=value lines (e.g. OPENAI_API_KEY=sk-...)
docker compose up --build
docker compose --profile metrics up --build   # adds Prometheus on :9090
```

`.env` is optional and is never copied into the image (`.dockerignore`). Put
`BIFROST_SETUP_TOKEN=...` in it to create the first admin with (see Docker above). The compose file passes
`-host 0.0.0.0` explicitly. `/app/data` is the named volume `raiju-data`. A one-shot `raiju-config`
service copies `deploy/config.example.json` into it when it has no `config.json` yet; after that, the file
in the volume is the one Raiju reads and the API and UI edit (the first admin included), and it survives
`docker compose down` and restarts. To start over from the file, `docker compose down -v`. To use your own
config, change the `raiju-config` mount in `docker-compose.yml`. Compose reads the image's HEALTHCHECK,
and Prometheus starts once Raiju is healthy. `deploy/prometheus.yml` scrapes `raiju:8080/metrics`. With
`server.metrics_token` set (`"env.RAIJU_METRICS_TOKEN"`, the value in `.env`), give Prometheus the same token
(the commented `authorization` block in `deploy/prometheus.yml`).

## Helm

The chart is in `deploy/helm/raiju`. Push the image somewhere the cluster can pull it, then:

```sh
kubectl create secret generic raiju-keys --from-literal=OPENAI_API_KEY=sk-...

helm install raiju deploy/helm/raiju \
  --set image.repository=registry.example.com/raiju \
  --set image.tag=0.1.0 \
  --set existingSecret=raiju-keys
```

The pod runs with a read-only root filesystem. `/app/data` is a PersistentVolumeClaim (1Gi,
ReadWriteOnce, kept on uninstall) and `/tmp` an emptyDir. An init container copies the `config`
value (rendered into a ConfigMap) to `/app/data/config.json`: with `configMode: ifAbsent` (the
default) only when the file is not there yet, so changes made through the API or UI persist and a
later change to `config` reaches only a fresh volume; with `configMode: always` at every start
(config as code: `config` is the source of truth and API changes last until the pod restarts).
Liveness probes `GET /health`, readiness `GET /ready`.

Useful values (see `values.yaml`):

| Value | Purpose |
|---|---|
| `config` | The whole `config.json` as YAML, rendered to a ConfigMap and copied to the data volume. |
| `configMode` | `ifAbsent` (default) or `always`, as above. |
| `persistence.enabled` | `true`: a PVC at `/app/data` (`existingClaim`, `storageClass`, `accessModes`, `size`, `keep`). `false`: an emptyDir, lost with the pod. |
| `tmp.sizeLimit` | Size limit of the `/tmp` emptyDir (256Mi). |
| `providerSecrets` | Map of env var name to value, rendered to a Secret and injected with `envFrom`. Use for quick tests only: values end up in the release history. |
| `existingSecret` | Name of a Secret you created (preferred). Replaces `providerSecrets`. |
| `workers` | Passed as `-workers`. |
| `resources` | Requests 128Mi, limit 512Mi (see Sizing). |
| `preStopSleepSeconds`, `terminationGracePeriodSeconds` | 5 and 40 (see Stopping). |
| `probes` | Liveness (`/health`) and readiness (`/ready`) timings. |
| `replicaCount` | Pods. Ignored when `autoscaling.enabled`. More than one needs shareable storage (below). |
| `strategy` | Empty: `Recreate` with a ReadWriteOnce claim, `RollingUpdate` otherwise. A rolling update on a ReadWriteMany volume runs two versions on one `config.json`; see "Upgrading on a shared volume" below. |
| `peers.headlessService` | A headless Service, `<release>-peers`, for cluster discovery by DNS (always rendered with a cluster listener). |
| `cluster.secret.existingSecret`, `cluster.secret.key` | The Secret holding `cluster.secret` (at least 32 bytes), injected as `RAIJU_CLUSTER_SECRET`; `config.cluster.secret` defaults to `env.RAIJU_CLUSTER_SECRET`. Required with `config.cluster.enabled`, and the chart refuses a secret written into the config. |
| `cluster.listenPort` | The cluster listener (`config.cluster.listen_port`, 7946): the peer routes are served there and refused on the main port; the peers Service targets it. `0` keeps them on the main port. |
| `cluster.serveMetrics` | Serve `/metrics` on the cluster port only; the annotations and the ServiceMonitor follow. |
| `metricsToken.existingSecret`, `metricsToken.key` | A bearer token for `/metrics` (`config.server.metrics_token`), injected as `RAIJU_METRICS_TOKEN`; the ServiceMonitor sends it. Off: `/metrics` is open. |
| `service.type`, `service.port` | Service. The pod port is `port`. |
| `prometheus.annotations` | `prometheus.io/*` annotations on pod and Service (on by default). |
| `serviceMonitor.enabled` | Prometheus Operator ServiceMonitor (needs its CRDs). Off by default. |
| `autoscaling.enabled` | HPA on CPU. Off by default. |
| `podDisruptionBudget.enabled` | PDB. Off by default. Only useful with 2+ replicas. |

Pods roll automatically when the ConfigMap or the chart's Secret changes. Changes to an
`existingSecret` are not detected, so restart the deployment (`kubectl rollout restart deploy/raiju`).

The container passes `-host 0.0.0.0` (the binary's own default is 127.0.0.1). `/api` is locked until an
admin exists: set `setupToken.existingSecret` (a Secret with a `BIFROST_SETUP_TOKEN` key, or the key named
by `setupToken.key`), or put `BIFROST_SETUP_TOKEN` in `existingSecret`, then create the first admin with
`POST /api/users` and the token in `X-Bifrost-Setup-Token`. With a PVC the admin is kept in
`/app/data/config.json`; with `configMode: always` it is lost at the next start unless `config` holds it.

```sh
kubectl create secret generic raiju-setup --from-literal=BIFROST_SETUP_TOKEN=$(openssl rand -hex 16)
helm upgrade --install raiju deploy/helm/raiju --reuse-values --set setupToken.existingSecret=raiju-setup
```

Plugins whose `path` is a URL are downloaded into a private (0700) `plugin-cache` folder beside
`config.json`, which is on the writable data volume. A plain-http plugin URL needs a `sha256` pin on its
entry. See [SECURITY.md](../SECURITY.md) for the outbound address rules.

MCP tools are denied to a virtual key that declares no `mcp_configs`, and WebRTC realtime is off unless
`server.webrtc_enabled` is true (WebRTC also needs `RAIJU_WEBRTC_BIND` and UDP reachability, which a
plain Service does not give).

### Several replicas

A ReadWriteOnce volume serves one pod, so the chart refuses `replicaCount` above 1 (or autoscaling)
with it. Replicas only share budgets, rate limits, state and config changes as a Raiju cluster
(`config.cluster`, see [docs/operations.md](../docs/operations.md)); without one, each pod enforces its
own limits and keeps its own config. Within a pod, a change saved through the API is applied by every
worker before the API answers. Two layouts work:

- Each pod its own data (`persistence.enabled: false`, `configMode: always`): the ConfigMap is the
  config at every start, and a cluster with `config_sync: "pull"` fetches every save from the peer that
  made it and writes it to its own (emptyDir) `config.json`, so API changes reach the other pods while they
  run. A full restart goes back to the ConfigMap. Pull needs peers: use the headless Service below for
  discovery (a cluster of type `broker` has none and must share the file).
- One shared ReadWriteMany volume (`persistence.accessModes: [ReadWriteMany]`, on EFS, NFS and the
  like) with `config_sync: "file"`: every pod rereads the same `config.json` when another saves it. The
  pods then also share `logs/` and the MCP OAuth state, so turn the log store off or give it a per-pod
  folder.

Upgrading on a shared volume: a rolling update (the chart's default with ReadWriteMany, and the ECS
module's default with EFS) runs old and new pods on one `config.json` for a while. Their saves are merged
under a file lock, so none is lost, as long as both versions take the same lock: any two releases from
wave 26 on (flock on `config.json.flock`), and from wave 27 on also the wave 25 release (wave 27 takes its
`config.json.lock` directory too). Upgrade a release before wave 25 (no lock), or wave 25 straight to a
release after wave 27, with `strategy: {type: Recreate}` (ECS: `deployment_minimum_healthy_percent = 0`,
`deployment_maximum_percent = 100`) for that one upgrade. docs/operations.md has the details and what flock
means on NFS and EFS.

Each pod's log and audit folders are on its own data volume (`/app/data/logs`, `/app/data/logs/audit`):
`/api/logs` answers from the pod that is asked. An enabled store that cannot open its folder stops the
pod's start (set `"required": false` in the section to start without it).

When `config.cluster.enabled` is true and `config_sync` is not set, the chart sets it from the
layout ("file" for a ReadWriteMany volume, "pull" otherwise). A cluster in either layout:

```yaml
replicaCount: 3
persistence:
  enabled: false
configMode: always
peers:
  headlessService: true
cluster:
  secret:
    existingSecret: raiju-cluster      # kubectl create secret generic raiju-cluster --from-literal=RAIJU_CLUSTER_SECRET=$(openssl rand -hex 32)
  listenPort: 7946                     # the default: peer routes on their own port, off the public Service
config:
  cluster:
    enabled: true                      # secret: env.RAIJU_CLUSTER_SECRET, listen_port and bind are set by the chart
    discovery:
      enabled: true
      type: dns
      dns_names: ["raiju-peers"]       # <release>-peers; bind_port defaults to the cluster port
      advertise_address: env.POD_IP    # the chart sets POD_IP
```

The gateway refuses to start with clustering on when `cluster.secret` is empty, names a variable that is
not set, or is shorter than 32 bytes: every route under `/api/cluster/` (the config with its stored keys, the
request logs, the budget counters, the live feed) is signed with it. `env.NAME` references in `cluster.secret`,
`cluster.bind`, `cluster.broker.address` and `cluster.discovery.advertise_address` / `consul_address` are
resolved like any other. Static `peers` name the peers' cluster port (`raiju-1.raiju-peers:7946`).

Send management traffic to one pod or accept that the last save wins (docs/operations.md, One
writer). `workers` is for CPU within a pod (about the number of cores it gets); replicas are for
capacity and availability.

## Config and secrets

- `config.json` uses Bifrost's format ([docs/config-reference.md](../docs/config-reference.md)).
  Any value written `env.NAME` is replaced with the environment variable `NAME` when the config
  loads (the process reads `/proc/self/environ`). Keep keys in the environment, not in the file.
- The file is read at start. Changes made through the management API or the web UI are saved to it
  and applied at once by every worker ([docs/operations.md](../docs/operations.md) covers nodes). An
  edit to the file on disk applies at the next start.
- If the config file is missing, Raiju builds providers from well-known variables such as
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.

## Memory and the request log

- A worker starts at about 20 MB and settles at 40 to 60 MB under load. Each open stream adds about 170 KB
  while it lasts, so set the memory limit from the streams a pod holds at once: 1,000 open streams on one worker
  need about 170 MB more. `make soak` measures both on your build.
- With `logs_store` on, a single process writes its rows in batches (every 100 ms or 64 KB); SIGTERM writes the
  last batch before the process exits (only a hard kill loses it). With `workers` above 1, each row is written as it comes, because the
  workers read each other's rows from the files.
- Each day's file is cut into segments of `logs_store.max_file_mb` (default 32), and start-up reads only the
  newest segments of today, so a restart late in a busy day stays quick.
- `logs_store.retention_days` (default 7) removes whole days. `logs_store.max_disk_mb` (default 512; 0 for no
  cap) also caps the folder: the oldest segments are deleted first. Set it below the volume's size; at 1,500
  requests a second a day of rows is on the order of 100 GB.
- With `logs_store.object_storage` set (S3, or GCS through its S3 interop API), the rows keep their metadata and a
  prompt preview and each row's bodies, raw payloads and plugin logs go to the bucket (Bifrost's hybrid store), which
  keeps the folder small; the log detail reads them back. `object_storage.format` is `json` (default) or `parquet`,
  `compression` `none` or `gzip` (Parquet's snappy and zstd are written as GZIP pages); set
  `logs_store.object_storage_offload: false` to keep rows whole. Rows beyond `max_memory_entries` are read from the
  files when a query's window reaches them.

## Limits of this packaging

- The image builds Tov from source (the installer needs network access and takes several minutes).
  The binary is dynamically linked against glibc, libstdc++ and WebKitGTK's JavaScriptCore (Tov
  links it for `node:*` modules), so the runtime is `debian:bookworm-slim` with
  `libjavascriptcoregtk-4.1-0`, not distroless, and carries JavaScriptCore's GLib and ICU
  libraries. CI scans it with trivy on every push to main.
- The chart's pod security settings (read-only root filesystem, no capabilities, fsGroup on the
  data volume) are checked with `helm template` (`make deploy-check`) and trivy's config rules, but
  have not been exercised on a cluster.
