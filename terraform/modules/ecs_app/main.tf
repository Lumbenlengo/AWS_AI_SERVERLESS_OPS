# terraform/modules/ecs_demo_app/main.tf
#
# The workload the platform monitors and remediates: a Fargate service running
# the Orders API demo app, tagged AIOpsManaged=true (the remediator's IAM role
# can ONLY touch resources with this tag), plus the "watch-" alarm that feeds
# the AI Ops workflow.
#
# Design notes (deliberate trade-offs for a ~$9/month demo):
#   - Uses the default VPC + public IP instead of an ALB. An ALB alone costs
#     ~$18/month; for a single-task demo, a security-grouped public IP is the
#     honest cheap option. Production would use ALB + private subnets.
#   - desired_count = 1, Fargate Spot for cost.
#
# After `terraform apply`, build and push the image:
#   aws ecr get-login-password | docker login --username AWS --password-stdin <repo>
#   docker build -t <repo>:latest demo-app/ && docker push <repo>:latest

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  prefix = "${var.project_name}-${var.environment}"
  name   = "${local.prefix}-demo-app"
}

# ── ECR ───────────────────────────────────────────────────────────────────────

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration { scan_on_push = true }
}

# ── LOGS ─────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 7
}

# ── IAM: EXECUTION + TASK ROLES ──────────────────────────────────────────────

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task" {
  name = "emit-error-metric"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "PutDemoAppMetrics"
      Effect   = "Allow"
      Action   = ["cloudwatch:PutMetricData"]
      Resource = "*"
      Condition = {
        StringEquals = { "cloudwatch:namespace" = "DemoApp" }
      }
    }]
  })
}

# ── NETWORK ──────────────────────────────────────────────────────────────────

resource "aws_security_group" "app" {
  name        = "${local.name}-sg"
  description = "Demo app: HTTP from admin CIDR only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "App port from admin CIDR"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  egress {
    description = "All outbound (ECR pull, CloudWatch)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── ECS ──────────────────────────────────────────────────────────────────────

resource "aws_ecs_cluster" "demo" {
  name = "${local.prefix}-demo"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name         = "orders-api"
    image        = "${aws_ecr_repository.app.repository_url}:latest"
    essential    = true
    portMappings = [{ containerPort = 8080, protocol = "tcp" }]
    environment = [
      { name = "SERVICE_NAME", value = "orders-api" },
      { name = "ENVIRONMENT", value = var.environment },
      { name = "METRIC_NAMESPACE", value = "DemoApp" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "orders-api"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name            = local.name
  cluster         = aws_ecs_cluster.demo.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }

  # THE tag: the remediator's IAM policy only permits ecs:UpdateService on
  # resources carrying AIOpsManaged=true. Untagged services are untouchable.
  tags = { AIOpsManaged = "true" }

  lifecycle {
    ignore_changes = [task_definition] # image pushes redeploy via forceNewDeployment
  }
}

# ── THE "WATCH-" ALARM (this is what feeds the AI Ops workflow) ──────────────

resource "aws_cloudwatch_metric_alarm" "app_errors" {
  alarm_name          = "${local.prefix}-watch-demo-app-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "DemoApp"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_description   = "Orders API error rate is high — AI Ops workflow will analyse and propose remediation"

  dimensions = { Service = "orders-api" }
}