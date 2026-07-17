# terraform/modules/eventbridge/main.tf
#
# FIXED vs previous version:
#   - The old rule matched EVERY alarm in the account. Combined with an
#     undimensioned Lambda error alarm this created an infinite loop: the
#     platform's own errors triggered the platform, which errored, which...
#   - Now the rule matches ONLY alarms with the "watch-" prefix. Convention:
#       {project}-{env}-watch-*    -> monitored workloads -> AI workflow
#       {project}-{env}-selfmon-*  -> the platform itself  -> email only
#   - The duplicate copy of this rule in the monitoring module was deleted.
#   - role_arn is a dedicated EventBridge role (previously this reused the
#     Step Functions execution role — wrong trust relationship).

locals {
  prefix = "${var.project_name}-${var.environment}"
}

# ── RULE 1: WATCHED-WORKLOAD ALARMS -> AI OPS WORKFLOW ───────────────────────

resource "aws_cloudwatch_event_rule" "watch_alarm_to_workflow" {
  name        = "${local.prefix}-watch-alarm-trigger"
  description = "Routes 'watch-' prefixed CloudWatch ALARMs to the AI Ops workflow. selfmon- alarms are excluded by design."

  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
    detail = {
      state     = { value = ["ALARM"] }
      alarmName = [{ prefix = "${local.prefix}-watch-" }]
    }
  })
}

resource "aws_cloudwatch_event_target" "alarm_to_step_functions" {
  rule      = aws_cloudwatch_event_rule.watch_alarm_to_workflow.name
  target_id = "StartAIOpsWorkflow"
  arn       = var.step_functions_arn
  role_arn  = var.eventbridge_role_arn

  # Resilience: if StartExecution fails (throttle, outage), retry then park
  # the event in a DLQ instead of losing the incident.
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 5
  }
  dead_letter_config {
    arn = aws_sqs_queue.events_dlq.arn
  }
}



resource "aws_sqs_queue" "events_dlq" {
  name                      = "${local.prefix}-events-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}


resource "aws_sqs_queue_policy" "events_dlq" {
  queue_url = aws_sqs_queue.events_dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.events_dlq.arn
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.watch_alarm_to_workflow.arn }
      }
    }]
  })
}

# ── RULE 2: DAILY COST REPORT ────────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "daily_cost_report" {
  name                = "${local.prefix}-daily-cost-report"
  description         = "Triggers daily AI cost analysis at 8am UTC"
  schedule_expression = "cron(0 8 * * ? *)"
}

resource "aws_cloudwatch_event_target" "cost_reporter" {
  rule      = aws_cloudwatch_event_rule.daily_cost_report.name
  target_id = "TriggerCostReporter"
  arn       = var.cost_reporter_lambda_arn
}

resource "aws_lambda_permission" "eventbridge_cost" {
  statement_id  = "AllowEventBridgeDailyCost"
  action        = "lambda:InvokeFunction"
  function_name = var.cost_reporter_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_cost_report.arn
}
