output "alb_dns_name" {
  description = "DNS name of the load balancer."
  value       = aws_lb.this.dns_name
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.this.name
}

output "cluster_arn" {
  description = "ARN of the cluster the service runs in."
  value       = local.cluster_arn
}

output "task_definition_arn" {
  description = "ARN of the task definition."
  value       = aws_ecs_task_definition.this.arn
}

output "log_group_name" {
  description = "CloudWatch log group for the container."
  value       = aws_cloudwatch_log_group.this.name
}

output "target_group_arn" {
  description = "ARN of the ALB target group."
  value       = aws_lb_target_group.this.arn
}

output "service_security_group_id" {
  description = "Security group of the tasks. Allow it on the EFS mount targets when EFS is used."
  value       = aws_security_group.service.id
}

output "cluster_dns_name" {
  description = "With cluster_enabled: the Cloud Map name that lists the tasks, for config.json's cluster.discovery.dns_names."
  value       = local.cluster_dns_name
}
