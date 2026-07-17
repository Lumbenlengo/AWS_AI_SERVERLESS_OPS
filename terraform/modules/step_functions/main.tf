# terraform/modules/step_functions/main.tf
#
# The AI Ops orchestration workflow.
#
# Flow:
#   [Start]
#      │
#   [AI_Analysis]         ← Lambda calls Bedrock Claude
#      │
#   [Route_By_Urgency]    ← HIGH/CRITICAL → human gate, LOW → log and stop
#      │
#   [Notify_And_Wait]     ← Slack message + PAUSE (waitForTaskToken)
#      │                    costs $0 while waiting, no timeout
#   [Check_Approval]
#      ├── approved=true  → [Remediate] → [Workflow_Complete]
#      └── approved=false → [Rejected_By_Human]
#
# waitForTaskToken: the workflow pauses here. The Lambda sends a Slack message
# containing the task token. The human runs an AWS CLI command with that token
# to resume. No polling, no Lambda running while waiting.

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/states/${var.project_name}-${var.environment}-ai-ops"
  retention_in_days = 30
}

resource "aws_sfn_state_machine" "ai_ops" {
  name     = "${var.project_name}-${var.environment}-ai-ops-workflow"
  role_arn = var.sfn_role_arn
  type     = "STANDARD"

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  definition = jsonencode({
    Comment = "AI Ops: Detect → AI Analyse → Human Approval Gate → Remediate"
    StartAt = "AI_Analysis"

    States = {

      AI_Analysis = {
        Type     = "Task"
        Comment  = "Call anomaly_analyser Lambda — it calls Bedrock Claude and returns structured JSON"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.analyser_lambda_arn
          "Payload.$"  = "$"
        }
        ResultSelector = { "analysis.$" = "$.Payload" }
        ResultPath     = "$.ai_result"
        Retry = [{
          ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.TooManyRequestsException"]
          IntervalSeconds = 5
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "Analysis_Failed"
          ResultPath  = "$.error"
        }]
        Next = "Route_By_Urgency"
      }

      Route_By_Urgency = {
        Type    = "Choice"
        Comment = "HIGH and CRITICAL urgency goes to human approval. LOW/MEDIUM just logs."
        Choices = [
          {
            Variable     = "$.ai_result.analysis.urgency"
            StringEquals = "HIGH"
            Next         = "Notify_And_Wait"
          },
          {
            Variable     = "$.ai_result.analysis.urgency"
            StringEquals = "CRITICAL"
            Next         = "Notify_And_Wait"
          }
        ]
        Default = "Log_Low_Priority"
      }

      Log_Low_Priority = {
        Type    = "Pass"
        Comment = "Urgency is LOW or MEDIUM. Logged. No engineer paged."
        Result  = { outcome = "logged_no_action_required" }
        End     = true
      }

      Notify_And_Wait = {
        Type     = "Task"
        Comment  = "Send Slack message with taskToken and PAUSE. Zero cost while waiting."
        Resource = "arn:aws:states:::lambda:invoke.waitForTaskToken"
        Parameters = {
          FunctionName = var.analyser_lambda_arn
          Payload = {
            action        = "notify_and_wait"
            "taskToken.$" = "$$.Task.Token"
            "analysis.$"  = "$.ai_result.analysis"
            "alarm.$"     = "$.detail"
          }
        }
        HeartbeatSeconds = 86400
        ResultPath       = "$.approval"
        Catch = [{
          ErrorEquals = ["States.HeartbeatTimeout"]
          Next        = "Approval_Timeout"
          ResultPath  = "$.error"
        }]
        Next = "Check_Approval"
      }

      Check_Approval = {
        Type = "Choice"
        Choices = [{
          Variable      = "$.approval.approved"
          BooleanEquals = true
          Next          = "Remediate"
        }]
        Default = "Rejected_By_Human"
      }

      Remediate = {
        Type     = "Task"
        Comment  = "Human approved. Execute the fix."
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.remediator_lambda_arn
          Payload = {
            "action.$"   = "$.ai_result.analysis.recommended_action"
            "resource.$" = "$.ai_result.analysis.resource"
            "analysis.$" = "$.ai_result.analysis"
          }
        }
        ResultPath = "$.remediation"
        Retry = [{
          ErrorEquals     = ["Lambda.ServiceException"]
          IntervalSeconds = 10
          MaxAttempts     = 2
          BackoffRate     = 2
        }]
        Catch = [{
          ErrorEquals = ["States.ALL"]
          Next        = "Remediation_Failed"
          ResultPath  = "$.error"
        }]
        Next = "Workflow_Complete"
      }

      Rejected_By_Human = {
        Type    = "Pass"
        Comment = "Engineer reviewed and chose not to remediate. Safe exit."
        Result  = { outcome = "rejected_by_human" }
        End     = true
      }

      Workflow_Complete = {
        Type    = "Succeed"
        Comment = "AI-driven remediation completed successfully"
      }

      Analysis_Failed = {
        Type  = "Fail"
        Error = "AnalysisFailed"
        Cause = "Anomaly analyser Lambda failed after 3 retries"
      }

      Approval_Timeout = {
        Type  = "Fail"
        Error = "ApprovalTimeout"
        Cause = "No human response within 24 hours — execution expired"
      }

      Remediation_Failed = {
        Type  = "Fail"
        Error = "RemediationFailed"
        Cause = "Remediator Lambda failed after 2 retries"
      }
    }
  })
}
