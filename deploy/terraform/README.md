# Terraform for Raiju

Two modules and three examples. Both modules take the image and the provider
keys as inputs. Neither builds the image or creates the registry.

| Path | What it does |
|---|---|
| `modules/helm` | Installs the chart in `deploy/helm/raiju` with `helm_release`. Optionally creates the namespace, a provider-key Secret and an Ingress. |
| `modules/aws-ecs` | ECS on Fargate behind an ALB: cluster (optional), task definition, service, security groups, target group, listeners, log group, IAM roles. |
| `examples/kind` | Local cluster. Uses the image loaded with `kind load`. |
| `examples/eks-helm` | Existing EKS cluster, existing `raiju-keys` Secret. |
| `examples/ecs` | Existing VPC; provider keys from Secrets Manager. |

Requirements: Terraform >= 1.5. Providers: `helm ~> 2.12`, `kubernetes ~> 2.30`,
`aws ~> 5.0`.

## Helm module

```hcl
module "raiju" {
  source = "./deploy/terraform/modules/helm"

  namespace        = "raiju"
  image_repository = "registry.example.com/raiju"
  image_tag        = "0.1.0"
  replicas         = 2
  workers          = 2

  config_json          = file("config.json")   # Bifrost format, refers to env.NAME
  existing_secret_name = "raiju-keys"          # preferred
  # provider_secrets = { OPENAI_API_KEY = var.openai_api_key }   # state holds the value

  ingress_host = "gateway.example.com"         # optional
}
```

Outputs: `release_name`, `namespace`, `service_name`, `ingress_host`.

The caller configures the `helm` and `kubernetes` providers. The module does not
configure them.

## ECS module

```hcl
module "raiju" {
  source = "./deploy/terraform/modules/aws-ecs"

  vpc_id            = "vpc-..."
  public_subnet_ids = ["subnet-...", "subnet-..."]
  task_subnet_ids   = ["subnet-...", "subnet-..."]   # private, with NAT
  image             = "123456789012.dkr.ecr.us-east-1.amazonaws.com/raiju:0.1.0"
  certificate_arn   = "arn:aws:acm:us-east-1:123456789012:certificate/..."

  ingress_cidr_blocks = ["10.0.0.0/8"] # required: who may reach the ALB

  secret_arns = {
    OPENAI_API_KEY      = "arn:aws:secretsmanager:us-east-1:123456789012:secret:raiju/openai"
    BIFROST_SETUP_TOKEN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:raiju/setup"
  }
}
```

`ingress_cidr_blocks` has no default, and the module serves HTTPS only: set
`certificate_arn`, or `allow_plain_http = true` to serve plain HTTP on purpose.
The management API is locked until an admin exists: give the tasks a
`BIFROST_SETUP_TOKEN` (or `setup_token` in a mounted config), create the first
admin with it, then remove it if you like.

Outputs: `alb_dns_name`, `service_name`, `cluster_arn`, `task_definition_arn`,
`log_group_name`, `target_group_arn`, `service_security_group_id`, `cluster_dns_name`.

The root filesystem is read-only (`readonly_root_filesystem`), and two volumes are
writable: `/app/data` (the EFS file system when `efs_file_system_id` is set, else the
task's ephemeral storage) and `/tmp` (ephemeral: the workers' share folder). Raiju
writes `/app/data` on every management API change (`config.json`, `config.json.bak`),
and keeps the MCP OAuth signing key and grants, flows in flight and, when on, the
request and audit logs there. Without EFS all of that, the first admin included, is
lost when the task stops: give the tasks an EFS volume to keep it.

