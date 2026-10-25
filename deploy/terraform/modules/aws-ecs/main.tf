data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

# the VPC's CIDR block: the default trusted_proxies (the ALB's addresses are in it)
data "aws_vpc" "this" {
  id = var.vpc_id
}

locals {
  cluster_arn = var.cluster_arn != null ? var.cluster_arn : one(aws_ecs_cluster.this[*].arn)
  efs_enabled = var.efs_file_system_id != null

  # Raiju clustering (cluster_enabled): the tasks find each other through a Cloud Map DNS name
  # (discovery type "dns") and share config.json on the EFS volume (config_sync "file").
  namespace_id     = var.cluster_enabled ? (var.service_discovery_namespace_id != null ? var.service_discovery_namespace_id : one(aws_service_discovery_private_dns_namespace.this[*].id)) : null
  namespace_name   = var.service_discovery_namespace_id != null ? var.service_discovery_namespace_name : "${var.name}.local"
  cluster_dns_name = var.cluster_enabled ? "${var.name}.${local.namespace_name}" : null
  cluster_secrets  = var.cluster_enabled && var.cluster_secret_arn != null ? { RAIJU_CLUSTER_SECRET = var.cluster_secret_arn } : {}
  all_secrets      = merge(var.secret_arns, local.cluster_secrets)

  # Same flags as the image's CMD, with -workers added. The image's ENTRYPOINT
  # is the raiju binary, so this list replaces the CMD only.
  command = concat(
    ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", tostring(var.port)],
    ["-workers", tostring(var.workers)],
  )

  # The ALB forwards each client's address in X-Forwarded-For: Raiju believes it from the VPC's range (the ALB's
  # addresses) unless trusted_proxies says otherwise. An explicit RAIJU_TRUSTED_PROXIES in environment wins.
  trusted_proxies = var.trusted_proxies != null ? var.trusted_proxies : [data.aws_vpc.this.cidr_block]
  environment = merge(
    length(local.trusted_proxies) > 0 ? { RAIJU_TRUSTED_PROXIES = join(",", local.trusted_proxies) } : {},
    var.environment,
  )

  secrets_manager_arns = [for arn in values(local.all_secrets) : arn if can(regex(":secretsmanager:", arn))]
  ssm_arns             = [for arn in values(local.all_secrets) : arn if can(regex(":ssm:", arn))]
}

# Cluster

resource "aws_ecs_cluster" "this" {
  count = var.cluster_arn == null ? 1 : 0

  name = var.name
  tags = var.tags
}

# Logs

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# IAM: execution role (pulls the image, reads secrets) and task role (the app)

data "aws_iam_policy_document" "assume_ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  count = length(local.all_secrets) > 0 ? 1 : 0

  dynamic "statement" {
    for_each = length(local.secrets_manager_arns) > 0 ? [1] : []
    content {
      actions   = ["secretsmanager:GetSecretValue"]
      resources = local.secrets_manager_arns
    }
  }

  dynamic "statement" {
    for_each = length(local.ssm_arns) > 0 ? [1] : []
    content {
      actions   = ["ssm:GetParameters"]
      resources = local.ssm_arns
    }
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  count = length(local.all_secrets) > 0 ? 1 : 0

  name   = "${var.name}-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets[0].json
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
  tags               = var.tags
}

data "aws_iam_policy_document" "task_efs" {
  count = local.efs_enabled ? 1 : 0

  # the data volume is written to: config.json on every API change, the MCP OAuth state, the logs
  statement {
    actions = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
    resources = [
      "arn:aws:elasticfilesystem:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:file-system/${var.efs_file_system_id}",
    ]
  }
}

resource "aws_iam_role_policy" "task_efs" {
  count = local.efs_enabled ? 1 : 0

  name   = "${var.name}-efs"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_efs[0].json
}

