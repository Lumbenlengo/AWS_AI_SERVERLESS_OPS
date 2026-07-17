# terraform/modules/api_gateway/outputs.tf

output "api_url" {
  description = "POST here with your operational question: {\"question\": \"...\"}"
  value       = "${aws_api_gateway_stage.dev.invoke_url}/ask"
}

output "health_url" {
  description = "No API key required — for uptime checks"
  value       = "${aws_api_gateway_stage.dev.invoke_url}/health"
}

output "api_key_secret_arn" {
  description = "Secrets Manager ARN holding the API Gateway key — fetch with: aws secretsmanager get-secret-value --secret-id <this-arn> --query SecretString --output text"
  value       = aws_secretsmanager_secret.api_key.arn
}
