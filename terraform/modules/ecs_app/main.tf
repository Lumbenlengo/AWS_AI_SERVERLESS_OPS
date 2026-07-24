# terraform/modules/ecs_demo_app/main.tf
#
# The workload the platform monitors and remediates: a Fargate service running
# the Orders API demo app, tagged AIOpsManaged=true (the remediator's IAM role
# can ONLY touch resources with this tag), plus the "watch-" alarm that feeds
# the AI Ops workflow.
#
# NETWORK ARCHITECTURE (updated from the original public-IP demo setup):
#   Internet
#      |
#   ALB (public subnets, port 80)         <- aws_lb.app
#      |
#   Target Group -> Task (PRIVATE subnets, port 8080, no public IP)
#      |
#   NAT Gateway (public subnet)  -> Internet Gateway -> internet
#      (outbound only: ECR image pulls, CloudWatch, Anthropic API calls)
#



data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_internet_gateway" "default" {
  filter {
    name   = "attachment.vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  prefix = "${var.project_name}-${var.environment}"
  name   = "${local.prefix}-demo-app"

  # First two subnets become "private" (task lives here, no public IP).
  # Next two stay "public" (ALB + NAT Gateway live here).
  private_subnet_ids = slice(data.aws_subnets.default.ids, 0, 2)
  public_subnet_ids  = slice(data.aws_subnets.default.ids, 2, 4)
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

# ── NAT GATEWAY (outbound internet access for the private subnets) ──────────

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${local.name}-nat-eip" }
}

resource "aws_nat_gateway" "app" {
  allocation_id = aws_eip.nat.id
  subnet_id     = local.public_subnet_ids[0] # NAT must live in a PUBLIC subnet
  tags          = { Name = "${local.name}-nat" }
}

# ── PRIVATE ROUTE TABLE (task subnets route out via NAT, not the IGW) ───────

resource "aws_route_table" "private" {
  vpc_id = data.aws_vpc.default.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.app.id
  }

  tags = { Name = "${local.name}-private-rt" }
}

resource "aws_route_table_association" "private" {
  count          = length(local.private_subnet_ids)
  subnet_id      = local.private_subnet_ids[count.index]
  route_table_id = aws_route_table.private.id
}

# ── SECURITY GROUPS ──────────────────────────────────────────────────────────

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb-sg"
  description = "ALB: public HTTP from admin CIDR"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP from admin CIDR"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  egress {
    description = "To the task on its container port"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app" {
  name        = "${local.name}-sg"
  description = "Demo app task: only reachable from the ALB, not the internet"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "App port, ALB only"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound (via NAT Gateway: ECR pull, CloudWatch, Anthropic API)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── ALB ───────────────────────────────────────────────────────────────────────

resource "aws_lb" "app" {
  name               = "${local.name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = local.public_subnet_ids
}

resource "aws_lb_target_group" "app" {
  name        = "${local.name}-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default.id
  target_type = "ip" # required for awsvpc network mode (Fargate)

  health_check {
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
    matcher             = "200"
  }
}

resource "aws_lb_listener" "app" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
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
    subnets          = local.private_subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false # now behind the ALB, in a private subnet
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "orders-api"
    container_port   = 8080
  }

  tags = { AIOpsManaged = "true" }

  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.app]
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