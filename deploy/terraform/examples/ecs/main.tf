terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  description = "Two or more public subnets for the ALB."
  type        = list(string)
}

variable "task_subnet_ids" {
  description = "Private subnets for the tasks (they need NAT for upstream providers)."
  type        = list(string)
}

variable "image" {
  description = "Image in ECR, for example 123456789012.dkr.ecr.us-east-1.amazonaws.com/raiju:0.1.0."
  type        = string
}

variable "provider_secret_arns" {
  description = "Environment variable name to Secrets Manager (or SSM) ARN, for example { OPENAI_API_KEY = \"arn:...\" }."
  type        = map(string)
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS."
  type        = string
}

variable "ingress_cidr_blocks" {
  description = "Networks allowed to reach the ALB, for example your office or VPN ranges."
  type        = list(string)
}

provider "aws" {
  region = var.region
}

module "raiju" {
  source = "../../modules/aws-ecs"

  name              = "raiju"
  vpc_id            = var.vpc_id
  public_subnet_ids = var.public_subnet_ids
  task_subnet_ids   = var.task_subnet_ids
  image             = var.image
  certificate_arn   = var.certificate_arn

  ingress_cidr_blocks = var.ingress_cidr_blocks

  cpu           = 512
  memory        = 1024
  desired_count = 2
  workers       = 1

  # Providers come from environment variables, which Raiju reads without a
  # config file. No file means the config is not mounted. Add a
  # BIFROST_SETUP_TOKEN secret to open /api until the first admin is created:
  # without an admin or a setup token the management API answers 403.
  secret_arns = var.provider_secret_arns
}

output "alb_dns_name" {
  value = module.raiju.alb_dns_name
}

output "service_name" {
  value = module.raiju.service_name
}
