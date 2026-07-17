variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "functions_path" { type = string }

variable "step_functions_arn" {
  description = "The AI Ops state machine ARN — console can list/read/approve executions on this machine only"
  type        = string
}

variable "runbook_assistant_lambda_arn" {
  description = "Console proxies /api/ask to this Lambda only"
  type        = string
}