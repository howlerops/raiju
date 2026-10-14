terraform {
  required_version = ">= 1.5"

  required_providers {
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

variable "kubeconfig_path" {
  description = "kubeconfig written by kind."
  type        = string
  default     = "~/.kube/config"
}

variable "kube_context" {
  description = "Context of the kind cluster (kind-<cluster name>)."
  type        = string
  default     = "kind-raiju"
}

variable "openai_api_key" {
  description = "OpenAI API key. Stored in the cluster Secret and in Terraform state."
  type        = string
  sensitive   = true
}

provider "kubernetes" {
  config_path    = pathexpand(var.kubeconfig_path)
  config_context = var.kube_context
}

provider "helm" {
  kubernetes {
    config_path    = pathexpand(var.kubeconfig_path)
    config_context = var.kube_context
  }
}

# Build and load the image first:
#   docker build -t raiju:local .
#   kind create cluster --name raiju
#   kind load docker-image raiju:local --name raiju
module "raiju" {
  source = "../../modules/helm"

  namespace         = "raiju"
  image_repository  = "raiju"
  image_tag         = "local"
  image_pull_policy = "Never"
  replicas          = 1

  # Only OpenAI is configured. The module drops the chart's default Anthropic
  # and Gemini providers, so they are not built without keys.
  config_json = jsonencode({
    client = { enable_logging = true, drop_excess_requests = false }
    providers = {
      openai = {
        keys = [{ name = "openai-1", value = "env.OPENAI_API_KEY", models = [], weight = 1 }]
      }
    }
    cache = { enabled = false }
  })

  provider_secrets = {
    OPENAI_API_KEY = var.openai_api_key
  }
}

output "service_name" {
  description = "Service name. Reach it with: kubectl -n raiju port-forward svc/<name> 8080:8080"
  value       = module.raiju.service_name
}

output "namespace" {
  value = module.raiju.namespace
}
