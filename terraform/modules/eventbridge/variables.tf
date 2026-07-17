

variable "project_name" { type = string }
variable "environment" { type = string }
variable "step_functions_arn" { type = string }

variable "eventbridge_role_arn" {
  description = "Dedicated EventBridge role allowed to StartExecution on the state machine"
  type        = string
}

variable "cost_reporter_lambda_arn" { type = string }
