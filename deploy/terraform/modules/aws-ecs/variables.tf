variable "name" {
  description = "Prefix for resource names. ALB and target group names allow 32 characters, so keep it short."
  type        = string
  default     = "raiju"

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,26}[a-z0-9])?$", var.name))
    error_message = "name must be 2 to 28 lowercase letters, digits or hyphens, not starting or ending with a hyphen."
  }
}

variable "tags" {
  description = "Tags for all resources that support them."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "VPC for the ALB, the target group and the tasks."
  type        = string
}

variable "public_subnet_ids" {
  description = "Subnets for the ALB. Use at least two Availability Zones."
  type        = list(string)
}

variable "task_subnet_ids" {
  description = "Subnets for the tasks. Private subnets need a NAT gateway so the tasks can reach the upstream providers."
  type        = list(string)
}

variable "ingress_cidr_blocks" {
  description = "CIDR blocks allowed to reach the ALB. Required: name the networks your clients come from. [\"0.0.0.0/0\"] opens the gateway to the internet, so say so explicitly if that is what you want."
  type        = list(string)

  validation {
    condition     = length(var.ingress_cidr_blocks) > 0
    error_message = "ingress_cidr_blocks must name at least one CIDR block."
  }
}

variable "certificate_arn" {
  description = "ACM certificate ARN. The ALB serves HTTPS on 443 and redirects HTTP to it. Required unless allow_plain_http is true."
  type        = string
  default     = null
}

variable "allow_plain_http" {
  description = "Serve plain HTTP on 80 when certificate_arn is null. Off by default: virtual keys, admin credentials and prompts would cross the network in clear text."
  type        = bool
  default     = false
}

variable "cluster_arn" {
  description = "ARN of an existing ECS cluster. Null creates one named after name."
  type        = string
  default     = null
}

variable "image" {
  description = "Image URI, for example 123456789012.dkr.ecr.us-east-1.amazonaws.com/raiju:0.1.0. The image must be linux and match cpu_architecture."
  type        = string
}

