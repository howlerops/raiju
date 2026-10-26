# Staging validation

The six production audits (docs/audits/) end with the same list: what only real infrastructure can confirm. This
runbook is how an operator confirms it before a release goes to production. Nothing in it has been run yet: the
development container has no cloud account, provider keys or IdP tenant. Record the results (the
`staging-results/` folder each run writes) with the release.

The steps run in order. Each one needs the ones before it. Budget about three working days, most of it the 24-hour
soak and waiting on the IdP tenants.

| Step | Confirms | Audit items |
|---|---|---|
| [(a)](#a-real-providers-and-a-24-hour-memory-soak) | Real providers; flat memory at 512Mi for 24 h with real traffic | re-audit 3-6 "memory against 512Mi", "real provider latency", "worker respawn under the OOM killer" |
| [(b)](#b-the-ecs-module-on-aws) | The ECS module applied: ALB, TLS, trusted proxies, first admin | "the ECS terraform applied on AWS", "ALB with RAIJU_TRUSTED_PROXIES" |
| [(c)](#c-a-real-identity-provider) | Okta and Entra: SSO through TLS, SCIM push, directory sync, session refresh | "real IdPs and cookies behind TLS proxies" |
| [(d)](#d-flock-on-efs) | flock on EFS: concurrent creates, lease release after a crash, the bridge under skew | "flock on EFS/NFS", "the bridge's stale rule under clock skew" |
| [(e)](#e-rolling-upgrades) | Rolling and stop-first upgrades under concurrent writes | "ECS/EKS rolling and stop-first upgrades" |
| [(f)](#f-multi-node) | Three tasks: Cloud Map, config sync, log reads, counters, the cluster listener, a partition | "multi-node clusters over a real network" |

## The kit

| Path | What it is |
|---|---|
| `deploy/terraform/examples/staging/` | A throwaway stack: the aws-ecs module with EFS, the ALB and TLS, a setup token and a cluster secret in Secrets Manager, one task or a three-task cluster (`cluster = true`), a seed task that writes `config.json` on EFS and a probe task for the lock checks. Every resource is tagged `purpose=raiju-staging`, `owner` and `expires_at`. |
| `tests/staging/` | The audits' repro scripts, pointed at a URL. Each prints one `PASS`, `FAIL` or `SKIP` line per check with its numbers, and exits 1 when a check failed. Python 3 standard library only. |
| `tests/staging/run.py` | Runs a set of them and collects `results.jsonl`, one log per check and `summary.md` in `--out`. |
| `.github/workflows/staging.yml` | The same from GitHub Actions: started by hand only (workflow_dispatch), with secrets from the `staging` environment; uploads `staging-results`. |

The scripts:

| Script | Check |
|---|---|
| `smoke_check.py` | /health, /ready, the certificate and the HTTP-to-HTTPS redirect, `/api` locked without credentials (and the setup token closed once an admin exists), an unknown virtual key refused, /v1/models, a chat whole and streamed, /metrics. `--providers openai/gpt-4.1-nano,...` also runs `tests/smoke.py`'s per-provider matrix (tool call, embeddings, native routes, the large request, log rows with cost) through the URL. |
| `creates.py` | 40 concurrent virtual key creates and 40 concurrent updates, spread over one or more URLs; every acknowledged write must be readable on every URL afterwards. |
| `bridge.py` | `creates.py` across an old and a new release on one volume, in rounds. |
| `body_soak.py` | Mixed traffic for a duration (chats, streams, long-context chats, bodies from 64 KB to 50 MB) while the RSS is sampled; a chart (`rss.svg`), `samples.csv` and a verdict. |
| `trickle.py` | A checked body that sends 8 MB and then a byte every 2 s must be cut within 60 s while another tenant's chats are served; an unauthenticated trickle to `/mcp` must be answered too. |
| `declared.py` | Clients that declare 12 MB and send nothing must not lock another tenant's 1 MB and 4 MB bodies out. |
| `dcr_flood.py` | A flood of `/oauth2/register` (half with forged `X-Forwarded-For`) gets 429 after one address's allowance, `/health` stays fast, and an earlier client still reaches the consent page. |
| `cluster_check.py` | `listener`, `sync`, `logs`, `counters` (or `all`), and `watch` for a partition. |
| `lock_probe.py` | Run where the volume is mounted: `hold` and `wait` on the gateway's lock file, `skew` against the file server's clock, `legacy` to time the upgrade bridge's stale rule. |

Settings, read from the environment by every script (flags override):

| Variable | Meaning |
|---|---|
| `RAIJU_BASE_URL` | The gateway as clients reach it (`https://raiju-staging.example.com`). |
| `RAIJU_ADMIN_TOKEN` | A management credential sent as `Authorization: Bearer` (the token `POST /api/users` returned, or a session token). `RAIJU_ADMIN_USER` and `RAIJU_ADMIN_PASSWORD` sign in instead. |
| `RAIJU_VKS` | Comma-separated virtual keys. The first is the main one; the body checks need at least two of different tenants (keys with different customers or teams, or keys with neither). |
| `RAIJU_MODEL` | `provider/model` for the inference checks (default `openai/gpt-4o-mini`). Use a cheap one. |
| `RAIJU_NODE_URLS` | Each node's main port, comma-separated, as reached from inside the VPC (step (f)). |
| `RAIJU_CLUSTER_SECRET`, `RAIJU_CLUSTER_PORT` | The cluster secret and the cluster listener port (7946). `RAIJU_CLUSTER_URLS` names each node's listener when the ports differ. |
| `RAIJU_METRICS_TOKEN`, `RAIJU_SETUP_TOKEN`, `RAIJU_CA_FILE` | The /metrics bearer token, the setup token (checked to open nothing), a CA bundle for a private certificate. TLS is always verified. |
| `RAIJU_RSS_CMD`, `RAIJU_RSS_METRIC` | Where the soak reads memory (see (a)). |
| `RAIJU_OLD_URL`, `RAIJU_NEW_URL` | The two releases for `run.py --checks bridge`. |

Body checks send their big bodies to the model `staging-discard/none` by default: it names no provider, so the
gateway reads the whole body through the body budget and answers 400 without calling anyone. The memory path is
exercised at no provider cost.

Every script creates what it needs under names starting `stg-<run>-` and deletes it at the end (`--keep` keeps it).

## Before you start

- A sandbox AWS account you may break, with a VPC that has two public subnets and two private subnets with a NAT
  gateway, in two Availability Zones.
- The release candidate image in ECR in that account (the image is built and scanned by CI on `main`; push the tag
  you are validating).
- A DNS name you control (`raiju-staging.example.com`) and an ACM certificate for it in the same region.
- Provider keys for the providers you ship with, each in Secrets Manager (`aws secretsmanager create-secret --name
  raiju-stg/openai --secret-string ...`). Budget: the smoke matrix costs cents; the soak's chat traffic at the
  default rate is about $10 to $30 a day on a small model (the big bodies cost nothing, see above).
- Terraform 1.7 or later, the AWS CLI with the Session Manager plugin (for ECS Exec), Python 3.10 or later, `curl`
  and `jq` on the operator host.
- For (d) and (f): a host inside the VPC (the probe task, a bastion, or a self-hosted GitHub runner), since the
  nodes' addresses and the cluster port are private.

### Bring the stack up

```sh
cd deploy/terraform/examples/staging
cat > staging.tfvars <<'EOF'
owner               = "you@example.com"
vpc_id              = "vpc-..."
public_subnet_ids   = ["subnet-...", "subnet-..."]
task_subnet_ids     = ["subnet-...", "subnet-..."]
image               = "123456789012.dkr.ecr.us-east-1.amazonaws.com/raiju:<candidate>"
certificate_arn     = "arn:aws:acm:us-east-1:123456789012:certificate/..."
public_url          = "https://raiju-staging.example.com"
ingress_cidr_blocks = ["203.0.113.10/32"]   # your address, the runner's
provider_secret_arns = { OPENAI_API_KEY = "arn:aws:secretsmanager:us-east-1:123456789012:secret:raiju-stg/openai-..." }
providers_from_env   = { openai = "OPENAI_API_KEY" }
EOF
terraform init
terraform apply -var-file=staging.tfvars                     # start_service = false: no task yet
eval "$(terraform output -raw seed_command)"                 # the seed task writes config.json on EFS
terraform apply -var-file=staging.tfvars -var start_service=true
terraform output alb_dns_name                                # point raiju-staging.example.com at it (CNAME)
```

`terraform output -raw seeded_config` shows the config the seed task wrote (no secret values: `env.NAME`
references). To change it, edit the variables, apply, and run the seed task again with `SEED_FORCE=1`
(`aws ecs run-task ... --overrides '{"containerOverrides":[{"name":"seed","environment":[{"name":"SEED_FORCE","value":"1"}]}]}'`).

### Teardown

The stack is throwaway: the secrets have no recovery window and the EFS file system goes with its data.

```sh
cd deploy/terraform/examples/staging
terraform destroy -var-file=staging.tfvars
aws resourcegroupstaggingapi get-resources --tag-filters Key=purpose,Values=raiju-staging   # must list nothing
```

A stack past its `expires_at` tag is fair game for anyone to destroy. Delete the provider-key secrets you made by
hand, and the DNS record.

## (a) Real providers and a 24-hour memory soak

**Prerequisites:** the stack up with one task (`cluster = false`), the first admin made (step (b) below shows how; do
that part first), two virtual keys of different tenants with access to `RAIJU_MODEL`.

**Real providers, locally.** `make smoke` runs `tests/smoke.py` against a local build with the keys in your
environment (README, Real-provider smoke tests):

```sh
export OPENAI_API_KEY=... ANTHROPIC_API_KEY=...        # the providers you ship with
make build TOV=$TOV && SMOKE_NO_BUILD=1 make smoke
```

**Real providers, deployed.** The same matrix through the ALB:

```sh
export RAIJU_BASE_URL=https://raiju-staging.example.com RAIJU_ADMIN_TOKEN=... RAIJU_VKS=sk-bf-...,sk-bf-...
python3 tests/staging/smoke_check.py --providers openai/gpt-4.1-nano,anthropic/claude-haiku-4-5
```

*Pass:* every line `PASS` (or `SKIP` for what is not configured), exit 0. `smoke.matrix.<provider>` passes when that
provider's matrix had no failure. *Fail:* any `FAIL`; a `cost 0` failure means the model is missing from the price
table.

**The soak.** One task with the chart's limit (the module's `memory = 512`), 24 hours of mixed traffic. Memory comes
from ECS: Container Insights, or the task's metadata. The simplest source is CloudWatch's `MemoryUtilized` for the
service, read by `--rss-cmd` every minute:

```sh
CLUSTER=$(terraform -chdir=deploy/terraform/examples/staging output -raw cluster_name)
SERVICE=$(terraform -chdir=deploy/terraform/examples/staging output -raw service_name)
aws ecs update-cluster-settings --cluster "$CLUSTER" --settings name=containerInsights,value=enabled
export RAIJU_RSS_CMD="aws cloudwatch get-metric-statistics --namespace ECS/ContainerInsights \
  --metric-name MemoryUtilized --dimensions Name=ClusterName,Value=${CLUSTER##*/} Name=ServiceName,Value=$SERVICE \
  --start-time \$(date -u -d '-2 min' +%FT%TZ) --end-time \$(date -u +%FT%TZ) --period 60 --statistics Maximum \
  --query 'Datapoints[-1].Maximum' --output text | sed 's/\$/ MiB/'"
python3 tests/staging/body_soak.py --duration 24h --rate 2 --sample-every 60 --limit-mb 512 \
  --out staging-results/soak
```

A host that can see the process (a self-managed runner, or EKS with `kubectl top`) can use
`--rss-cmd "kubectl top pod -l app.kubernetes.io/name=raiju --no-headers | awk '{print \$3}'"`; a Prometheus
exporter beside the gateway, `--rss-metric process_resident_memory_bytes --metrics-url http://exporter:9256/metrics`.
`--mix l210` replays `tests/soak/bodies.py`'s loop (the pattern of re-audit 6's leak); the default mix spans 64 KB to
50 MB, with 50 MB bodies past the 48 MB budget answered 503 and counted as refused.

*Watch:* the progress line every 10 minutes (requests, errors, refused, RSS); the ECS service events
(`aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --query 'services[0].events[:5]'`) for a
stopped task; the task's `StoppedReason` (`OutOfMemoryError` is an OOM kill); the log group for a worker started again (a worker the OOM killer kills inside a running task is
respawned, tov-patches 0019: RSS samples then drop without the task stopping).

*Pass:* `PASS soak`: growth over the second half under 32 MB (`--max-growth-mb`), peak under 90% of 512 MB, no
restart in the samples, errors (connection failures and 5xx other than the body budget's) under 1%; no task stopped
in the service events; `rss.svg` flat after the warm-up. *Fail:* any of those; attach `rss.svg`, `samples.csv`,
`summary.json` and the log group's last hour to the report.

**Teardown:** nothing to undo; turn Container Insights off if the account does not normally use it.

## (b) The ECS module on AWS

**Prerequisites:** the stack applied as above, DNS pointing at the ALB.

```sh
cd deploy/terraform/examples/staging
BASE=$(terraform output -raw base_url)
curl -si "http://${BASE#https://}/health" | head -3            # 301 to https
curl -s "$BASE/health"; curl -s -o /dev/null -w '%{http_code}\n' "$BASE/ready"          # {"status":"ok"} 200
curl -s -o /dev/null -w '%{http_code}\n' "$BASE/api/governance/virtual-keys"            # 401: /api is locked
SETUP=$(eval "$(terraform output -raw setup_token_command)")
curl -s -X POST "$BASE/api/users" -H "X-Bifrost-Setup-Token: $SETUP" -H 'content-type: application/json' \
  -d '{"name":"ops-admin","role":"admin"}' | jq -r .token > admin-token && chmod 600 admin-token
export RAIJU_BASE_URL=$BASE RAIJU_ADMIN_TOKEN=$(cat admin-token) RAIJU_SETUP_TOKEN=$SETUP
curl -s -X POST "$BASE/api/governance/virtual-keys" -H "Authorization: Bearer $RAIJU_ADMIN_TOKEN" \
  -H 'content-type: application/json' -d '{"name":"staging-a"}' | jq -r .value      # repeat for staging-b
export RAIJU_VKS=sk-bf-...,sk-bf-...
python3 tests/staging/run.py --checks smoke,creates,trickle,declared,dcr --out staging-results/b
```

Trusted proxies: the module sets `RAIJU_TRUSTED_PROXIES` to the VPC's range, so the gateway believes the ALB's
`X-Forwarded-For` entry and nothing a client adds in front of it. Check it two ways:

```sh
# the audit log's client address is yours, not an ALB address from the VPC range (needs audit.enabled in the
# seeded config, through extra_config_json):
curl -s "$BASE/api/audit-logs?limit=1" -H "Authorization: Bearer $RAIJU_ADMIN_TOKEN" | jq .
# forged X-Forwarded-For values buy no fresh allowance:
python3 tests/staging/dcr_flood.py --seconds 30
```

*Watch:* the target group's health (`aws elbv2 describe-target-health`), the task's `healthStatus` (the
container check runs `raiju -healthcheck`), the log group's start-up lines (no warning about the bind address or a
missing setup token).

*Pass:* the redirect, `/health` and `/ready` as shown; 401 before the first admin; the first admin made with the
setup token and `smoke.setup_token_closed_after_first_admin` passing afterwards; every check of `run.py` passing;
the audit log showing the operator's own address; `dcr_flood` with `registered_201` within one address's allowance.
*Fail:* a 502 or 504 from the ALB (idle timeout or health check), the ALB's address in the audit log, a forged
address escaping the registration limit, any `FAIL`.

**Teardown:** keep the stack for the next steps; delete `admin-token` at the end.

## (c) A real identity provider

**Prerequisites:** (b) done; an Okta developer org and a Microsoft Entra developer tenant; `public_url` served with a
real certificate (SSO cookies are `Secure` behind TLS). The gateway's SSO settings are the `oidc` and
`scim_config` blocks (docs/config-reference.md); pass them through `extra_config_json` with secrets as `env.NAME`
(add the secret ARNs to `provider_secret_arns`), apply, and reseed with `SEED_FORCE=1`.

Okta: an OIDC web app with sign-in redirect `https://raiju-staging.example.com/api/oidc/callback`, grant types
authorization code and refresh token, scopes `openid profile email groups offline_access`; a SCIM 2.0 app pointed
at `https://raiju-staging.example.com/scim/v2` with the provisioning token from
`POST /api/scim/provisioning-token`; an API token for directory sync.

```json
{"scim_config": {"enabled": true, "provider": "okta", "config": {
   "issuerUrl": "https://dev-123456.okta.com/oauth2/default", "clientId": "0oa...", "clientSecret": "env.OKTA_CLIENT_SECRET",
   "apiToken": "env.OKTA_API_TOKEN", "enableBulkSync": true, "bulkSyncInterval": "15m",
   "rolesField": "groups", "attributeRoleMappings": [{"attribute": "groups", "value": "raiju-admins", "role": "admin"}]}},
 "oidc": {"session_ttl_seconds": 300, "scopes": ["openid", "profile", "email", "groups", "offline_access"]}}
```

Entra: an app registration with the web redirect above, a client secret, the Graph application permissions
`User.Read.All` and `Group.Read.All` (admin consent) for directory sync, and an enterprise app with provisioning
to the SCIM URL; `"provider": "entra"` with `tenantId`, `clientId`, `clientSecret` (and `appIdUri` if tokens carry
it).

Walk through, in a browser with its developer tools open, for each IdP:

1. **SSO through the ALB.** Open `https://raiju-staging.example.com/api/oidc/login`. The 302 sets the state cookie
   (`Secure`, `HttpOnly`, `SameSite=Lax`); sign in at the IdP; the callback lands back on the dashboard signed in.
   Then start a login in one browser and paste its IdP callback URL into another: it must answer 401 ("not
   started in this browser").
2. **SCIM push.** Assign a user and a group to the SCIM app; within a minute `GET /api/users` lists the user with
   `source: "scim"`; deactivate the user in the IdP and the user is disabled; remove the assignment and the user
   is gone.
3. **Directory sync.** `POST /api/scim/provision/sync` (or wait for `bulkSyncInterval`): users of the directory
   appear with `source: "directory"`; `GET /api/scim/provision/status` shows the last run without errors.
4. **Session refresh.** With `session_ttl_seconds: 300`, stay idle for six minutes and reload the dashboard: it
   stays signed in (a silent refresh with the IdP's refresh token). Revoke the user's sessions in the IdP and wait
   another six minutes: the next request is 401.

*Watch:* the gateway log for OIDC and SCIM errors; the IdP's system log (Okta) or provisioning logs (Entra) for
rejected SCIM calls; the `raiju_oidc_state` metric family.

*Pass:* every numbered step behaves as written on both IdPs, through the ALB. *Fail:* a callback that loses the
state cookie (a 401 on the first sign-in), SCIM calls rejected, a directory sync error, a session that ends at its
TTL despite a refresh token, or one that outlives an IdP-side revocation by more than one TTL.

**Teardown:** unassign the apps and delete them in the IdPs; reseed the gateway without the blocks.

## (d) flock on EFS

**Prerequisites:** (b) done; `cluster = true` applied (three tasks, `start_service = true`) so that tasks share
`config.json` on EFS; two probe tasks for ECS Exec:

```sh
cd deploy/terraform/examples/staging
eval "$(terraform output -raw probe_command)"      # twice: probe A and probe B
aws ecs execute-command --cluster <cluster> --task <probe-A-id> --container probe --interactive --command sh
# inside each probe: fetch the kit (curl the raw files of the commit under test, or paste lock_probe.py and kit.py)
```

The data directory is `/data` in a probe (the access point's root, `/raiju` on the file system) and `/app/data` in
the gateway tasks; the gateway's lock file is `config.json.flock`.

1. **40 concurrent creates over the tasks.** From a host in the VPC, with each task's address
   (`aws ecs describe-tasks`, or resolve `terraform output -raw cluster_dns_name`):

   ```sh
   export RAIJU_NODE_URLS=http://10.0.1.11:8080,http://10.0.2.12:8080,http://10.0.1.13:8080
   python3 tests/staging/creates.py --all-nodes --creates 40 --settle 5
   ```

   *Pass:* `lost=0 lost_updates=0` with every create acknowledged (`--max-refused 0`).

2. **A process killed while it holds the lock.** In probe A: `python3 lock_probe.py hold /data/config.json.flock`.
   Start 40 creates (`creates.py --all-nodes`) in another shell: they wait. In probe B:
   `python3 lock_probe.py wait /data/config.json.flock --max-wait 5 &`. Then in probe A, `kill -9 <pid>`.
   *Pass:* `lock.wait` within a few seconds of the kill (the client sends the unlock as the process dies); the
   creates that were waiting complete (those that waited past 15 s answer 503 and nothing acknowledged is lost).

3. **A host that disappears while it holds the lock (the NFS lease).** In probe A hold the lock again, then cut
   probe A off from EFS without killing it: remove the NFS rule from its security group, or stop its task with
   `aws ecs stop-task` after detaching the network (any way that stops the client from sending the unlock). In
   probe B run `wait` with `--timeout 300`, and keep `creates.py` running in a loop.
   *Pass:* `waited_s` close to the server's lease (EFS documents about a minute; NFSv4's default is 90 s), creates
   answering 503 meanwhile and succeeding after, nothing lost. Record the measured lease: docs/operations.md quotes
   it unconfirmed. *Fail:* the lock never released (`wait` timed out), or saves lost.

4. **The bridge's stale rule under clock skew.** Measure each gateway host's clock against the file server
   (ECS tasks have no shell; measure the probe hosts, which share Fargate's time source):
   `python3 lock_probe.py skew /data`. Then from a probe, play a wave 25 process holding its lock directory:

   ```sh
   python3 lock_probe.py legacy /data/config.json --age 0  --base-url http://10.0.1.11:8080   # expect ok after 10 s
   python3 lock_probe.py legacy /data/config.json --age 6  --base-url http://10.0.1.11:8080   # ok after 4 s
   python3 lock_probe.py legacy /data/config.json --age -8 --base-url http://10.0.1.11:8080   # 503 after 15 s
   ```

   (`RAIJU_ADMIN_TOKEN` set in the probe.) `--age` moves the directory's time back (negative: forward, a writer
   whose clock runs ahead); `--gateway-skew` adds a measured skew to the expectation.
   *Pass:* each `lock.legacy_bridge` line passes, and the measured skew is under a second. *Fail:* a directory taken
   over earlier than 10 s minus the skew (a live old holder's lock would be broken), or the skew over a second
   (fix the time sync before running mixed versions).

*Watch:* the gateway logs for `locked by another process` and 503s; EFS `ClientConnections` and `PercentIOLimit`
in CloudWatch.

**Teardown:** stop the probe tasks (`aws ecs stop-task`), restore any security group rule you removed, `rmdir
/data/config.json.lock` if a run was interrupted.

## (e) Rolling upgrades

**Prerequisites:** (d) done, the cluster of three running the previous release; the candidate image pushed.

1. **Rolling (the module's default, 100% / 200%).** Start a writer loop and the bridge check, then upgrade:

   ```sh
   python3 tests/staging/creates.py --all-nodes --rounds 20 --settle 5 --max-refused 4 > rolling.log &
   terraform apply -var-file=staging.tfvars -var start_service=true -var cluster=true -var image=<candidate>
   aws ecs wait services-stable --cluster <cluster> --services <service>
   ```

   While old and new tasks overlap, point `bridge.py` at one old and one new task:
   `python3 tests/staging/bridge.py --old-url http://<old-task>:8080 --new-url http://<new-task>:8080 --rounds 3`.
   *Pass:* every round of `rolling.log` and every bridge round `lost=0 lost_updates=0`; the deployment finishes
   without the circuit breaker rolling it back; `/ready` stays 200 through the ALB (run
   `smoke_check.py` in a loop). *Fail:* any acknowledged write missing, a rollback, 5xx from the ALB beyond the
   draining tasks' own.

2. **Stop-first (MCP OAuth on, or an upgrade across lock protocols).** deploy/README.md requires stop-first when the
   MCP OAuth client registration format changes (waves 27 and 28) and from wave 25 straight past wave 27:

   ```sh
   terraform apply -var-file=staging.tfvars -var start_service=true -var cluster=true -var image=<candidate> \
     -var deployment_minimum_healthy_percent=0 -var deployment_maximum_percent=100
   ```

   Before it, register an MCP OAuth client and complete a grant with a real MCP client (register, authorize,
   approve with a virtual key, exchange the code), and begin a second consent without finishing it.
   *Pass:* after the upgrade the granted client's token still works at `/mcp`, the open consent link still opens,
   and `creates.py` loses nothing. *Fail:* `400 invalid_client` for a client that had a grant, or lost writes.

*Watch:* `aws ecs describe-services ... events`, the target group's draining targets, the gateway log's
`SIGTERM: draining` and `stopped after` lines (under the 35 s stop timeout).

**Teardown:** set the deployment percentages back to 100 and 200; keep the candidate running for (f).

## (f) Multi-node

**Prerequisites:** the cluster of three on the candidate; a host inside the VPC with `RAIJU_NODE_URLS` (each task's
private address and port 8080), `RAIJU_CLUSTER_SECRET` (`eval "$(terraform output -raw cluster_secret_command)"`),
`RAIJU_ADMIN_TOKEN`, `RAIJU_VKS`.

1. **Cloud Map.** `dig +short $(terraform output -raw cluster_dns_name)` from inside the VPC lists the three task
   addresses (and follows a task replacement within the record's 10 s TTL).
2. **The checks.**

   ```sh
   python3 tests/staging/cluster_check.py all --timeout 30
   ```

   `cluster.listener`: each node's port 7946 answers a signed request with a distinct node id and refuses unsigned
   and stale ones (401), port 8080 and the ALB answer 404, and exactly one node leads. `cluster.sync`: a key
   created on node 1, updated on node 2 and deleted on node 3 reaches every node (the seconds are printed).
   `cluster.logs`: a chat sent to each node is readable from every node. `cluster.counters`: a rate limit of 6
   requests spread over the nodes, then the next request on every node is 429.
3. **A partition and the rejoin.** Start the watch, then cut one task off from the others for two minutes and
   restore it:

   ```sh
   python3 tests/staging/cluster_check.py watch --duration 15m --every 5 --probe-every 30 | tee partition.log &
   # cut node 3 off: give its ENI a security group without the self-referencing 7946 rule (it keeps EFS and the ALB)
   aws ec2 modify-network-interface-attribute --network-interface-id <eni-of-node-3> --groups <sg-without-7946>
   sleep 120
   aws ec2 modify-network-interface-attribute --network-interface-id <eni-of-node-3> --groups <service-sg>
   ```

   *Watch:* the timeline: node 3 drops out of the others' view and may elect itself (`3:c*`), probes from node 3
   reach fewer nodes; after the restore one leader again and probes reach 3/3. The gateway logs for peer errors.
   *Pass:* `PASS cluster.watch` (converged at the end, the last probe reached every node), and afterwards
   `cluster_check.py all` passes again; counters did not reset (the rate limit is still exhausted for the key used
   before the partition). *Fail:* no convergence within a minute of the restore, a probe that never reaches node 3,
   writes made during the partition missing afterwards.

**Teardown:** restore the security groups if the watch was interrupted; then [destroy the stack](#teardown).

## From GitHub Actions

`.github/workflows/staging.yml` runs `tests/staging/run.py` with the inputs `base_url`, `checks` (as `run.py
--checks`), `soak_duration` and `runner`. It never runs on push or pull request, and the job does not start
without a base URL. Create a GitHub environment named `staging` (Settings, Environments; add required reviewers to
gate runs) with:

- secrets: `RAIJU_ADMIN_TOKEN`, `RAIJU_VKS`, and as needed `RAIJU_CLUSTER_SECRET`, `RAIJU_METRICS_TOKEN`,
  `RAIJU_SETUP_TOKEN`;
- variables: `RAIJU_MODEL`, `RAIJU_SMOKE_MODELS`, and as needed `RAIJU_NODE_URLS`, `RAIJU_OLD_URL`,
  `RAIJU_NEW_URL`, `RAIJU_RSS_CMD`, `RAIJU_RSS_METRIC`.

Then Actions, Staging validation, Run workflow. GitHub-hosted runners reach only the ALB (add their address range
to `ingress_cidr_blocks`, or use a self-hosted runner) and stop after six hours: run the 24-hour soak, the cluster
checks and the bridge from a self-hosted runner inside the VPC (`runner` input) or from an operator host. Results
are uploaded as the `staging-results` artifact and summarised on the run page.
