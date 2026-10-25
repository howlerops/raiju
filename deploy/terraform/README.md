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
`log_group_name`, `target_group_arn`, `service_security_group_id`.

The container runs `-app-dir /app/data -host 0.0.0.0 -port 8080 -workers N`
(the image's CMD, with `-workers`). Health check: `GET /health` on the target
group.

## Config and secrets

- Provider keys go in as environment variables. `secret_arns` maps each name to
  a Secrets Manager or SSM ARN, which ECS injects. Raiju builds providers from
  well-known variables (`OPENAI_API_KEY`, ...) when no config file exists, so
  ECS needs no config file.
- To use a `config.json`, set `efs_file_system_id` and `efs_access_point_id`. The
  file system is mounted read-only at `/app/data`. Put `config.json` on it first.
  The ECS module does not create the file system or the access point.

## Validate

Run from `deploy/terraform`:

```sh
terraform fmt -check -recursive
for d in examples/*; do (cd "$d" && terraform init -backend=false && terraform validate); done
```

## Limits

- `validate` checks syntax and types only. Nothing was applied: no cluster, no
  AWS account.
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
