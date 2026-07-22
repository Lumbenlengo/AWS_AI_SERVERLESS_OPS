# terraform/environments/dev/variables.tf
#
# FIXED vs previous version:
#   - aws_account_id variable REMOVED entirely. It was hardcoded (leaked in the
#     repo) and terraform.tfvars overrode it with "" which broke bucket naming.
#     The account ID now always comes from data.aws_caller_identity.
#   - alert_email has no default — personal email no longer committed.

variable "project_name" {
  description = "Project name used for all resource naming"
  type        = string
  default     = "ai-ops-serverless"
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "bedrock_model_id" {
  description = "Amazon Bedrock model ID for Claude"
  type        = string
  default     = "anthropic.claude-3-haiku-20240307-v1:0"
}

variable "slack_webhook_url" {
  description = "Slack Incoming Webhook URL. Set via TF_VAR_slack_webhook_url — never commit."
  type        = string
  default     = ""
  sensitive   = true
}

variable "alert_email" {
  description = "Email address for SNS alert subscriptions. Set via TF_VAR_alert_email or tfvars (gitignored)."
  type        = string
}

variable "github_repository" {
  description = "GitHub org/repo allowed to assume the CI role via OIDC, e.g. Lumbenlengo/AWS_AI_SERVERLESS_OPS"
  type        = string
}

variable "cost_alert_threshold" {
  description = "Daily spend threshold in USD that triggers an AI cost alert"
  type        = number
  default     = 10
}

variable "api_throttle_rate" {
  description = "API Gateway requests per second limit"
  type        = number
  default     = 10
}

variable "api_daily_quota" {
  description = "API Gateway max requests per day"
  type        = number
  default     = 1000
}

variable "demo_app_enabled" {
  description = "Deploy the ECS demo workload (adds ~$9/month Fargate cost). Required for the end-to-end remediation demo."
  type        = bool
  default     = true
}

variable "admin_cidr" {
  description = "CIDR allowed to reach the demo app directly, e.g. your-ip/32"
  type        = string
  default     = "0.0.0.0/0"
}

variable "anthropic_api_key" {
  description = "Anthropic API key for direct Claude calls (leave empty to use Bedrock)"
  type        = string
  default     = ""
  sensitive   = true
}