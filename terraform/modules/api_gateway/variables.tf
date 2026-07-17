# terraform/modules/api_gateway/variables.tf

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region — needed to build the Lambda integration URI"
  type        = string
}

variable "runbook_assistant_lambda_arn" {
  description = "ARN of the runbook_assistant Lambda this API proxies to"
  type        = string
}

variable "api_throttle_rate" {
  description = "Requests per second limit for the usage plan and stage method settings"
  type        = number
}

variable "api_daily_quota" {
  description = "Maximum requests per day for the usage plan"
  type        = number
}
