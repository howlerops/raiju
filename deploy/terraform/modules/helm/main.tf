locals {
  chart_path = abspath(coalesce(var.chart_path, "${path.module}/../../../helm/raiju"))

  # Helm merges user values into the chart defaults, so a provider that the
  # config leaves out would survive from the defaults. A null value removes the
  # key, which drops the default providers that are not listed here.
  cfg               = var.config_json == null ? null : jsondecode(var.config_json)
  cfg_providers     = local.cfg == null ? {} : try(local.cfg.providers, {})
  default_providers = ["openai", "anthropic", "gemini"]
  config_values = local.cfg == null ? null : merge(local.cfg, {
    providers = merge(
      { for p in local.default_providers : p => null if !contains(keys(local.cfg_providers), p) },
      local.cfg_providers,
    )
  })

  has_provider_secrets = nonsensitive(length(var.provider_secrets) > 0)
  create_secret        = local.has_provider_secrets && var.existing_secret_name == null
  secret_name = var.existing_secret_name != null ? var.existing_secret_name : one(
    kubernetes_secret_v1.providers[*].metadata[0].name
  )
  secret_keys_ok = alltrue([
    for k in nonsensitive(keys(var.provider_secrets)) : can(regex("^[A-Za-z_][A-Za-z0-9_]*$", k))
  ])

  values = merge(
    {
      # Service and Ingress names follow the release name.
      fullnameOverride = var.release_name
      replicaCount     = var.replicas
      workers          = var.workers
      port             = var.port
      image = {
        repository = var.image_repository
        tag        = var.image_tag
        pullPolicy = var.image_pull_policy
      }
      imagePullSecrets = [for s in var.image_pull_secrets : { name = s }]
      service = {
        type = var.service_type
        port = var.port
      }
      resources = var.resources
    },
    local.config_values == null ? {} : { config = local.config_values },
    local.secret_name == null ? {} : { existingSecret = local.secret_name },
  )
}

resource "kubernetes_namespace_v1" "this" {
  count = var.create_namespace ? 1 : 0

  metadata {
    name = var.namespace
  }
}

resource "kubernetes_secret_v1" "providers" {
  count = local.create_secret ? 1 : 0

  metadata {
    name      = "${var.release_name}-provider-keys"
    namespace = var.namespace
    labels = {
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  type = "Opaque"
  data = var.provider_secrets

  depends_on = [kubernetes_namespace_v1.this]
}

resource "helm_release" "raiju" {
  name             = var.release_name
  namespace        = var.namespace
  create_namespace = false
  chart            = local.chart_path
  values           = [yamlencode(local.values)]
  wait             = true
  timeout          = var.timeout

  depends_on = [kubernetes_namespace_v1.this, kubernetes_secret_v1.providers]

  lifecycle {
    precondition {
      condition     = !(var.existing_secret_name != null && local.has_provider_secrets)
      error_message = "Set either existing_secret_name or provider_secrets, not both."
    }
    precondition {
      condition     = local.secret_keys_ok
      error_message = "provider_secrets keys must be valid environment variable names."
    }
  }
}

resource "kubernetes_ingress_v1" "this" {
  count = var.ingress_host == null ? 0 : 1

  metadata {
    name        = var.release_name
    namespace   = var.namespace
    annotations = var.ingress_annotations
  }

  spec {
    ingress_class_name = var.ingress_class_name

    dynamic "tls" {
      for_each = var.ingress_tls_secret_name == null ? [] : [1]
      content {
        hosts       = [var.ingress_host]
        secret_name = var.ingress_tls_secret_name
      }
    }

    rule {
      host = var.ingress_host
      http {
        path {
          path      = "/"
          path_type = "Prefix"
          backend {
            service {
              name = var.release_name
              port {
                number = var.port
              }
            }
          }
        }
      }
    }
  }

  depends_on = [helm_release.raiju]
}