The container runs `-app-dir /app/data -host 0.0.0.0 -port 8080 -workers N`
(the image's CMD, with `-workers`; the binary itself binds 127.0.0.1 unless told otherwise). The
target group checks `GET /ready` (`health_check_path`), the container's own health check runs
`raiju -healthcheck` (`GET /health`), and `stopTimeout` is 35 s, above the SIGTERM drain.

## Config and secrets

- Provider keys go in as environment variables. `secret_arns` maps each name to
  a Secrets Manager or SSM ARN, which ECS injects. Raiju builds providers from
  well-known variables (`OPENAI_API_KEY`, ...) when no config file exists, so
  ECS needs no config file.
- A Bedrock key with no credentials of its own signs with the task role (ECS container
  credentials, the AWS SDK's default chain): add the Bedrock permissions to it.
- To use a `config.json`, set `efs_file_system_id` and `efs_access_point_id`. The
  file system is mounted read-write at `/app/data`. Put `config.json` on it first,
  or let the first start build providers from the environment and save the file
  on the first API change. The access point must make its root directory writable
  by the image's user (uid and gid 65532), for example with `posix_user` set to
  them, and the EFS mount targets must allow the `service_security_group_id`. The
  ECS module does not create the file system or the access point.

## Several tasks

`desired_count` is 1 by default, and above 1 needs `cluster_enabled = true`
(terraform plan fails otherwise): without a Raiju cluster each task enforces
budgets and rate limits alone, so every limit is multiplied by the task count, and
each keeps its own config. A cluster needs:

- `efs_file_system_id` and `efs_access_point_id`: the tasks share `config.json`
  (`config_sync: "file"`). Give each task its own log folder or turn the log store
  off, as with a shared volume in the chart (deploy/README.md). A deployment starts
  the new tasks before the old ones stop (`deployment_minimum_healthy_percent` 100,
  `deployment_maximum_percent` 200), so two versions write `config.json` for a
  while: safe when both lock it the same way (deploy/README.md, "Upgrading on a
  shared volume"). For an upgrade across lock protocols set 0 and 100 for that
  deployment.
- `cluster_secret_arn`: a Secrets Manager or SSM ARN of a secret of at least 32
  bytes (`openssl rand -hex 32`; a shorter one stops the tasks at start), injected
  as `RAIJU_CLUSTER_SECRET`.
- The cluster block in `config.json`. The module registers each task in a Cloud
  Map private DNS namespace (`<name>.local` in `vpc_id`, or
  `service_discovery_namespace_id` and `service_discovery_namespace_name`) and lets
  the tasks reach each other on `cluster_port` (7946, the cluster listener that
  serves the peer routes off the ALB's port); output `cluster_dns_name` is the
  name Raiju's DNS discovery lists:

```json
{
  "cluster": {
    "enabled": true,
    "secret": "env.RAIJU_CLUSTER_SECRET",
    "config_sync": "file",
    "listen_port": 7946,
    "discovery": { "enabled": true, "type": "dns", "dns_names": ["raiju.raiju.local"] }
  }
}
```

```hcl
module "raiju" {
  # ... as above
  desired_count       = 3
  cluster_enabled     = true
  efs_file_system_id  = "fs-..."
  efs_access_point_id = "fsap-..."
  cluster_secret_arn  = "arn:aws:secretsmanager:us-east-1:123456789012:secret:raiju/cluster"
}
```

## Validate

Run from `deploy/terraform`:

```sh
terraform fmt -check -recursive
for d in examples/*; do (cd "$d" && terraform init -backend=false && terraform validate); done
(cd modules/aws-ecs && terraform init -backend=false && terraform test)   # Terraform 1.7+, a mocked AWS provider
```

`TERRAFORM=$(which terraform) python3 -m unittest tests/test_deploy.py` runs the
module's `terraform test` too.

## Limits

- `validate` checks syntax and types only, and `terraform test` plans against a
  mocked AWS provider. Nothing was applied: no cluster, no AWS account, so the
  Cloud Map discovery and EFS permissions are not proven on AWS.
- The chart keeps `config` in a ConfigMap, not a Secret, so the module passes
  config through the chart's values. Keep keys out of it: use `env.NAME`.
- Changes to the Secret named by `existing_secret_name` do not roll the pods.
  Run `kubectl rollout restart deploy/<release>`.
- Helm merges map values into the chart defaults. The module nulls the default
  Anthropic and Gemini providers when `config_json` does not list them. Other
  default map values (for example `resources.requests.cpu`) cannot be removed.
- The chart has no `env` input, so the only Secret it injects is the one
  named in `existing_secret_name` or `provider_secrets`.
- The chart has no Ingress template. The module creates one when `ingress_host`
  is set.
- ECS: the ARNs are `arn:aws:` (not GovCloud or China partitions). A customer KMS
  key on a secret needs `kms:Decrypt` on the execution role, which the module
  does not add.
- ECS: `readonlyRootFilesystem` defaults to true, as in the chart. Not exercised
  on Fargate.
- Helm and ECS: no HEALTHCHECK, because the image has no shell or curl. Probes
  come from Kubernetes and from the ALB.
