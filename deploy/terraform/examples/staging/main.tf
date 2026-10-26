# A throwaway staging stack for docs/staging-validation.md: the aws-ecs module with an EFS volume, an ALB with TLS,
# a setup token and a cluster secret in Secrets Manager, one task or a three-task Raiju cluster, and one-off task
# definitions that seed config.json on EFS and probe the volume's locks. Every resource carries an expires_at tag.
#
#   terraform init && terraform apply -var-file=staging.tfvars                       # start_service = false
#   $(terraform output -raw seed_command)                                            # writes config.json on EFS
#   terraform apply -var-file=staging.tfvars -var start_service=true
#   ... the runbook's steps ...
#   terraform destroy -var-file=staging.tfvars                                       # Teardown: removes everything
#
# The secrets have no recovery window and the EFS file system is deleted with its data: nothing outlives a destroy.

provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

data "aws_vpc" "this" {
  id = var.vpc_id
}

# fixed at the first apply, so the expiry tag does not move on later plans
resource "time_static" "created" {}

locals {
  tags = {
    purpose    = "raiju-staging"
    owner      = var.owner
    ttl_hours  = tostring(var.ttl_hours)
    expires_at = timeadd(time_static.created.rfc3339, "${var.ttl_hours}h")
  }
  task_count = var.cluster ? 3 : 1

  providers = {
    for p, envname in var.providers_from_env : p => {
      keys = [{ name = "${p}-staging", value = "env.${envname}", models = [], weight = 1 }]
    }
  }
  # (through JSON text, so both branches of the conditional have one type)
  cluster_block = jsondecode(var.cluster ? jsonencode({
    cluster = {
      enabled     = true
      secret      = "env.RAIJU_CLUSTER_SECRET"
      config_sync = "file"
      listen_port = 7946
      log_reads   = true
      discovery   = { enabled = true, type = "dns", dns_names = [module.raiju.cluster_dns_name] }
    }
  }) : "{}")
  mcp_block = jsondecode(var.mcp_oauth ? jsonencode({
    mcp_server_auth_mode = "both"
    oauth2_server_config = { issuer_url = var.public_url }
  }) : "{}")
  # config.json as the seed task writes it: keys and secrets only as env.NAME references
  config = merge(
    {
      setup_token = "env.BIFROST_SETUP_TOKEN"
      client = merge({
        enable_logging            = true
        enforce_auth_on_inference = true
        allow_direct_keys         = false
        disable_content_logging   = true
        max_request_body_size_mb  = 100
      }, local.mcp_block)
      # each task keeps its own request log on its /tmp volume (a shared folder would mix the nodes' files)
      logs_store = { enabled = true, dir = "/tmp/raiju-logs", content_logging = false }
      providers  = local.providers
    },
    local.cluster_block,
    jsondecode(var.extra_config_json),
  )
}

# Secrets: the setup token opens /api until the first admin exists; the cluster secret signs the peer routes

resource "random_password" "setup_token" {
  length  = 40
  special = false
}

resource "random_password" "cluster_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "setup_token" {
  name                    = "${var.name}/setup-token"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "setup_token" {
  secret_id     = aws_secretsmanager_secret.setup_token.id
  secret_string = random_password.setup_token.result
}

resource "aws_secretsmanager_secret" "cluster_secret" {
  name                    = "${var.name}/cluster-secret"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "cluster_secret" {
  secret_id     = aws_secretsmanager_secret.cluster_secret.id
  secret_string = random_password.cluster_secret.result
}

# EFS: config.json, the MCP OAuth state and the sessions, shared by the tasks (the lock checks of step (d) run here)

resource "aws_efs_file_system" "data" {
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"
  tags             = { Name = "${var.name}-data" }
}

resource "aws_security_group" "efs" {
  name        = "${var.name}-efs"
  description = "NFS from the staging VPC"
  vpc_id      = var.vpc_id

  ingress {
    description = "NFS"
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.this.cidr_block]
  }
}

