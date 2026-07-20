# terraform/modules/api_gateway/main.tf

resource "aws_api_gateway_rest_api" "runbook" {
  name        = "${var.project_name}-${var.environment}-runbook-api"
  description = "AI-powered runbook assistant. POST /ask with your operational question."

  endpoint_configuration { types = ["REGIONAL"] }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_resource" "ask" {
  rest_api_id = aws_api_gateway_rest_api.runbook.id
  parent_id   = aws_api_gateway_rest_api.runbook.root_resource_id
  path_part   = "ask"
}

resource "aws_api_gateway_method" "post_ask" {
  rest_api_id      = aws_api_gateway_rest_api.runbook.id
  resource_id      = aws_api_gateway_resource.ask.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "lambda" {
  rest_api_id             = aws_api_gateway_rest_api.runbook.id
  resource_id             = aws_api_gateway_resource.ask.id
  http_method             = aws_api_gateway_method.post_ask.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/${var.runbook_assistant_lambda_arn}/invocations"
}

resource "aws_api_gateway_method_response" "ok" {
  rest_api_id = aws_api_gateway_rest_api.runbook.id
  resource_id = aws_api_gateway_resource.ask.id
  http_method = aws_api_gateway_method.post_ask.http_method
  status_code = "200"
}

resource "aws_lambda_permission" "allow_api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = var.runbook_assistant_lambda_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.runbook.execution_arn}/*/*"
}

resource "aws_api_gateway_resource" "health" {
  rest_api_id = aws_api_gateway_rest_api.runbook.id
  parent_id   = aws_api_gateway_rest_api.runbook.root_resource_id
  path_part   = "health"
}

resource "aws_api_gateway_method" "get_health" {
  rest_api_id      = aws_api_gateway_rest_api.runbook.id
  resource_id      = aws_api_gateway_resource.health.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = false
}

resource "aws_api_gateway_integration" "health_mock" {
  rest_api_id       = aws_api_gateway_rest_api.runbook.id
  resource_id       = aws_api_gateway_resource.health.id
  http_method       = aws_api_gateway_method.get_health.http_method
  type              = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "health_ok" {
  rest_api_id = aws_api_gateway_rest_api.runbook.id
  resource_id = aws_api_gateway_resource.health.id
  http_method = aws_api_gateway_method.get_health.http_method
  status_code = "200"
}

resource "aws_api_gateway_integration_response" "health_ok" {
  rest_api_id = aws_api_gateway_rest_api.runbook.id
  resource_id = aws_api_gateway_resource.health.id
  http_method = aws_api_gateway_method.get_health.http_method
  status_code = aws_api_gateway_method_response.health_ok.status_code
  response_templates = {
    "application/json" = "{\"status\": \"healthy\", \"service\": \"runbook-assistant\"}"
  }
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${var.project_name}-${var.environment}"
  retention_in_days = 14
}



resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.runbook.id
  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.ask.id,
      aws_api_gateway_method.post_ask.id,
      aws_api_gateway_integration.lambda.id,
      aws_api_gateway_resource.health.id,
      aws_api_gateway_method.get_health.id,
      aws_api_gateway_integration.health_mock.id,
    ]))
  }
  lifecycle { create_before_destroy = true }
}

resource "aws_api_gateway_stage" "dev" {
  deployment_id        = aws_api_gateway_deployment.main.id
  rest_api_id          = aws_api_gateway_rest_api.runbook.id
  stage_name           = var.environment
  xray_tracing_enabled = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn
    format = jsonencode({
      requestId    = "$context.requestId"
      ip           = "$context.identity.sourceIp"
      method       = "$context.httpMethod"
      path         = "$context.resourcePath"
      status       = "$context.status"
      responseTime = "$context.responseLatency"
    })
  }

  depends_on = [aws_api_gateway_account.this]
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.runbook.id
  stage_name  = aws_api_gateway_stage.dev.stage_name
  method_path = "*/*"

  settings {
    logging_level          = "INFO"
    metrics_enabled        = true
    throttling_rate_limit  = var.api_throttle_rate
    throttling_burst_limit = var.api_throttle_rate * 2
  }
}

resource "aws_api_gateway_api_key" "ops" {
  name    = "${var.project_name}-${var.environment}-ops-key"
  enabled = true
}

resource "aws_api_gateway_usage_plan" "ops" {
  name = "${var.project_name}-${var.environment}-usage-plan"

  api_stages {
    api_id = aws_api_gateway_rest_api.runbook.id
    stage  = aws_api_gateway_stage.dev.stage_name
  }

  quota_settings {
    limit  = var.api_daily_quota
    period = "DAY"
  }

  throttle_settings {
    rate_limit  = var.api_throttle_rate
    burst_limit = var.api_throttle_rate * 2
  }
}

resource "aws_api_gateway_usage_plan_key" "ops" {
  key_id        = aws_api_gateway_api_key.ops.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.ops.id
}

resource "aws_secretsmanager_secret" "api_key" {
  name                    = "${var.project_name}/${var.environment}/api-gateway/ops-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "api_key" {
  secret_id     = aws_secretsmanager_secret.api_key.id
  secret_string = aws_api_gateway_api_key.ops.value
}

resource "aws_iam_role" "api_gateway_cloudwatch" {
  name = "${var.project_name}-${var.environment}-apigw-cloudwatch-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  role       = aws_iam_role.api_gateway_cloudwatch.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "this" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch.arn
}