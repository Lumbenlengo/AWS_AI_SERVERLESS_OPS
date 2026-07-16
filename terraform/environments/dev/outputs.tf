# terraform/environments/dev/outputs.tf

output "api_url" {
  description = "HTTPS endpoint for the Runbook Assistant — POST here with your question"
  value       = module.api_gateway.api_url
}

output "api_key_secret_arn" {
  description = "Secrets Manager ARN containing the API Gateway key"
  value       = module.api_gateway.api_key_secret_arn
}

output "step_functions_arn" {
  description = "ARN of the AI Ops Step Functions state machine"
  value       = module.step_functions.state_machine_arn
}

output "runbooks_bucket" {
  description = "S3 bucket name — upload your Markdown runbooks here"
  value       = aws_s3_bucket.runbooks.id
}

output "sns_topic_arn" {
  description = "ARN of the SNS alerts topic"
  value       = aws_sns_topic.alerts.arn
}

output "github_actions_role_arn" {
  description = "Set this as the AWS_ROLE_ARN secret in the GitHub repo"
  value       = module.iam.github_actions_role_arn
}

output "cloudwatch_dashboard_url" {
  description = "Direct URL to the CloudWatch operations dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${var.project_name}-${var.environment}-ai-ops"
}



output "mission_control_url" {
  description = "Open this in a browser — the fullstack Ops Console (approvals, incidents, assistant, costs)"
  value       = module.mission_control.console_url
}

output "mission_control_key_secret_arn" {
  description = "Secrets Manager ARN with the console sign-in key"
  value       = module.mission_control.console_key_secret_arn
}



output "demo_app_ecr_url" {
  description = "Push the demo-app image here (docker build demo-app/ && docker push)"
  value       = try(module.demo_app[0].ecr_repository_url, null)
}

output "demo_app_cluster" {
  value = try(module.demo_app[0].cluster_name, null)
}

output "demo_app_service" {
  value = try(module.demo_app[0].service_name, null)
}

output "demo_app_watch_alarm" {
  description = "The alarm that feeds the AI Ops workflow"
  value       = try(module.demo_app[0].watch_alarm_name, null)
}