output "alb_dns_name" {
  description = "Point public_url's DNS name at this (a CNAME or an alias record)."
  value       = module.raiju.alb_dns_name
}

output "base_url" {
  value = var.public_url
}

output "cluster_name" {
  value = module.raiju.cluster_arn
}

output "service_name" {
  value = module.raiju.service_name
}

output "log_group_name" {
  value = module.raiju.log_group_name
}

output "cluster_dns_name" {
  description = "With cluster = true: the Cloud Map name listing the tasks (resolve it inside the VPC for RAIJU_NODE_URLS)."
  value       = module.raiju.cluster_dns_name
}

output "expires_at" {
  value = local.tags.expires_at
}

output "setup_token_command" {
  description = "Prints the setup token (for the first admin, step (b))."
  value       = "aws secretsmanager get-secret-value --region ${var.region} --secret-id ${aws_secretsmanager_secret.setup_token.arn} --query SecretString --output text"
}

output "cluster_secret_command" {
  description = "Prints the cluster secret (RAIJU_CLUSTER_SECRET for tests/staging/cluster_check.py)."
  value       = "aws secretsmanager get-secret-value --region ${var.region} --secret-id ${aws_secretsmanager_secret.cluster_secret.arn} --query SecretString --output text"
}

output "seed_command" {
  description = "Runs the seed task: writes config.json on EFS unless one is there."
  value       = "aws ecs run-task --region ${var.region} --cluster ${module.raiju.cluster_arn} --launch-type FARGATE --task-definition ${aws_ecs_task_definition.tool["seed"].arn} --network-configuration '${local.run_task_network}'"
}

output "probe_command" {
  description = "Starts a probe task (python3, the volume at /data) for ECS Exec: aws ecs execute-command --interactive --command sh --task <id> --container probe."
  value       = "aws ecs run-task --region ${var.region} --cluster ${module.raiju.cluster_arn} --launch-type FARGATE --enable-execute-command --task-definition ${aws_ecs_task_definition.tool["probe"].arn} --network-configuration '${local.run_task_network}'"
}

output "seeded_config" {
  description = "The config.json the seed task writes (no secret values: env.NAME references)."
  value       = jsonencode(local.config)
}
