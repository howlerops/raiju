variable "namespace" {
  description = "Namespace for the release."
  type        = string
  default     = "raiju"
}

variable "create_namespace" {
  description = "Create the namespace. Set false when it already exists."
  type        = bool
  default     = true
}

variable "release_name" {
  description = "Helm release name. Also passed as the chart's fullnameOverride, so the Service and Ingress are named after it."
  type        = string
  default     = "raiju"

  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$", var.release_name))
    error_message = "release_name must be a DNS label of at most 63 characters."
  }
}

variable "chart_path" {
  description = "Path to the chart. Null uses the repo's deploy/helm/raiju."
  type        = string
  default     = null
}

variable "image_repository" {
  description = "Image repository, for example registry.example.com/raiju."
  type        = string
}

variable "image_tag" {
  description = "Image tag. Empty means the chart's appVersion."
  type        = string
  default     = ""
}

variable "image_pull_policy" {
  description = "Image pull policy. Use Never for images loaded into a local cluster (kind)."
  type        = string
  default     = "IfNotPresent"

  validation {
    condition     = contains(["Always", "IfNotPresent", "Never"], var.image_pull_policy)
    error_message = "image_pull_policy must be Always, IfNotPresent or Never."
  }
}

variable "image_pull_secrets" {
  description = "Names of existing docker-registry Secrets for pulling the image."
  type        = list(string)
  default     = []
}

variable "replicas" {
  description = "Pod count (chart replicaCount). Each pod has its own budgets, rate limits and cache."
  type        = number
  default     = 1

  validation {
    condition     = var.replicas >= 1
    error_message = "replicas must be at least 1."
  }
}

variable "workers" {
  description = "Worker processes per pod (-workers)."
  type        = number
  default     = 1
}

variable "port" {
  description = "Port the gateway listens on in the pod and the Service port (chart port)."
  type        = number
  default     = 8080
}

variable "service_type" {
  description = "Kubernetes Service type."
  type        = string
  default     = "ClusterIP"

  validation {
    condition     = contains(["ClusterIP", "NodePort", "LoadBalancer"], var.service_type)
    error_message = "service_type must be ClusterIP, NodePort or LoadBalancer."
  }
}

variable "config_json" {
  description = <<-EOT
    Contents of config.json in Bifrost format, for example file("config.json").
    Null uses the chart's default config. Providers absent from this config are
    removed from the chart defaults, so only the providers you list are built.
    Keep keys out of the file: refer to them as "env.NAME" and set NAME in
    provider_secrets or in existing_secret_name.
  EOT
  type        = string
  default     = null

  validation {
    condition     = var.config_json == null ? true : can(jsondecode(var.config_json))
    error_message = "config_json must be valid JSON."
  }
}

variable "provider_secrets" {
  description = <<-EOT
    Map of environment variable name to value (for example OPENAI_API_KEY). The
    module stores them in a Secret that is injected with envFrom, so config's
    env.NAME references resolve. Values end up in Terraform state. Mutually
    exclusive with existing_secret_name.
  EOT
  type        = map(string)
  default     = {}
}

variable "existing_secret_name" {
  description = "Name of a Secret that already exists in the namespace, injected with envFrom. Preferred over provider_secrets."
  type        = string
  default     = null
}

variable "resources" {
  description = "Container resources (chart resources)."
  type = object({
    requests = optional(map(string), {})
    limits   = optional(map(string), {})
  })
  default = {
    requests = { cpu = "250m", memory = "64Mi" }
    limits   = { memory = "256Mi" }
  }
}

variable "ingress_host" {
  description = "Host name for an Ingress that routes to the Service. Null creates no Ingress."
  type        = string
  default     = null
}

variable "ingress_class_name" {
  description = "Ingress class name. Null uses the cluster default."
  type        = string
  default     = null
}

variable "ingress_annotations" {
  description = "Annotations for the Ingress."
  type        = map(string)
  default     = {}
}

variable "ingress_tls_secret_name" {
  description = "TLS Secret for ingress_host. Null serves plain HTTP."
  type        = string
  default     = null
}

variable "timeout" {
  description = "Seconds Helm waits for the release to become ready."
  type        = number
  default     = 300
}