resource "aws_efs_mount_target" "data" {
  for_each = toset(var.task_subnet_ids)

  file_system_id  = aws_efs_file_system.data.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "data" {
  file_system_id = aws_efs_file_system.data.id

  # the image's user; config.json is written 0600 by it
  posix_user {
    uid = 65532
    gid = 65532
  }

  root_directory {
    path = "/raiju"
    creation_info {
      owner_uid   = 65532
      owner_gid   = 65532
      permissions = "0750"
    }
  }
}

# The gateway

module "raiju" {
  source = "../../modules/aws-ecs"

  name                = var.name
  tags                = local.tags
  vpc_id              = var.vpc_id
  public_subnet_ids   = var.public_subnet_ids
  task_subnet_ids     = var.task_subnet_ids
  image               = var.image
  certificate_arn     = var.certificate_arn
  ingress_cidr_blocks = var.ingress_cidr_blocks

  cpu           = var.cpu
  memory        = var.memory
  workers       = var.workers
  desired_count = var.start_service ? local.task_count : 0

  deployment_minimum_healthy_percent = var.deployment_minimum_healthy_percent
  deployment_maximum_percent         = var.deployment_maximum_percent

  efs_enabled         = true # the file system is made in this apply, so its id is unknown at plan time
  efs_file_system_id  = aws_efs_file_system.data.id
  efs_access_point_id = aws_efs_access_point.data.id

  cluster_enabled    = var.cluster
  cluster_secret_arn = var.cluster ? aws_secretsmanager_secret.cluster_secret.arn : null

  secret_arns = merge(var.provider_secret_arns, {
    BIFROST_SETUP_TOKEN = aws_secretsmanager_secret.setup_token.arn
  })

  depends_on = [aws_efs_mount_target.data, aws_secretsmanager_secret_version.setup_token, aws_secretsmanager_secret_version.cluster_secret]
}

# One-off tasks on the same volume: seed (writes config.json unless one exists; SEED_FORCE=1 replaces it) and probe
# (python3 with the volume at /data, for tests/staging/lock_probe.py over ECS Exec)

resource "aws_cloudwatch_log_group" "tools" {
  name              = "/ecs/${var.name}-tools"
  retention_in_days = 7
}

data "aws_iam_policy_document" "assume_ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "tools_execution" {
  name               = "${var.name}-tools-execution"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
}

resource "aws_iam_role_policy_attachment" "tools_execution" {
  role       = aws_iam_role.tools_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "tools_task" {
  statement {
    actions   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
    resources = [aws_efs_file_system.data.arn]
  }
  # ECS Exec into the probe task
  statement {
    actions   = ["ssmmessages:CreateControlChannel", "ssmmessages:CreateDataChannel", "ssmmessages:OpenControlChannel", "ssmmessages:OpenDataChannel"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "tools_task" {
  name               = "${var.name}-tools-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
}

resource "aws_iam_role_policy" "tools_task" {
  name   = "${var.name}-tools"
  role   = aws_iam_role.tools_task.id
  policy = data.aws_iam_policy_document.tools_task.json
}

locals {
  tools_volume = {
    name = "data"
    efs = {
      file_system_id  = aws_efs_file_system.data.id
      access_point_id = aws_efs_access_point.data.id
    }
  }
  seed_script = <<-EOT
    import os, sys
    p = "/data/config.json"
    if os.path.exists(p) and os.environ.get("SEED_FORCE") != "1":
        print("config.json exists; SEED_FORCE=1 replaces it"); sys.exit(0)
    fd = os.open(p + ".seed", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, os.environ["RAIJU_SEED_CONFIG"].encode()); os.fsync(fd); os.close(fd)
    os.replace(p + ".seed", p); print("wrote", p)
  EOT
}

resource "aws_ecs_task_definition" "tool" {
  for_each = {
    seed  = { command = ["python3", "-c", local.seed_script], env = [{ name = "RAIJU_SEED_CONFIG", value = jsonencode(local.config) }] }
    probe = { command = ["sleep", "86400"], env = [] }
  }

  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.tools_execution.arn
  task_role_arn            = aws_iam_role.tools_task.arn

  volume {
    name = local.tools_volume.name
    efs_volume_configuration {
      file_system_id     = local.tools_volume.efs.file_system_id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = local.tools_volume.efs.access_point_id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([{
    name        = each.key
    image       = var.seed_image
    essential   = true
    command     = each.value.command
    environment = each.value.env
    mountPoints = [{ sourceVolume = "data", containerPath = "/data", readOnly = false }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.tools.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = each.key
      }
    }
  }])
}

locals {
  run_task_network = "awsvpcConfiguration={subnets=[${join(",", var.task_subnet_ids)}],securityGroups=[${module.raiju.service_security_group_id}],assignPublicIp=DISABLED}"
}
