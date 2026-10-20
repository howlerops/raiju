# Deploying Raiju

Raiju is one binary. Terraform modules (Helm release, AWS ECS Fargate) are in
[terraform/](terraform/README.md).

Raiju is one binary. The image runs it as non-root on a slim Debian base
(bookworm-slim with JavaScriptCore, which the binary links). It takes a
Bifrost-format `config.json` from `/app/data`, and provider keys come from environment variables that the config refers to as `env.NAME`.

Endpoints for probes and scraping: `GET /health` (200, `{"status":"ok"}`) and
`GET /metrics` (Prometheus text, Bifrost metric names). The image has no
HEALTHCHECK (there is no curl), so probe from outside the container.

## Docker

```sh
docker build -t raiju:local .

# Providers from environment variables, no config file:
docker run --rm -p 8080:8080 -e OPENAI_API_KEY=sk-... raiju:local

# With a config file (env.NAME values read from the environment; .env must exist):
docker run --rm -p 8080:8080 \
  -v "$PWD/deploy/config.example.json:/app/data/config.json:ro" \
  --env-file .env \
  raiju:local

curl localhost:8080/health
```

The default command is `-app-dir /app/data -host 0.0.0.0 -port 8080`. If you
pass arguments, pass all of them, because they replace the default command.
Use `-workers N` for more processes per container.

## Docker Compose

```sh
# optional: create .env with NAME=value lines (e.g. OPENAI_API_KEY=sk-...)
docker compose up --build
docker compose --profile metrics up --build   # adds Prometheus on :9090
```

`.env` is optional and is never copied into the image (`.dockerignore`).
Compose mounts `deploy/config.example.json` as `/app/data/config.json`. To use
your own config, change that line in `docker-compose.yml`.
`deploy/prometheus.yml` scrapes `raiju:8080/metrics`.

## Helm

The chart is in `deploy/helm/raiju`. Push the image somewhere the cluster can
pull it, then:

```sh
kubectl create secret generic raiju-keys --from-literal=OPENAI_API_KEY=sk-...

helm install raiju deploy/helm/raiju \
  --set image.repository=registry.example.com/raiju \
  --set image.tag=0.1.0 \
  --set existingSecret=raiju-keys
```

Useful values (see `values.yaml`):

| Value | Purpose |
|---|---|
| `config` | The whole `config.json` as YAML. Rendered to a ConfigMap, mounted at `/app/data/config.json`. |
| `providerSecrets` | Map of env var name to value, rendered to a Secret and injected with `envFrom`. Use for quick tests only: values end up in the release history. |
| `existingSecret` | Name of a Secret you created (preferred). Replaces `providerSecrets`. |
| `workers` | Passed as `-workers`. |
| `replicaCount` | Pods. Ignored when `autoscaling.enabled`. |
| `service.type`, `service.port` | Service. The pod port is `port`. |
| `prometheus.annotations` | `prometheus.io/*` annotations on pod and Service (on by default). |
| `serviceMonitor.enabled` | Prometheus Operator ServiceMonitor (needs its CRDs). Off by default. |
| `autoscaling.enabled` | HPA on CPU. Off by default. |
| `podDisruptionBudget.enabled` | PDB. Off by default. Only useful with 2+ replicas. |

Pods roll automatically when the ConfigMap or the chart's Secret changes.
Changes to an `existingSecret` are not detected, so restart the deployment
(`kubectl rollout restart deploy/raiju`).

## Config and secrets

- `config.json` uses Bifrost's format. Any value written `env.NAME` is replaced
  with the environment variable `NAME` when the config loads (the process
  reads `/proc/self/environ`). Keep keys in the environment, not in the file.
- The config is read once at start. Changing it means restarting the process.
- If the config file is missing, Raiju builds providers from well-known
  variables such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.
- Probes: liveness and readiness on `/health`, port `http` (the container port).

## Workers vs replicas

Governance (budgets, rate limits), the response cache and metrics counters live
in memory in each worker process. They are not shared:

- Each worker enforces its own budget and rate limit. With 4 replicas of 2
  workers, a budget of $10 can be spent as up to $80 in total. Divide the limits
  by the number of processes, or accept that they are per-process.
- Cache hits only happen within one process. More replicas mean a lower hit rate.
- `/api/governance/budgets` and `/api/cache` report one process, not the fleet.

Use `workers` for CPU use within a pod (about the number of cores the pod gets),
and replicas for capacity and availability. Each new replica, including one from
the HPA, adds another full set of per-process limits.

## Limits of this packaging

- The image builds Tov from source (the installer needs network access and takes
  several minutes). The binary is dynamically linked against glibc, libstdc++ and
  WebKitGTK's JavaScriptCore (Tov links it for `node:*` modules), so the runtime is
  `debian:bookworm-slim` with `libjavascriptcoregtk-4.1-0`, not distroless.
- The chart's pod security settings (read-only root filesystem, no capabilities)
  have not been exercised on a cluster.
