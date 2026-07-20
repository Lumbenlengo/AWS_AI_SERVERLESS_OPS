# terraform/environments/dev/main.tf


terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.40" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Repository  = "github.com/Lumbenlengo/AWS_AI_SERVERLESS_OPS"
    }
  }
}

data "aws_caller_identity" "current" {}

# SNS ALERT TOPIC

resource "aws_sns_topic" "alerts" {
  name              = "${var.project_name}-${var.environment}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# S3: RUNBOOKS BUCKET

resource "aws_s3_bucket" "runbooks" {
  bucket        = "${var.project_name}-${var.environment}-runbooks-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment == "dev"
}

resource "aws_s3_bucket_versioning" "runbooks" {
  bucket = aws_s3_bucket.runbooks.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "runbooks" {
  bucket = aws_s3_bucket.runbooks.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "runbooks" {
  bucket                  = aws_s3_bucket.runbooks.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# MODULE: IAM

module "iam" {
  source              = "../../modules/iam"
  project_name        = var.project_name
  environment         = var.environment
  aws_region          = var.aws_region
  bedrock_model_id    = var.bedrock_model_id
  sns_topic_arn       = aws_sns_topic.alerts.arn
  runbooks_bucket_arn = aws_s3_bucket.runbooks.arn
  github_repository   = var.github_repository
}

# MODULE: LAMBDA
# remediation_map now points at the demo app now that ecs_app exists.

module "lambda" {
  source               = "../../modules/lambda"
  project_name         = var.project_name
  environment          = var.environment
  aws_region           = var.aws_region
  bedrock_model_id     = var.bedrock_model_id
  slack_webhook_url    = var.slack_webhook_url
  cost_alert_threshold = var.cost_alert_threshold
  sns_topic_arn        = aws_sns_topic.alerts.arn
  runbooks_bucket_name = aws_s3_bucket.runbooks.id
  functions_path       = "${path.root}/../../../functions"

  remediation_map = var.demo_app_enabled ? {
    "${var.project_name}-${var.environment}-watch-demo-app-errors" = {
      resource        = "${module.demo_app[0].cluster_name}/${module.demo_app[0].service_name}"
      allowed_actions = ["restart_ecs_service", "log_only"]
    }
  } : {}

  lambda_role_arns = {
    anomaly_analyser  = module.iam.analyser_role_arn
    runbook_assistant = module.iam.runbook_role_arn
    cost_reporter     = module.iam.cost_reporter_role_arn
    remediator        = module.iam.remediator_role_arn
  }
}

# MODULE: STEP FUNCTIONS

module "step_functions" {
  source                = "../../modules/step_functions"
  project_name          = var.project_name
  environment           = var.environment
  sfn_role_arn          = module.iam.step_functions_role_arn
  analyser_lambda_arn   = module.lambda.anomaly_analyser_arn
  remediator_lambda_arn = module.lambda.remediator_arn
}

# MODULE: EVENTBRIDGE

module "eventbridge" {
  source                   = "../../modules/eventbridge"
  project_name             = var.project_name
  environment              = var.environment
  step_functions_arn       = module.step_functions.state_machine_arn
  eventbridge_role_arn     = module.iam.eventbridge_sfn_role_arn
  cost_reporter_lambda_arn = module.lambda.cost_reporter_arn
}

# MODULE: MONITORING

module "monitoring" {
  source             = "../../modules/monitoring"
  project_name       = var.project_name
  environment        = var.environment
  aws_region         = var.aws_region
  sns_topic_arn      = aws_sns_topic.alerts.arn
  step_functions_arn = module.step_functions.state_machine_arn
}

# MODULE: API GATEWAY

module "api_gateway" {
  source                       = "../../modules/api_gateway"
  project_name                 = var.project_name
  environment                  = var.environment
  aws_region                   = var.aws_region
  runbook_assistant_lambda_arn = module.lambda.runbook_assistant_arn
  api_throttle_rate            = var.api_throttle_rate
  api_daily_quota              = var.api_daily_quota
}

# MODULE: DEMO APP

module "ecs_app" {
  count        = var.demo_app_enabled ? 1 : 0
  source       = "../../modules/ecs_app"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  admin_cidr   = var.admin_cidr
}

# MODULE: MISSION CONTROL

module "mission_control" {
  source                       = "../../modules/mission_control"
  project_name                 = var.project_name
  environment                  = var.environment
  aws_region                   = var.aws_region
  functions_path               = "${path.root}/../../../functions"
  step_functions_arn           = module.step_functions.state_machine_arn
  runbook_assistant_lambda_arn = module.lambda.runbook_assistant_arn
}