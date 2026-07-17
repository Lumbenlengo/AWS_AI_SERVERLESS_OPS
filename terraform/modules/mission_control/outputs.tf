output "console_url" {
  description = "Ops Console URL — open in a browser, enter the console key to sign in"
  value       = aws_lambda_function_url.console.function_url
}

output "console_key_secret_arn" {
  description = "Secrets Manager ARN holding the console auth key"
  value       = aws_secretsmanager_secret.console_key.arn
}