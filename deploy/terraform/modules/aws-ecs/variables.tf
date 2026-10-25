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
  description = "Number of tasks."
  type        = number
  default     = 2
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
  description = "Optional EFS file system mounted read-only at the -app-dir (/app/data) so config.json can be supplied from it. Null mounts nothing; providers then come from environment variables."
  type        = string
  default     = null
}

variable "efs_access_point_id" {
  description = "EFS access point for efs_file_system_id. Required when efs_file_system_id is set. The access point must expose the config directory as its root."
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

variable "health_check_path" {
  description = "ALB target group health check path."
  type        = string
  default     = "/health"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30
}
