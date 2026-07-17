variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "bedrock_model_id" { type = string }
variable "runbooks_bucket_name" { type = string }
variable "sns_topic_arn" { type = string }
variable "functions_path" { type = string }
variable "cost_alert_threshold" { type = number }

variable "slack_webhook_url" {
  type      = string
  sensitive = true
  default   = ""
}

variable "lambda_role_arns" {
  description = "One IAM role per function: anomaly_analyser, runbook_assistant, cost_reporter, remediator"
  type        = map(string)
}

variable "remediation_map" {
  description = "Deterministic alarm -> remediation target mapping (ADR 004). Keys are alarm names; values define the resource and the actions the AI may recommend for it."
  type = map(object({
    resource        = string
    allowed_actions = list(string)
  }))
  default = {}
}
