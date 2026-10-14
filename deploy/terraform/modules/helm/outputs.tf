output "release_name" {
  description = "Helm release name."
  value       = helm_release.raiju.name
}

output "namespace" {
  description = "Namespace the release is installed in."
  value       = var.namespace
}

output "service_name" {
  description = "Name of the Kubernetes Service (the chart's fullname, which is the release name)."
  value       = var.release_name
}

output "ingress_host" {
  description = "Ingress host, or null when no Ingress was created."
  value       = var.ingress_host
}
