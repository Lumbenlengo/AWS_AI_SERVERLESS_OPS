# terraform/modules/lambda/main.tf


locals {
  prefix = "${var.project_name}-${var.environment}"

  functions = {
    anomaly_analyser = {
      name    = "anomaly-analyser"
      timeout = 60
      env = {
        BEDROCK_MODEL_ID  = var.bedrock_model_id
        SLACK_WEBHOOK_URL = var.slack_webhook_url
        ANTHROPIC_API_KEY = var.anthropic_api_key
        SNS_TOPIC_ARN     = var.sns_topic_arn
        REMEDIATION_MAP   = jsonencode(var.remediation_map)
      }
    }
    runbook_assistant = {
      name    = "runbook-assistant"
      timeout = 60
      env = {
        BEDROCK_MODEL_ID     = var.bedrock_model_id
        RUNBOOKS_BUCKET_NAME = var.runbooks_bucket_name
      }
    }
    cost_reporter = {
      name    = "cost-reporter"
      timeout = 120
      env = {
        BEDROCK_MODEL_ID     = var.bedrock_model_id
        SLACK_WEBHOOK_URL    = var.slack_webhook_url
        SNS_TOPIC_ARN        = var.sns_topic_arn
        COST_ALERT_THRESHOLD = tostring(var.cost_alert_threshold)
      }
    }
    remediator = {
      name    = "remediator"
      timeout = 120
      env = {
        SNS_TOPIC_ARN = var.sns_topic_arn
      }
    }
  }
}

data "archive_file" "src" {
  for_each    = local.functions
  type        = "zip"
  source_dir  = "${var.functions_path}/${each.key}"
  output_path = "${path.module}/builds/${each.key}.zip"
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.prefix}-${each.value.name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${local.prefix}-${each.value.name}"
  role             = var.lambda_role_arns[each.key]
  handler          = "main.lambda_handler"
  runtime          = "python3.12"
  filename         = data.archive_file.src[each.key].output_path
  source_code_hash = data.archive_file.src[each.key].output_base64sha256
  timeout          = each.value.timeout
  memory_size      = 256

  environment {
    variables = merge(
      {
        AWS_REGION_NAME = var.aws_region # AWS_REGION is reserved by the runtime
        ENVIRONMENT     = var.environment
      },
      each.value.env
    )
  }

  tracing_config { mode = "Active" }

  depends_on = [aws_cloudwatch_log_group.fn]
}