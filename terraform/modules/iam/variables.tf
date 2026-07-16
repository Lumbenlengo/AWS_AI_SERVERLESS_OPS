variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }

variable "bedrock_model_id" {
  description = "Model ID used to scope bedrock:InvokeModel to this model only"
  type        = string
}

variable "sns_topic_arn" {
  description = "Alerts topic — the only topic Lambdas may publish to"
  type        = string
}

variable "runbooks_bucket_arn" {
  description = "Runbooks bucket ARN — the only bucket the runbook assistant may read"
  type        = string
}

variable "github_repository" {
  description = "org/repo allowed to assume the CI role via OIDC"
  type        = string
}