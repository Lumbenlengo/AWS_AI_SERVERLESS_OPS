# terraform/modules/iam/main.tf

data "aws_caller_identity" "current" {}

locals {
  prefix         = "${var.project_name}-${var.environment}"
  log_group_arns = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.prefix}-*"

  bedrock_is_inference_profile = can(regex("^(us|eu|apac)\\.", var.bedrock_model_id))

  bedrock_profile_arn = "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}"

  bedrock_foundation_model_id  = local.bedrock_is_inference_profile ? join(".", slice(split(".", var.bedrock_model_id), 1, length(split(".", var.bedrock_model_id)))) : var.bedrock_model_id
  bedrock_foundation_model_arn = "arn:aws:bedrock:*::foundation-model/${local.bedrock_foundation_model_id}"

  bedrock_model_arns = local.bedrock_is_inference_profile ? [local.bedrock_profile_arn, local.bedrock_foundation_model_arn] : [local.bedrock_foundation_model_arn]
}
# ── SHARED TRUST + BASELINE POLICIES ─────────────────────────────────────────

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "logs_and_xray" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.log_group_arns}:*"]
  }
  statement {
    sid       = "XRay"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    resources = ["*"] # X-Ray does not support resource-level permissions
  }
}

resource "aws_iam_policy" "logs_and_xray" {
  name   = "${local.prefix}-lambda-logs-xray"
  policy = data.aws_iam_policy_document.logs_and_xray.json
}

# ── ROLE 1: ANOMALY ANALYSER ─────────────────────────────────────────────────

resource "aws_iam_role" "analyser" {
  name               = "${local.prefix}-analyser-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "analyser" {
  name = "analyser-permissions"
  role = aws_iam_role.analyser.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "BedrockThisModelOnly"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.bedrock_model_arns
      },
      {
        Sid      = "SNSThisTopicOnly"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = var.sns_topic_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "analyser_base" {
  role       = aws_iam_role.analyser.name
  policy_arn = aws_iam_policy.logs_and_xray.arn
}

# ── ROLE 2: RUNBOOK ASSISTANT (public-facing — most restricted) ──────────────

resource "aws_iam_role" "runbook" {
  name               = "${local.prefix}-runbook-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "runbook" {
  name = "runbook-permissions"
  role = aws_iam_role.runbook.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "BedrockThisModelOnly"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.bedrock_model_arns
      },
      {
        Sid      = "RunbooksBucketReadOnly"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [var.runbooks_bucket_arn, "${var.runbooks_bucket_arn}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "runbook_base" {
  role       = aws_iam_role.runbook.name
  policy_arn = aws_iam_policy.logs_and_xray.arn
}

# ── ROLE 3: COST REPORTER ────────────────────────────────────────────────────

resource "aws_iam_role" "cost_reporter" {
  name               = "${local.prefix}-cost-reporter-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "cost_reporter" {
  name = "cost-reporter-permissions"
  role = aws_iam_role.cost_reporter.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "CostExplorerRead"
        Effect   = "Allow"
        Action   = ["ce:GetCostAndUsage", "ce:GetCostForecast"]
        Resource = "*" # Cost Explorer does not support resource-level permissions
      },
      {
        Sid      = "BedrockThisModelOnly"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.bedrock_model_arns
      },
      {
        Sid      = "SNSThisTopicOnly"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = var.sns_topic_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cost_reporter_base" {
  role       = aws_iam_role.cost_reporter.name
  policy_arn = aws_iam_policy.logs_and_xray.arn
}

# ── ROLE 4: REMEDIATOR (the only role that can mutate infrastructure) ────────


resource "aws_iam_role" "remediator" {
  name               = "${local.prefix}-remediator-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "remediator" {
  name = "remediator-permissions"
  role = aws_iam_role.remediator.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECSDescribe"
        Effect   = "Allow"
        Action   = ["ecs:DescribeServices", "ecs:ListTasks"]
        Resource = "*"
      },
      {
        Sid      = "ECSRestartTaggedOnly"
        Effect   = "Allow"
        Action   = ["ecs:UpdateService"]
        Resource = "*"
        Condition = {
          StringEquals = { "aws:ResourceTag/AIOpsManaged" = "true" }
        }
      },
      {
        Sid      = "ASGDescribe"
        Effect   = "Allow"
        Action   = ["autoscaling:DescribeAutoScalingGroups"]
        Resource = "*"
      },
      {
        Sid      = "ASGScaleTaggedOnly"
        Effect   = "Allow"
        Action   = ["autoscaling:UpdateAutoScalingGroup"]
        Resource = "*"
        Condition = {
          StringEquals = { "aws:ResourceTag/AIOpsManaged" = "true" }
        }
      },
      {
        Sid      = "SNSThisTopicOnly"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = var.sns_topic_arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "remediator_base" {
  role       = aws_iam_role.remediator.name
  policy_arn = aws_iam_policy.logs_and_xray.arn
}

# ── STEP FUNCTIONS EXECUTION ROLE ────────────────────────────────────────────

resource "aws_iam_role" "step_functions" {
  name = "${local.prefix}-sfn-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "step_functions" {
  name = "sfn-permissions"
  role = aws_iam_role.step_functions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokePlatformLambdasOnly"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.prefix}-*"
      },
      {
        # CloudWatch Logs delivery for SFN requires these on * (AWS limitation)
        Sid    = "SFNLogDelivery"
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

# ── EVENTBRIDGE -> STEP FUNCTIONS ROLE ───────────────────────────────────────

resource "aws_iam_role" "eventbridge_sfn" {
  name = "${local.prefix}-eventbridge-sfn-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "events.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_sfn" {
  name = "start-step-functions"
  role = aws_iam_role.eventbridge_sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.prefix}-*"
    }]
  })
}

# ── GITHUB ACTIONS OIDC (tightened) ──────────────────────────────────────────


resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd"
  ]
}

resource "aws_iam_role" "github_actions" {
  name = "${local.prefix}-github-actions-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Condition = {
        # Exact repo, not org wildcard
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:*" }
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_actions" {
  name = "terraform-deploy"
  role = aws_iam_role.github_actions.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "StateBackend"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::${var.project_name}-tfstate-*", "arn:aws:s3:::${var.project_name}-tfstate-*/*"]
      },
      {
        Sid      = "StateLock"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.project_name}-tflock"
      },
      {
        Sid      = "ManagePlatform"
        Effect   = "Allow"
        Action   = ["lambda:*", "states:*", "apigateway:*", "events:*", "logs:*", "sns:*", "cloudwatch:*", "s3:*", "iam:Get*", "iam:List*"]
        Resource = "*"
        # NOTE: still broad for a CI role — acceptable for a solo dev project,
        # documented as a known trade-off. Production would use per-service
        # permission boundaries or Terraform Cloud with drift detection.
      },
      {
        Sid      = "PassRoleProjectOnly"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.prefix}-*"
      }
    ]
  })
}
