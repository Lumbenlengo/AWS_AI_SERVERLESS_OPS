# Copy to terraform.tfvars (gitignored) and fill in.
# Secrets (slack webhook) go via environment: TF_VAR_slack_webhook_url=...

project_name         = "ai-ops-serverless"
aws_region           = "us-east-1"
environment          = "dev"
bedrock_model_id     = "anthropic.claude-3-haiku-20240307-v1:0"
alert_email          = "contact@patriciolumbe.com"
github_repository    = "Lumbenlengo/AWS_AI_SERVERLESS_OPS"
cost_alert_threshold = 10
api_throttle_rate    = 10
api_daily_quota      = 1000

# Turn on for the full end-to-end demo (adds ~$9/month Fargate cost)
demo_app_enabled = false
admin_cidr       = "0.0.0.0/0" # restrict to your-ip/32 for the demo
