# AI Ops Serverless Platform

> Event-driven AI operations platform using AWS Lambda and Amazon Bedrock.
> Implements a scalable, cost-efficient serverless architecture for intelligent
> infrastructure operations with human-in-the-loop automation.
> Every resource is Infrastructure-as-Code. Zero static keys.

**Live endpoint:** `https://api.patriciolumbe.com/runbook/ask`

---

## What This Project Is NOT

This is not an AI wrapper that calls Bedrock and returns a response. That is a demo.

This project uses AI to **enhance infrastructure operations**: detecting anomalies, explaining
them in plain English to non-technical stakeholders, and safely automating remediation
with a human approval gate. The AI is a component in an event-driven system — not the system itself.

---

## Architecture

```
CloudWatch Anomaly Detection
         │
         ▼
    EventBridge ──────────────────────────────────────────┐
         │                                                │
         ▼                                                ▼
  Lambda: Anomaly Analyser                    EventBridge Schedule
         │                                    (daily 8am UTC)
         │ boto3 → Bedrock Claude                         │
         │                                                ▼
         ▼                                    Lambda: Cost Reporter
  Step Functions Workflow                              │
         │                                             ▼
    ┌────┴────┐                              Cost Explorer API
    │AI Analyse│                                        │
    └────┬────┘                                         ▼
         │                                    Bedrock Claude
    ┌────▼────┐                              (explain cost trend)
    │Notify + │  ← Slack message with                   │
    │  WAIT   │    Approve/Reject commands               ▼
    └────┬────┘                                      SNS/Slack
         │
    Human clicks Approve
         │
    ┌────▼────┐
    │Remediate│ ← ECS restart / ASG scale
    └─────────┘

  API Gateway (POST /ask)
         │
         ▼
  Lambda: Runbook Assistant
         │
         ▼
  S3 Runbooks → Bedrock Claude
  (RAG pattern — answers from your docs)
```

---

## Features

| Feature | AWS Services | What it proves |
|---|---|---|
| AI log analysis | CloudWatch → EventBridge → Lambda → Bedrock | AI-powered ops automation |
| Anomaly explanation | CloudWatch Anomaly Detection → Lambda → Bedrock → Slack | Metrics in plain English for stakeholders |
| Runbook Q&A | API Gateway → Lambda → S3 → Bedrock | RAG pattern + vector retrieval concept |
| Human-in-the-loop | Step Functions `waitForTaskToken` | Enterprise governance pattern |
| Daily cost intelligence | EventBridge schedule → Lambda → Cost Explorer → Bedrock | FinOps automation |

---

## Why Step Functions, Not a Single Lambda

A single Lambda doing detect → analyse → notify → remediate is fragile:
- Lambda has a 15-minute timeout — cannot wait for human approval
- If one step fails, no visibility into which step, no retry logic
- No audit trail of what automated action was taken and when

Step Functions solves all of this. Each state is independently retried. The workflow
pauses at zero cost via `waitForTaskToken`. Full execution history stored for 90 days.

---

## Folder Structure

```
ai-ops-serverless-platform/
├── terraform/
│   ├── environments/dev/         # Root configuration
│   └── modules/
│       ├── iam/                  # All roles and policies
│       ├── lambda/               # All 4 Lambda functions
│       ├── step_functions/       # AI Ops state machine
│       ├── api_gateway/          # Runbook assistant endpoint
│       ├── eventbridge/          # Alarm and schedule triggers
│       └── monitoring/           # Alarms, dashboards, SNS
├── functions/
│   ├── anomaly_analyser/         # AI alarm analysis + approval gate
│   ├── runbook_assistant/        # RAG-based Q&A
│   ├── cost_reporter/            # Daily FinOps AI analysis
│   └── remediator/               # Post-approval automated fix
├── runbooks/                     # Markdown knowledge base for AI
├── events/                       # Test payloads for every Lambda
├── docs/adr/                     # Architecture Decision Records
└── .github/workflows/            # CI/CD pipeline
```

---

## Cost Estimate

| Component | Monthly Cost |
|---|---|
| Lambda (100 invocations/month avg) | ~$0.02 |
| Step Functions (600 state transitions) | ~$0.02 |
| API Gateway (1000 requests) | ~$0.004 |
| CloudWatch Alarms (5) | ~$0.50 |
| S3 (runbooks storage) | ~$0.01 |
| **Total** | **~$0.60/month** |

> This is the power of serverless — the platform costs almost nothing when idle.

---

## Deployment

```bash
# 1. Bootstrap state backend (once)
aws s3 mb s3://ai-ops-serverless-tfstate-678632990341 --region us-east-1
aws dynamodb create-table \
  --table-name ai-ops-serverless-tflock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# 2. Deploy
cd terraform/environments/dev
terraform init
terraform plan
terraform apply

# 3. Upload runbooks
aws s3 sync ../../runbooks/ s3://$(terraform output -raw runbooks_bucket)/

# 4. Test the runbook assistant
curl -X POST $(terraform output -raw api_url) \
  -H "Content-Type: application/json" \
  -H "x-api-key: $(aws secretsmanager get-secret-value \
    --secret-id ai-ops-serverless/dev/api-gateway/ops-key \
    --query SecretString --output text)" \
  -d '{"question": "How do I roll back a failed deployment?"}'

# 5. Trigger the full AI Ops workflow
aws stepfunctions start-execution \
  --state-machine-arn $(terraform output -raw step_functions_arn) \
  --input file://../../events/step-functions-input.json
```

---

Built by [Patricio Lumbe](https://patriciolumbe.com)
