![AWS](https://img.shields.io/badge/Amazon_Web_Services-FF9900?style=for-the-badge&logo=amazonwebservices&logoColor=white)
![Python](https://img.shields.io/badge/Python-FFD43B?style=for-the-badge&logo=python&logoColor=blue)
![Terraform](https://img.shields.io/badge/Terraform-7B42BC?style=for-the-badge&logo=terraform&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)
![MIT License](https://img.shields.io/badge/MIT-green?style=for-the-badge)

# AI Ops Serverless Platform

When something breaks in the cloud at 3 a.m., a person usually has to notice
the alarm, dig through logs to figure out what went wrong, decide on a fix, and
run it. This project does the noticing, figuring-out, and explaining
automatically — then waits for a human to say "yes, go ahead" before it touches
anything.

The AI reads the alarm and writes a plain-English explanation. It never decides
what to change on its own, and nothing runs without someone approving it first.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Compute** | AWS Lambda, ECS Fargate, API Gateway |
| **Orchestration** | Step Functions, EventBridge |
| **Monitoring** | CloudWatch (Logs, Metrics, Alarms) |
| **AI** | Anthropic Claude API (Planned: Amazon Bedrock) |
| **Infrastructure** | Terraform (8 modules) |
| **Storage** | S3, Secrets Manager |
| **Language** | Python 3.12 |
| **CI/CD** | GitHub Actions |
| **Runbook Format** | Markdown + RAG retrieval |

---

## Key Features

✅ **AI-powered incident analysis** — Claude reads alarms and explains root cause in plain English

✅ **Human-in-the-loop approvals** — Nothing runs until a human clicks "approve"

✅ **Deterministic remediation** — Actions come from a Terraform-owned allowlist, never from the model

✅ **Zero-cost waiting** — Step Functions pauses at $0 while waiting for human decision

✅ **Full audit trail** — Every decision logged in CloudWatch and Step Functions history

✅ **Serverless & cost-efficient** — ~$0.60/month idle, scales with incident volume

✅ **RAG runbook assistant** — Answers operational questions by reading team's own Markdown docs

✅ **Mission Control dashboard** — Web UI for approvals, incident history, and Q&A

---

## How It Works: Architecture at a Glance

```
CloudWatch Alarm
       ↓
  EventBridge (routes event)
       ↓
 Step Functions (orchestrates workflow)
       ↓
 anomaly_analyser Lambda (calls Claude)
       ↓
 Claude writes root cause + suggested action
       ↓
 Slack notification (human sees analysis)
       ↓
 Mission Control dashboard (human approves or rejects)
       ↓
 remediator Lambda (only if approved)
       ↓
 ECS service restarts (via Terraform-allowed actions only)
       ↓
    ✅ Incident recovered
```

---

## Full Architecture Diagram

<img width="1331" height="663" alt="diagram AI OPS PLATFORM" src="https://github.com/user-attachments/assets/25845f32-c4a8-4bac-8bd8-bc01264cd50f" />

---

## Incident Response Pipeline
<img width="3000" height="1688" alt="Incident Response Pipeline" src="https://github.com/user-attachments/assets/889318ed-0cea-4dc5-8821-fd9f310c58df" />

**Example timeline for a typical incident:**
- Detect: ~60 seconds (CloudWatch → EventBridge → Step Functions)
- Analyse: ~30 seconds (Claude reads alarm, writes explanation)
- Human review & approval: 1–5 minutes
- Remediation: ~30 seconds (restart service)
- **Total: 2–7 minutes from alarm to recovery**

*(Compared to manual incident response: 30 min detection + 60 min diagnosis + 30 min fix = ~2 hours)*

---

## Safety: Six Safeguards Between AI and Your Infrastructure
<img width="3000" height="1688" alt="Safety Six Safeguards Between AI and Your Infrastructure" src="https://github.com/user-attachments/assets/c5f3d66e-14e9-45aa-aab9-f5ab0c9dbcd8" />

The core guarantee: **the AI never holds the keys**. It can only suggest actions
from a short pre-approved list, and the actual target always comes from a
Terraform table, never from the model. Unknown alarm? It just logs and waits.

---

## What Each Function Does

| Function | Job | Can modify infrastructure? |
|---|---|---|
| **anomaly_analyser** | Read alarm, ask Claude, validate against rules | ❌ No (read-only) |
| **remediator** | Execute approved action (restart service) | ✅ Yes, allowlisted only |
| **runbook_assistant** | Answer questions by reading Markdown docs | ❌ No (read-only) |
| **cost_reporter** | Daily spend summary | ❌ No (read-only) |
| **mission_control** | Web dashboard for approvals and history | ❌ No (UI only) |

---

## Why Step Functions, Not One Big Function

A single function fails for incident response because:
- **Timeout risk** — Functions time out after 15 minutes (humans need more time to approve)
- **No audit trail** — If something fails mid-run, you don't know which step
- **No pause point** — Can't wait for human input without burning compute cost

Step Functions solves this:
- Pauses at zero cost while waiting for human approval
- Each step is retried independently if it fails
- Full execution history stored for 90 days
- Built for long-running workflows with human gates

---

<img width="3000" height="1688" alt="Engineering Challenges Solved" src="https://github.com/user-attachments/assets/c25993ab-72e3-4a8f-b555-d34a4b375e33" />

## Engineering Challenges Solved

| Challenge | Solution |
|---|---|
| **Waiting for human without paying compute** | Step Functions `waitForTaskToken` — paused executions cost $0 |
| **AI remediation staying safe** | Deterministic allowlist from Terraform; model never names targets |
| **Preventing accidental infrastructure changes** | Lambda re-validates allowlist independently, no shortcuts |
| **Handling alarms 24/7 without on-call SRE** | Fully automated detect and analyse; human just clicks approve/reject |
| **Explaining incidents to non-engineers** | Claude generates plain English summaries, posted to Slack |
| **Sharing operational knowledge** | RAG over Markdown runbooks stored in S3 |

---

## Infrastructure as Code: Terraform Modules

```
terraform/modules/
├── iam/              # All roles and policies (least-privilege)
├── lambda/           # All 5 functions
├── step_functions/   # State machine definition
├── api_gateway/      # Runbook assistant endpoint
├── eventbridge/      # Alarm routing and schedule triggers
├── ecs_app/          # Demo app + ECS cluster + alarms
├── monitoring/       # Dashboards, alarms, SNS
└── mission_control/  # Lambda Function URL + dashboard
```

Nearly all infrastructure managed by Terraform, versioned, and deployable with
`terraform apply`. One exception: Mission Control public access permissions (currently
set manually via AWS CLI; on roadmap to move into Terraform).

---

## CI/CD Pipeline

Every push to main/develop:

```
GitHub Actions
    ↓
✅ Python unit tests (pytest)
✅ Terraform fmt + validate
✅ Build & push Docker image to ECR
✅ Terraform apply
✅ Force ECS deployment
```

---

## Observability

| What | Where | Purpose |
|---|---|---|
| Lambda executions | CloudWatch Logs | Debugging function behavior |
| Step Functions flow | Step Functions Executions tab | Tracking workflow progress and history |
| API calls | CloudWatch Metrics (custom) | Monitoring request patterns |
| Application events | Application Logs (via ECS) | Understanding app behavior during incidents |

---

## Project Structure

```
ai-ops-serverless-platform/
├── terraform/
│   ├── environments/dev/      # Main configuration
│   └── modules/               # 8 reusable modules
├── functions/
│   ├── anomaly_analyser/      # AI analysis
│   ├── remediator/            # Infrastructure changes
│   ├── runbook_assistant/     # Q&A
│   ├── cost_reporter/         # Daily summary
│   ├── mission_control/       # Dashboard
│   └── tests/                 # pytest suite
├── runbooks/                  # Markdown docs for RAG
├── docs/adr/                  # Architecture Decision Records
├── events/                    # Test payloads
└── .github/workflows/         # GitHub Actions
```

---

## Cost Breakdown

| Scenario | Monthly Cost |
|---|---|
| **Idle** (no traffic, no alarms) | ~$0.60 |
| **Example workload** (10 incidents/day) | ~$3.00 |
| **With demo app running 24/7** | ~$9.60 |

Serverless means you pay only for what you use. The demo app (ECS Fargate) is
there to show the system working live; removing it drops costs back to under $1/month.

---

## Current Status

✅ **Working end-to-end:**
- Demo app (ECS Fargate) with realistic alarms
- CloudWatch → EventBridge → Step Functions workflow
- Lambda analysis (Anthropic API)
- Human approval gate (Mission Control dashboard)
- Slack notifications
- Terraform 8-module architecture
- GitHub Actions CI/CD pipeline

⏳ **Next steps:**
- Move to Amazon Bedrock (pending model approval)
- Fold Mission Control permissions into Terraform
- Add multi-region support
- Broader remediation actions (SSM Automation, EKS)

---

## Architecture Decisions

Why these choices? Read the full reasoning:

- **[ADR 001: Step Functions over Lambda chain](docs/adr/001-step-functions-over-lambda-chain.md)** — Long-running workflows need pause-and-wait, retries, audit trails
- **[ADR 002–003: AI safety and deterministic remediation](docs/adr/002-003-additional-decisions.md)** — AI suggests, humans decide; targets come from code, not from model
- **[ADR 004: Deterministic remediation targets](docs/adr/004-deterministic-remediation-targets.md)** — Unknown alarm = no action (secure by default)

---

## Skills Demonstrated

This project demonstrates:

**Architecture & Design**
- Event-driven architecture (CloudWatch → EventBridge → Step Functions → Lambda)
- Human-in-the-loop AI systems
- Serverless patterns and cost optimization
- Infrastructure as Code (Terraform, 8 modules)

**AWS & Cloud**
- Lambda, Step Functions, EventBridge, API Gateway
- ECS Fargate, ECR, CloudWatch
- IAM (least-privilege roles per function)
- Secrets Manager, S3
- VPC and networking

**AI/ML Integration**
- LLM API integration (Claude)
- Prompt engineering (constrained prompts)
- RAG (Retrieval-Augmented Generation) for runbooks
- Safe AI guardrails (allowlists, deterministic execution)

**Engineering & Operations**
- Incident response automation
- Audit trails and compliance
- Real-time monitoring and alerting
- Cost awareness and optimization

---

## Roadmap

| Phase | Focus |
|---|---|
| **Now** | Bedrock integration, Terraform completeness |
| **Q3 2026** | Multi-region, advanced cost analytics |
| **Q4 2026** | Broader remediation (SSM Automation), EKS support |
| **2027** | Custom action framework, policy-based approvals |

---

## Deploying It Yourself

```bash
# 1. Create state backend (once)
aws s3 mb s3://ai-ops-serverless-tfstate-$(aws sts get-caller-identity --query Account --output text) \
  --region us-east-1

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
  -H "x-api-key: $(aws secretsmanager get-secret-value --secret-id ai-ops-serverless/dev/api-gateway/ops-key --query SecretString --output text)" \
  -d '{"question": "How do I roll back a failed deployment?"}'

# 5. Trigger the workflow by hand
aws stepfunctions start-execution \
  --state-machine-arn $(terraform output -raw step_functions_arn) \
  --input file://../../events/step-functions-input.json
```

---

## Screenshots & Demo

*[GIF: Full incident workflow — alarm → Slack → approval → restart → healthy]*

*[Screenshot: Mission Control dashboard showing pending approvals]*

*[Screenshot: Step Functions execution history]*

---

## Author

**Patricio Lumbe**  
Cloud Engineer | AWS | Infrastructure as Code  

🔗 [LinkedIn](https://linkedin.com/in/patriciolumbe)  
🌐 [Portfolio](https://patriciolumbe.com)  
📧 [contact@patriciolumbe.com](mailto:contact@patriciolumbe.com)  
💻 [GitHub](https://github.com/lumbenlengo)

---

*This project demonstrates production incident-response patterns: event-driven architecture,
safe AI integration, Infrastructure as Code, and human governance. Everything is version-controlled,
tested, and deployed via CI/CD.*


