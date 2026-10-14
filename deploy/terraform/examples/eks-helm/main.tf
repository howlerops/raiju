terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.12"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "cluster_name" {
  description = "Existing EKS cluster."
  type        = string
}

variable "image_repository" {
  description = "Image repository the cluster can pull from, for example a private ECR repository."
  type        = string
}

variable "image_tag" {
  type    = string
  default = "0.1.0"
}

variable "existing_secret_name" {
  description = "Secret with the provider keys, created before apply: kubectl -n raiju create secret generic raiju-keys --from-literal=OPENAI_API_KEY=..."
  type        = string
  default     = "raiju-keys"
}

variable "replicas" {
  type    = number
  default = 2
}

variable "ingress_host" {
  description = "Host name for the Ingress. Null creates no Ingress; use kubectl port-forward instead."
  type        = string
  default     = null
}

variable "ingress_class_name" {
  type    = string
  default = null
}

data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

data "aws_eks_cluster_auth" "this" {
  name = var.cluster_name
}

provider "aws" {
  region = var.region
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.this.token
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.this.token
  }
}

module "raiju" {
  source = "../../modules/helm"

  namespace        = "raiju"
  image_repository = var.image_repository
  image_tag        = var.image_tag
  replicas         = var.replicas
  workers          = 2

  # config.json uses env.NAME references. The Secret must hold every NAME the
  # config refers to (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY here).
  config_json          = file("${path.module}/../../../config.example.json")
  existing_secret_name = var.existing_secret_name

  ingress_host       = var.ingress_host
  ingress_class_name = var.ingress_class_name
}

output "release_name" {
  value = module.raiju.release_name
}

output "service_name" {
  value = module.raiju.service_name
}

output "namespace" {
  value = module.raiju.namespace
}
