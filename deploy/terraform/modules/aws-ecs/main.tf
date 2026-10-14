data "aws_region" "current" {}

data "aws_caller_identity" "current" {}

locals {
  cluster_arn = var.cluster_arn != null ? var.cluster_arn : one(aws_ecs_cluster.this[*].arn)
  efs_enabled = var.efs_file_system_id != null

  # Same flags as the image's CMD, with -workers added. The image's ENTRYPOINT
  # is the raiju binary, so this list replaces the CMD only.
  command = concat(
    ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", tostring(var.port)],
    ["-workers", tostring(var.workers)],
  )

  secrets_manager_arns = [for arn in values(var.secret_arns) : arn if can(regex(":secretsmanager:", arn))]
  ssm_arns             = [for arn in values(var.secret_arns) : arn if can(regex(":ssm:", arn))]
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
  count = length(var.secret_arns) > 0 ? 1 : 0

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
  count = length(var.secret_arns) > 0 ? 1 : 0

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

  statement {
    actions = ["elasticfilesystem:ClientMount"]
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
  tags                       = var.tags
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

  dynamic "volume" {
    for_each = local.efs_enabled ? [1] : []
    content {
      name = "config"
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
      name         = var.name
      image        = var.image
      essential    = true
      command      = local.command
      portMappings = [{ name = "http", containerPort = var.port, hostPort = var.port, protocol = "tcp" }]

      readonlyRootFilesystem = var.readonly_root_filesystem
      environment            = [for k, v in var.environment : { name = k, value = v }]
      secrets                = [for k, v in var.secret_arns : { name = k, valueFrom = v }]
      mountPoints = local.efs_enabled ? [
        { sourceVolume = "config", containerPath = "/app/data", readOnly = true }
      ] : []

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
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
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

  depends_on = [aws_lb_listener.http, aws_lb_listener.https]
}
