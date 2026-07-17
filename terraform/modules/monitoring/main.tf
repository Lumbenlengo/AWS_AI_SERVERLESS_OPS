# terraform/modules/monitoring/main.tf
#
# Self-monitoring for the platform itself.
#
# FIXED vs previous version:
#   1. The Lambda error alarm had NO dimensions — it summed errors across every
#      Lambda in the account, including the analyser itself, creating a
#      feedback loop (analyser errors -> alarm -> workflow -> analyser -> ...).
#      Now: one dimensioned alarm per platform function.
#   2. Alarm names use the "selfmon-" prefix. Only "watch-" alarms trigger the
#      AI workflow (see eventbridge module), so the platform never analyses
#      its own failures in a loop — selfmon alarms go to SNS/email only.
#   3. The duplicate alarm->StepFunctions EventBridge rule (and its duplicate
#      IAM role) that lived in this module is REMOVED. One rule, one place.
#   4. SNS topic moved to root to break the module dependency cycle.

locals {
  prefix             = "${var.project_name}-${var.environment}"
  platform_functions = ["anomaly-analyser", "runbook-assistant", "cost-reporter", "remediator"]
}

# ── PER-FUNCTION ERROR ANOMALY ALARMS (selfmon — email only, no AI loop) ─────

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = toset(local.platform_functions)

  alarm_name          = "${local.prefix}-selfmon-${each.key}-errors"
  comparison_operator = "GreaterThanUpperThreshold"
  evaluation_periods  = 2
  threshold_metric_id = "e1"
  treat_missing_data  = "notBreaching"
  alarm_description   = "Platform self-monitoring: ${each.key} error rate is anomalously high"
  alarm_actions       = [var.sns_topic_arn]
  ok_actions          = [var.sns_topic_arn]

  metric_query {
    id          = "m1"
    return_data = true
    metric {
      metric_name = "Errors"
      namespace   = "AWS/Lambda"
      period      = 120
      stat        = "Sum"
      dimensions  = { FunctionName = "${local.prefix}-${each.key}" }
    }
  }

  metric_query {
    id          = "e1"
    expression  = "ANOMALY_DETECTION_BAND(m1, 2)"
    label       = "Errors (expected range)"
    return_data = true
  }
}

# ── STEP FUNCTIONS FAILURE ALARM (selfmon) ───────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "sfn_failures" {
  alarm_name          = "${local.prefix}-selfmon-sfn-execution-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_description   = "One or more AI Ops workflow executions failed"
  alarm_actions       = [var.sns_topic_arn]

  dimensions = { StateMachineArn = var.step_functions_arn }
}

# ── DASHBOARD ────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "ai_ops" {
  dashboard_name = "${local.prefix}-ai-ops"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 2
        properties = {
          markdown = "# AI Ops Serverless Platform — ${var.environment}\n**Lambda health · Step Functions executions · API traffic** — selfmon alarms alert by email; `watch-` alarms trigger the AI remediation workflow"
        }
      },
      {
        type = "metric", x = 0, y = 2, width = 8, height = 6
        properties = {
          title = "Lambda invocations", view = "timeSeries", region = var.aws_region, period = 300
          metrics = [for f in local.platform_functions :
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.prefix}-${f}"]
          ]
        }
      },
      {
        type = "metric", x = 8, y = 2, width = 8, height = 6
        properties = {
          title = "Lambda errors", view = "timeSeries", region = var.aws_region, period = 300
          metrics = [for f in local.platform_functions :
            ["AWS/Lambda", "Errors", "FunctionName", "${local.prefix}-${f}"]
          ]
        }
      },
      {
        type = "metric", x = 16, y = 2, width = 8, height = 6
        properties = {
          title = "Lambda p95 duration (ms)", view = "timeSeries", region = var.aws_region, period = 300
          metrics = [for f in local.platform_functions :
            ["AWS/Lambda", "Duration", "FunctionName", "${local.prefix}-${f}", { stat = "p95" }]
          ]
        }
      },
      {
        type = "metric", x = 0, y = 8, width = 12, height = 6
        properties = {
          title = "AI Ops workflow executions", view = "timeSeries", region = var.aws_region, period = 300
          metrics = [
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", var.step_functions_arn],
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.step_functions_arn],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", var.step_functions_arn]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 8, width = 12, height = 6
        properties = {
          title = "Runbook API", view = "timeSeries", region = var.aws_region, period = 300
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiName", "${local.prefix}-runbook-api"],
            ["AWS/ApiGateway", "4XXError", "ApiName", "${local.prefix}-runbook-api"],
            ["AWS/ApiGateway", "5XXError", "ApiName", "${local.prefix}-runbook-api"],
            ["AWS/ApiGateway", "Latency", "ApiName", "${local.prefix}-runbook-api", { stat = "p95" }]
          ]
        }
      }
    ]
  })
}