variable "cpu_architecture" {
  description = "CPU architecture of the image."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "cpu" {
  description = "Task CPU units. Fargate allows 256, 512, 1024, 2048 or 4096."
  type        = number
  default     = 256

  validation {
    condition     = contains([256, 512, 1024, 2048, 4096], var.cpu)
    error_message = "cpu must be one of 256, 512, 1024, 2048, 4096."
  }
}

variable "memory" {
  description = "Task memory in MiB. Must be a valid Fargate pairing with cpu."
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Number of tasks. Above 1 needs cluster_enabled: without a Raiju cluster each task enforces budgets and rate limits alone and keeps its own config."
  type        = number
  default     = 1
}

variable "deployment_minimum_healthy_percent" {
  description = "Lower limit of running tasks during a deployment, as a percentage of desired_count. The default (100, with deployment_maximum_percent 200) starts the new tasks before the old ones stop: with EFS, old and new versions then write one config.json at once. That is safe between releases that lock it the same way, and from wave 27 on with the wave 25 release too (flock plus its mkdir lock, docs/operations.md). For an upgrade from a release before wave 25 (no config lock), or from wave 25 straight to a release after wave 27, set 0 (and deployment_maximum_percent 100) for that deployment: the old tasks stop first."
  type        = number
  default     = 100

  validation {
    condition     = var.deployment_minimum_healthy_percent >= 0 && var.deployment_minimum_healthy_percent <= 100
    error_message = "deployment_minimum_healthy_percent is between 0 and 100."
  }
}

variable "deployment_maximum_percent" {
  description = "Upper limit of running tasks during a deployment, as a percentage of desired_count (see deployment_minimum_healthy_percent). 100 with a minimum of 0 never runs old and new tasks together."
  type        = number
  default     = 200

  validation {
    condition     = var.deployment_maximum_percent >= 100 && var.deployment_maximum_percent <= 200
    error_message = "deployment_maximum_percent is between 100 and 200."
  }
}

variable "cluster_enabled" {
  description = "Run the tasks as one Raiju cluster: a Cloud Map DNS name lists the tasks for discovery, the tasks may reach each other on port, and RAIJU_CLUSTER_SECRET is injected from cluster_secret_arn. Needs efs_file_system_id; config.json on it must hold the cluster block (see deploy/terraform/README.md)."
  type        = bool
  default     = false
}

variable "cluster_port" {
  description = "With cluster_enabled: the cluster listener's port (config.json cluster.listen_port, 7946 as in the chart). Only the tasks themselves may reach it; the ALB never forwards to it."
  type        = number
  default     = 7946
}

variable "cluster_secret_arn" {
  description = "Secrets Manager or SSM ARN of the cluster secret (at least 32 bytes, or the tasks refuse to start), injected as RAIJU_CLUSTER_SECRET (config.json: \"secret\": \"env.RAIJU_CLUSTER_SECRET\"). Required when cluster_enabled."
  type        = string
  default     = null

  validation {
    condition     = var.cluster_secret_arn == null || can(regex("^arn:[^:]+:(secretsmanager|ssm):", var.cluster_secret_arn))
    error_message = "cluster_secret_arn must be a Secrets Manager or SSM parameter ARN."
  }
}

variable "service_discovery_namespace_id" {
  description = "Existing Cloud Map private DNS namespace for cluster discovery. Null creates <name>.local in vpc_id when cluster_enabled."
  type        = string
  default     = null
}

variable "service_discovery_namespace_name" {
  description = "Name of service_discovery_namespace_id (for example internal.example), used for cluster_dns_name. Set it with service_discovery_namespace_id."
  type        = string
  default     = null
}

variable "port" {
  description = "Container port (-port) and target group port."
  type        = number
  default     = 8080
}

variable "workers" {
  description = "Worker processes per task (-workers). Each worker has its own budgets and rate limits."
  type        = number
  default     = 1
}

variable "environment" {
  description = "Plain environment variables for the container, for example settings that are not secret."
  type        = map(string)
  default     = {}
}

variable "secret_arns" {
  description = <<-EOT
    Map of environment variable name to the ARN of a Secrets Manager secret
    (arn:...:secretsmanager:...) or an SSM parameter (arn:...:ssm:...). Each
    value is injected into the container, so config's env.NAME references
    resolve. Add the KMS permissions yourself if the secret uses a customer key.
  EOT
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for arn in values(var.secret_arns) : can(regex("^arn:[^:]+:(secretsmanager|ssm):", arn))
    ])
    error_message = "secret_arns values must be Secrets Manager or SSM parameter ARNs."
  }
}

variable "efs_file_system_id" {
  description = "Optional EFS file system mounted read-write at the -app-dir (/app/data): config.json (saved on every API change), the MCP OAuth state and the logs are kept there across tasks. Null gives /app/data the task's ephemeral storage (lost when the task stops); providers then come from environment variables."
  type        = string
  default     = null
}

variable "efs_access_point_id" {
  description = "EFS access point for efs_file_system_id. Required when efs_file_system_id is set. The access point must expose the data directory as its root, writable by the image's user (uid and gid 65532: set its posix_user, or a root_directory creation_info owned by it)."
  type        = string
  default     = null

  validation {
    condition     = var.efs_file_system_id == null || var.efs_access_point_id != null
    error_message = "efs_access_point_id is required when efs_file_system_id is set."
  }
}

variable "readonly_root_filesystem" {
  description = "Mount the container root filesystem read-only, as the chart does."
  type        = bool
  default     = true
}

variable "alb_idle_timeout" {
  description = "ALB idle timeout in seconds. Keep it below Raiju's server.idle_timeout_seconds (60 by default): with equal timeouts the ALB can send a request on a connection the task is closing, which answers 502. A stream that sends nothing for this long is cut by the ALB."
  type        = number
  default     = 55
}

variable "health_check_path" {
  description = "ALB target group health check path. /ready answers 503 while a task drains or when a store that is on could not open; /health is liveness only."
  type        = string
  default     = "/ready"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30
}