# Networking: ALB accepts from ingress_cidr_blocks, tasks accept only from the ALB

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "Raiju load balancer"
  vpc_id      = var.vpc_id
  tags        = var.tags

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidr_blocks
  }

  dynamic "ingress" {
    for_each = var.certificate_arn == null ? [] : [1]
    content {
      description = "HTTPS"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = var.ingress_cidr_blocks
    }
  }

  egress {
    description = "To tasks and health checks"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name        = "${var.name}-service"
  description = "Raiju tasks"
  vpc_id      = var.vpc_id
  tags        = var.tags

  ingress {
    description     = "From the load balancer"
    from_port       = var.port
    to_port         = var.port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  dynamic "ingress" {
    for_each = var.cluster_enabled ? [1] : []
    content {
      description = "Raiju cluster peers (cluster.listen_port)"
      from_port   = var.cluster_port
      to_port     = var.cluster_port
      protocol    = "tcp"
      self        = true
    }
  }

  egress {
    description = "Upstream providers and EFS"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Load balancer

resource "aws_lb" "this" {
  name                       = var.name
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.public_subnet_ids
  drop_invalid_header_fields = true
  # below Raiju's server.idle_timeout_seconds (60), so the ALB never reuses a connection the task is closing
  idle_timeout = var.alb_idle_timeout
  tags         = var.tags
}

resource "aws_lb_target_group" "this" {
  name                 = var.name
  port                 = var.port
  protocol             = "HTTP"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  deregistration_delay = 30
  tags                 = var.tags

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  lifecycle {
    precondition {
      condition     = var.certificate_arn != null || var.allow_plain_http
      error_message = "Set certificate_arn to serve HTTPS, or allow_plain_http = true to serve plain HTTP on purpose."
    }
  }

  default_action {
    type             = var.certificate_arn == null ? "forward" : "redirect"
    target_group_arn = var.certificate_arn == null ? aws_lb_target_group.this.arn : null

    dynamic "redirect" {
      for_each = var.certificate_arn == null ? [] : [1]
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count = var.certificate_arn == null ? 0 : 1

  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# Cluster discovery: a Cloud Map A record per task, which Raiju's DNS discovery lists

resource "aws_service_discovery_private_dns_namespace" "this" {
  count = var.cluster_enabled && var.service_discovery_namespace_id == null ? 1 : 0

  name = "${var.name}.local"
  vpc  = var.vpc_id
  tags = var.tags
}

resource "aws_service_discovery_service" "this" {
  count = var.cluster_enabled ? 1 : 0

  name = var.name
  tags = var.tags

  dns_config {
    namespace_id   = local.namespace_id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

# Task definition and service

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.cpu)
  memory                   = tostring(var.memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  tags                     = var.tags

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  # /app/data: the EFS file system when one is given (kept across tasks), else the task's own ephemeral
  # storage (lost with the task). Either way it is writable: Raiju saves config.json on every API change,
  # and keeps the MCP OAuth signing key, flows in flight and the request log there.
  dynamic "volume" {
    for_each = local.efs_enabled ? [] : [1]
    content {
      name = "data"
    }
  }

  # /tmp: the workers' share folder (/tmp/raiju-<pid>-<random>) and temporary files, under a read-only root
  volume {
    name = "tmp"
  }

  dynamic "volume" {
    for_each = local.efs_enabled ? [1] : []
    content {
      name = "data"
      efs_volume_configuration {
        file_system_id     = var.efs_file_system_id
        transit_encryption = "ENABLED"
        authorization_config {
          access_point_id = var.efs_access_point_id
          iam             = "ENABLED"
        }
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = var.name
      image     = var.image
      essential = true
      command   = local.command
      portMappings = concat(
        [{ name = "http", containerPort = var.port, hostPort = var.port, protocol = "tcp" }],
        var.cluster_enabled ? [{ name = "cluster", containerPort = var.cluster_port, hostPort = var.cluster_port, protocol = "tcp" }] : [],
      )
      # the binary probes itself (the image has no curl); /health is liveness
      healthCheck = {
        command     = ["CMD", "/usr/local/bin/raiju", "-healthcheck", "-port", tostring(var.port)]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 15
      }
      # SIGTERM drains for up to server.shutdown_grace_seconds (25 by default) plus about 5 s of flushing
      stopTimeout = 35

      readonlyRootFilesystem = var.readonly_root_filesystem
      environment            = [for k, v in local.environment : { name = k, value = v }]
      secrets                = [for k, v in local.all_secrets : { name = k, valueFrom = v }]
      mountPoints = [
        { sourceVolume = "data", containerPath = "/app/data", readOnly = false },
        { sourceVolume = "tmp", containerPath = "/tmp", readOnly = false },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "raiju"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "this" {
  name                               = var.name
  cluster                            = local.cluster_arn
  task_definition                    = aws_ecs_task_definition.this.arn
  desired_count                      = var.desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  health_check_grace_period_seconds  = 30
  deployment_minimum_healthy_percent = var.deployment_minimum_healthy_percent
  deployment_maximum_percent         = var.deployment_maximum_percent
  tags                               = var.tags

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.task_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = var.name
    container_port   = var.port
  }

  dynamic "service_registries" {
    for_each = var.cluster_enabled ? [1] : []
    content {
      registry_arn = aws_service_discovery_service.this[0].arn
    }
  }

  lifecycle {
    # each task alone enforces its own budgets, rate limits and config: more than one needs a Raiju cluster
    precondition {
      condition     = var.desired_count <= 1 || var.cluster_enabled
      error_message = "desired_count above 1 needs cluster_enabled = true: without a Raiju cluster each task enforces budgets and rate limits alone (every limit is multiplied by the task count) and keeps its own config."
    }
    precondition {
      condition     = !var.cluster_enabled || (local.efs_enabled && var.cluster_secret_arn != null)
      error_message = "cluster_enabled needs efs_file_system_id (the tasks share config.json, config_sync \"file\") and cluster_secret_arn (the cluster secret, injected as RAIJU_CLUSTER_SECRET)."
    }
  }

  depends_on = [aws_lb_listener.http, aws_lb_listener.https]
}
