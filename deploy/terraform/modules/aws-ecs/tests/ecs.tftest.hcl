# terraform test (Terraform 1.7 or later), against a mocked AWS provider: no account needed.
# Run from deploy/terraform/modules/aws-ecs: terraform init -backend=false && terraform test

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
    defaults = { cidr_block = "10.20.0.0/16" }
  }
}

variables {
  vpc_id              = "vpc-0example"
  public_subnet_ids   = ["subnet-0a", "subnet-0b"]
  task_subnet_ids     = ["subnet-0c", "subnet-0d"]
  image               = "123456789012.dkr.ecr.us-east-1.amazonaws.com/raiju:0.1.0"
  certificate_arn     = "arn:aws:acm:us-east-1:123456789012:certificate/example"
  ingress_cidr_blocks = ["10.0.0.0/8"]
}

run "one_task_with_writable_ephemeral_data_and_tmp" {
  command = plan

  assert {
    condition     = aws_ecs_service.this.desired_count == 1
    error_message = "the default is one task"
  }
  assert {
    condition     = aws_ecs_service.this.deployment_minimum_healthy_percent == 100 && aws_ecs_service.this.deployment_maximum_percent == 200
    error_message = "the default deployment starts the new task before the old one stops (both lock config.json the same way)"
  }
  assert {
    condition = alltrue([
      for m in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].mountPoints : m.readOnly == false
    ])
    error_message = "every mount is writable"
  }
  assert {
    condition     = toset([for m in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].mountPoints : m.containerPath]) == toset(["/app/data", "/tmp"])
    error_message = "/app/data and /tmp are mounted"
  }
  assert {
    condition     = jsondecode(aws_ecs_task_definition.this.container_definitions)[0].readonlyRootFilesystem == true
    error_message = "the root filesystem stays read-only"
  }
  assert {
    condition     = length(aws_service_discovery_service.this) == 0
    error_message = "no discovery without a cluster"
  }
  assert {
    condition     = aws_lb.this.idle_timeout < 60
    error_message = "the ALB closes idle connections before Raiju does (server.idle_timeout_seconds 60)"
  }
  assert {
    condition     = contains([for e in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].environment : "${e.name}=${e.value}"], "RAIJU_TRUSTED_PROXIES=10.20.0.0/16")
    error_message = "the ALB's forwarding headers are believed from the VPC's range by default"
  }
}

run "trusted_proxies_can_be_named_or_turned_off" {
  command = plan

  variables {
    trusted_proxies = []
  }

  assert {
    condition     = !contains([for e in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].environment : e.name], "RAIJU_TRUSTED_PROXIES")
    error_message = "[] trusts no proxy"
  }
}

run "trusted_proxies_named" {
  command = plan

  variables {
    trusted_proxies = ["10.20.1.0/24", "10.20.2.0/24"]
  }

  assert {
    condition     = contains([for e in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].environment : "${e.name}=${e.value}"], "RAIJU_TRUSTED_PROXIES=10.20.1.0/24,10.20.2.0/24")
    error_message = "the named ranges are passed on"
  }
}

run "efs_is_mounted_read_write" {
  command = plan

  variables {
    efs_file_system_id  = "fs-0example"
    efs_access_point_id = "fsap-0example"
  }

  assert {
    condition     = one([for v in aws_ecs_task_definition.this.volume : v if v.name == "data"]).efs_volume_configuration[0].file_system_id == "fs-0example"
    error_message = "/app/data is the EFS volume"
  }
  assert {
    condition     = one([for m in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].mountPoints : m if m.containerPath == "/app/data"]).readOnly == false
    error_message = "the EFS volume is writable"
  }
}

run "several_tasks_need_a_cluster" {
  command = plan

  variables {
    desired_count = 2
  }

  expect_failures = [aws_ecs_service.this]
}

run "a_cluster_needs_efs_and_a_secret" {
  command = plan

  variables {
    desired_count   = 2
    cluster_enabled = true
  }

  expect_failures = [aws_ecs_service.this]
}

run "rolling_by_default_stop_first_on_request" {
  command = plan

  variables {
    efs_file_system_id                 = "fs-0example"
    efs_access_point_id                = "fsap-0example"
    deployment_minimum_healthy_percent = 0
    deployment_maximum_percent         = 100
  }

  assert {
    condition     = aws_ecs_service.this.deployment_minimum_healthy_percent == 0 && aws_ecs_service.this.deployment_maximum_percent == 100
    error_message = "a deployment can stop the old tasks before the new ones start (an upgrade across lock protocols)"
  }
}

run "a_cluster_of_tasks" {
  command = plan

  variables {
    desired_count       = 3
    cluster_enabled     = true
    efs_file_system_id  = "fs-0example"
    efs_access_point_id = "fsap-0example"
    cluster_secret_arn  = "arn:aws:secretsmanager:us-east-1:123456789012:secret:raiju/cluster"
  }

  assert {
    condition     = aws_ecs_service.this.desired_count == 3
    error_message = "three tasks"
  }
  assert {
    condition     = contains([for s in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].secrets : s.name], "RAIJU_CLUSTER_SECRET")
    error_message = "the cluster secret is injected"
  }
  assert {
    condition     = length(aws_service_discovery_service.this) == 1 && output.cluster_dns_name == "raiju.raiju.local"
    error_message = "the tasks are listed under a Cloud Map name"
  }
  assert {
    condition     = contains([for p in jsondecode(aws_ecs_task_definition.this.container_definitions)[0].portMappings : p.containerPort], 7946)
    error_message = "the cluster listener's port is mapped"
  }
}
