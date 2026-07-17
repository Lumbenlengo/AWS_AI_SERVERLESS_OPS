# terraform/environments/dev/outputs.tf

output "state_machine_arn" {
  description = "The AI Ops workflow, useful for triggering a manual test run"
  value       = module.step_functions.state_machine_arn
}

output "api_url" {
  description = "POST here with your operational question: {\"question\": \"...\"}"
  value       = module.api_gateway.api_url
}

output "health_url" {
  description = "No API key required, for uptime checks"
  value       = module.api_gateway.health_url
}

output "api_key_secret_arn" {
  description = "Secrets Manager ARN holding the API Gateway key"
  value       = module.api_gateway.api_key_secret_arn
}

output "mission_control_url" {
  description = "Open this in a browser, enter the console key when prompted"
  value       = module.mission_control.console_url
}

output "mission_control_key_secret_arn" {
  description = "Secrets Manager ARN holding the Mission Control access key"
  value       = module.mission_control.console_key_secret_arn
}

output "demo_app_ecr_url" {
  description = "Push the demo app image here, null if demo_app_enabled is false"
  value       = try(module.demo_app[0].ecr_repository_url, null)
}

output "demo_app_cluster" {
  value = try(module.demo_app[0].cluster_name, null)
}

output "demo_app_service" {
  value = try(module.demo_app[0].service_name, null)
}

output "demo_app_watch_alarm" {
  description = "Confirm this name matches what REMEDIATION_MAP expects"
  value       = try(module.demo_app[0].watch_alarm_name, null)
}