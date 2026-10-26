variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  description = "Prefix for every resource. Keep it short (ALB names allow 32 characters)."
  type        = string
  default     = "raiju-stg"
}

variable "owner" {
  description = "Who to ask about this stack (an email or a team), written to the owner tag."
  type        = string
}

variable "ttl_hours" {
  description = "How long the stack is meant to live: the expires_at tag is the creation time plus this. Nothing deletes it on its own; a sweeper (or you) runs terraform destroy (docs/staging-validation.md, Teardown)."
  type        = number
  default     = 48

  validation {
    condition     = var.ttl_hours >= 1 && var.ttl_hours <= 168
    error_message = "ttl_hours is between 1 and 168 (a week): this stack is throwaway."
  }
}

variable "vpc_id" {
  description = "A sandbox VPC with public subnets (the ALB) and private subnets with NAT (the tasks)."
  type        = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "task_subnet_ids" {
  description = "Private subnets for the tasks and the EFS mount targets (one per Availability Zone)."
  type        = list(string)
}

variable "image" {
  description = "The Raiju image under test, in ECR (the release candidate)."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for the staging host name (the IdP checks need real TLS)."
  type        = string
}

variable "public_url" {
  description = "https:// URL clients use (a DNS name pointing at the ALB that the certificate covers). The MCP OAuth issuer and the IdP redirect URIs are built from it."
  type        = string

  validation {
    condition     = can(regex("^https://[^/]+$", var.public_url))
    error_message = "public_url is https://host, without a path or trailing slash."
  }
}

variable "ingress_cidr_blocks" {
  description = "Who may reach the ALB: the operator's address and the CI runner's (and the IdP's SCIM egress ranges for step (c))."
  type        = list(string)
}

variable "cluster" {
  description = "Run three tasks as one Raiju cluster (Cloud Map discovery, config.json shared on EFS, the cluster listener on 7946). false runs one task."
  type        = bool
  default     = false
}

variable "start_service" {
  description = "false keeps the service at 0 tasks: apply once with false, run the seed task (output seed_command) to write config.json on EFS, then apply with true."
  type        = bool
  default     = false
}

variable "deployment_minimum_healthy_percent" {
  description = "Passed to the module (step (e): 100 for a rolling upgrade, 0 for stop-first)."
  type        = number
  default     = 100
}

variable "deployment_maximum_percent" {
  type    = number
  default = 200
}

variable "cpu" {
  type    = number
  default = 256
}

variable "memory" {
  description = "Task memory in MiB: 512 is the chart's and the module's limit, the one the soak (step (a)) must hold."
  type        = number
  default     = 512
}

variable "workers" {
  type    = number
  default = 1
}

variable "provider_secret_arns" {
  description = "Provider keys: environment variable name to Secrets Manager or SSM ARN, for example { OPENAI_API_KEY = \"arn:...\" }."
  type        = map(string)
  default     = {}
}

variable "providers_from_env" {
  description = "Providers written into the seeded config.json: provider name to the environment variable holding its key (a key of provider_secret_arns)."
  type        = map(string)
  default     = { openai = "OPENAI_API_KEY" }
}

variable "mcp_oauth" {
  description = "Turn on the MCP authorization server (client.mcp_server_auth_mode \"both\") so the registration flood check (tests/staging/dcr_flood.py) has something to hit."
  type        = bool
  default     = true
}

variable "extra_config_json" {
  description = "JSON merged over the seeded config.json's top level (for example the oidc and scim_config blocks of step (c)). Keep secrets out: use env.NAME and secret_arns."
  type        = string
  default     = "{}"
}

variable "seed_image" {
  description = "Image of the one-off seed and probe tasks (needs python3 and a shell)."
  type        = string
  default     = "public.ecr.aws/docker/library/python:3.13-slim"
}
