# terraform/modules/mission_control/main.tf
#
# The mission_control: one Lambda serving both the frontend (single HTML page)
# and the JSON APIs, exposed via a Lambda Function URL (HTTPS, no API Gateway
# needed — Function URLs are free beyond the Lambda invocation cost itself).
#
# Auth: a random key generated here and stored in Secrets Manager. The console
# frontend asks for it once and keeps it in sessionStorage; every /api/* call
# sends it as `x-console-key`. This is a pragmatic solo-project trade-off,
# documented in the README — production would put Cognito or IAM auth in
# front of the Function URL instead.
#
# IAM: its own role, least privilege —
#   - states:ListExecutions / GetExecutionHistory / SendTaskSuccess,
#     scoped to THIS state machine only
#   - lambda:InvokeFunction on the runbook assistant ONLY (read-only proxy)
#   - ce:GetCostAndUsage (Cost Explorer has no resource-level permissions)
#   - it cannot touch ECS, ASG, or SNS — it has no remediation power itself;
#     it only relays the human's decision to Step Functions, same as the
#     CLI `send-task-success` command would.

data "aws_caller_identity" "current" {}

locals {
  prefix = "${var.project_name}-${var.environment}"
}

resource "random_password" "console_key" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "console_key" {
  name                    = "${var.project_name}/${var.environment}/ops-console/key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "console_key" {
  secret_id     = aws_secretsmanager_secret.console_key.id
  secret_string = random_password.console_key.result
}

# ── PACKAGE ──────────────────────────────────────────────────────────────────

data "archive_file" "src" {
  type        = "zip"
  source_dir  = "${var.functions_path}/mission_control"
  output_path = "${path.module}/builds/mission_control.zip"
}

resource "aws_cloudwatch_log_group" "console" {
  name              = "/aws/lambda/${local.prefix}-ops-console"
  retention_in_days = 14
}

# ── IAM ──────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "console" {
  name = "${local.prefix}-ops-console-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "console" {
  name = "ops-console-permissions"
  role = aws_iam_role.console.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "StepFunctionsReadAndApproveThisMachineOnly"
        Effect = "Allow"
        Action = [
          "states:ListExecutions",
          "states:GetExecutionHistory",
          "states:SendTaskSuccess",
          "states:SendTaskFailure"
        ]
        Resource = [
          var.step_functions_arn,
          "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:execution:${local.prefix}-ai-ops-workflow:*"
        ]
      },
      {
        Sid      = "InvokeRunbookAssistantOnly"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = var.runbook_assistant_lambda_arn
      },
      {
        Sid      = "CostExplorerRead"
        Effect   = "Allow"
        Action   = ["ce:GetCostAndUsage"]
        Resource = "*" # Cost Explorer does not support resource-level permissions
      },
      {
        Sid      = "ReadOwnConsoleKey"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.console_key.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "console_logs" {
  role       = aws_iam_role.console.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ── LAMBDA + FUNCTION URL ─────────────────────────────────────────────────────

resource "aws_lambda_function" "console" {
  function_name    = "${local.prefix}-ops-console"
  role             = aws_iam_role.console.arn
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.src.output_path
  source_code_hash = data.archive_file.src.output_base64sha256
  timeout          = 15
  memory_size      = 256

  environment {
    variables = {
      AWS_REGION_NAME    = var.aws_region
      ENVIRONMENT        = var.environment
      STATE_MACHINE_ARN  = var.step_functions_arn
      RUNBOOK_LAMBDA_ARN = var.runbook_assistant_lambda_arn
      CONSOLE_KEY        = random_password.console_key.result
    }
  }

  tracing_config { mode = "Active" }

  depends_on = [aws_cloudwatch_log_group.console]
}

resource "aws_lambda_function_url" "console" {
  function_name      = aws_lambda_function.console.function_name
  authorization_type = "NONE" # app-level auth via x-console-key instead

  cors {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type", "x-console-key"]
  }
}