# terraform test (Terraform 1.7 or later) with mocked providers: no account needed.
# Run from deploy/terraform/examples/staging: terraform init -backend=false && terraform test

mock_provider "aws" {
  mock_data "aws_region" {
    defaults = { name = "us-east-1" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_vpc" {
    defaults = { cidr_block = "10.30.0.0/16" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:raiju-stg/example" }
  }
  mock_resource "aws_efs_file_system" {
    defaults = { arn = "arn:aws:elasticfilesystem:us-east-1:123456789012:file-system/fs-0example", id = "fs-0example" }
  }
  mock_resource "aws_efs_access_point" {
    defaults = { id = "fsap-0example" }
  }
  mock_resource "aws_ecs_task_definition" {
    defaults = { arn = "arn:aws:ecs:us-east-1:123456789012:task-definition/raiju-stg:1" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/raiju-stg-example" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/raiju-stg/0example" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/raiju-stg/0example" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:/ecs/raiju-stg" }
  }
  mock_resource "aws_ecs_cluster" {
    defaults = { arn = "arn:aws:ecs:us-east-1:123456789012:cluster/raiju-stg" }
  }
}

mock_provider "random" {}

mock_provider "time" {
  mock_resource "time_static" {
    defaults = { rfc3339 = "2026-10-26T00:00:00Z" }
  }
}

variables {
  owner               = "platform-team@example.com"
  vpc_id              = "vpc-0example"
  public_subnet_ids   = ["subnet-0a", "subnet-0b"]
  task_subnet_ids     = ["subnet-0c", "subnet-0d"]
  image               = "123456789012.dkr.ecr.us-east-1.amazonaws.com/raiju:rc"
  certificate_arn     = "arn:aws:acm:us-east-1:123456789012:certificate/example"
  public_url          = "https://raiju-staging.example.com"
  ingress_cidr_blocks = ["203.0.113.0/24"]
}

run "first_apply_starts_no_task" {
  command = apply

  assert {
    condition     = module.raiju.service_name == "raiju-stg" && length(aws_efs_mount_target.data) == 2
    error_message = "the module runs with an EFS mount target per task subnet"
  }
  assert {
    condition     = output.expires_at == "2026-10-28T00:00:00Z"
    error_message = "expires_at is the creation time plus ttl_hours (48)"
  }
  assert {
    condition     = aws_secretsmanager_secret.setup_token.recovery_window_in_days == 0 && aws_secretsmanager_secret.cluster_secret.recovery_window_in_days == 0
    error_message = "the secrets are deleted at once on destroy"
  }
  assert {
    condition     = !can(jsondecode(output.seeded_config).cluster)
    error_message = "one task: no cluster block"
  }
  assert {
    condition     = jsondecode(output.seeded_config).setup_token == "env.BIFROST_SETUP_TOKEN" && jsondecode(output.seeded_config).providers.openai.keys[0].value == "env.OPENAI_API_KEY"
    error_message = "the seeded config holds env.NAME references only"
  }
}

run "cluster_of_three" {
  command = plan

  variables {
    cluster       = true
    start_service = true
  }

  assert {
    condition     = module.raiju.cluster_dns_name == "raiju-stg.raiju-stg.local"
    error_message = "the module registers the tasks in Cloud Map"
  }
}

run "ttl_is_bounded" {
  command = plan

  variables {
    ttl_hours = 720
  }

  expect_failures = [var.ttl_hours]
}
