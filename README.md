![AWS](https://img.shields.io/badge/Amazon_Web_Services-FF9900?style=for-the-badge&logo=amazonwebservices&logoColor=white)
![Python](https://img.shields.io/badge/Python-FFD43B?style=for-the-badge&logo=python&logoColor=blue)
![Terraform](https://img.shields.io/badge/Terraform-7B42BC?style=for-the-badge&logo=terraform&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)
![MIT License](https://img.shields.io/badge/MIT-green?style=for-the-badge)

# AI Ops Serverless Platform

When something breaks in the cloud at 3 a.m., a person usually has to notice
the alarm, dig through logs to figure out what went wrong, decide on a fix, and
run it. This project does the noticing, figuring-out, and explaining
automatically then waits for a human to say "yes, go ahead" before it touches
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
| **AI** | Amazon Bedrock (Claude Sonnet 4.5, cross-region inference profile) |
| **Infrastructure** | Terraform (8 modules) |
| **Storage** | S3, Secrets Manager |
| **Networking** | Application Load Balancer, NAT Gateway, private subnets |
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

✅ **Mission Control dashboard** — Web UI for approvals, incident history, cost tracking, and Q&A

---

## How It Works: Architecture at a Glance

```
CloudWatch Alarm
       ↓
  EventBridge (routes event)
       ↓
 Step Functions (orchestrates workflow)
       ↓
 anomaly_analyser Lambda (calls Claude via Bedrock)
       ↓
 Claude writes root cause + suggested action
       ↓
 urgency LOW? ──────────────▶ logged automatically, no approval needed
       ↓ (MEDIUM / HIGH / CRITICAL)
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

**Reading the diagram, left to right:** CloudWatch and EventBridge detect and
route the event → Step Functions orchestrates the whole workflow → the AI
Reasoning Layer (`anomaly_analyser`, Bedrock, `runbook_assistant`,
`cost_reporter`) does the thinking → Human Governance (Slack, Mission Control,
`remediator`) is where every decision and every infrastructure change actually
happens. The full function-by-function breakdown is in the table below.

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
Only `MEDIUM`, `HIGH`, and `CRITICAL` urgency ever reach a human approval gate —
`LOW` urgency incidents are logged automatically, with no action taken.

---

## What Each Function Does

| Function | Job | Can modify infrastructure? |
|---|---|---|
| **anomaly_analyser** | Read alarm, ask Claude via Bedrock, validate against rules | ❌ No (read-only) |
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
| **ALB and ECS tasks landing in different Availability Zones** | Dedicated subnets created for the ALB in the same AZs as the private task subnets |
| **Deprecated Claude model version causing silent 400 errors** | Migrated to Amazon Bedrock with a cross-region inference profile; IAM widened to cover the model across regions |
| **Custom CloudWatch metric silently never arriving** | `boto3` client rebuilt fresh on every call instead of once at container startup, with explicit success/failure logging |

---

## Infrastructure as Code: Terraform Modules

```
terraform/modules/
├── iam/              # All roles and policies (least-privilege)
├── lambda/           # All 5 functions
├── step_functions/   # State machine definition
├── api_gateway/      # Runbook assistant endpoint
├── eventbridge/      # Alarm routing and schedule triggers
├── ecs_app/          # Demo app + ALB + NAT Gateway + private subnets + alarms
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
✅ 34 Python unit tests (pytest)
✅ Terraform fmt + validate
✅ Checkov security scan
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
│   └── tests/                 # 34-test pytest suite
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
| **With demo app + ALB + NAT Gateway running 24/7** | ~$55–60 |

Serverless means you pay only for what you use. The ALB, NAT Gateway, and demo
app (ECS Fargate) exist to show the system working live, behind a properly
private network, the way a real production workload would be deployed.
Removing them drops the always-on cost back to under $1/month, since Lambda,
Step Functions, and CloudWatch are pay-per-use.

This stack deliberately does not run a WAF in front of the ALB, and serves
plain HTTP rather than HTTPS — for a portfolio demo with no real customer
traffic and no owned domain routed through this AWS account, the added monthly
cost didn't justify the benefit. Both tradeoffs are documented explicitly in
the CI pipeline's Checkov configuration rather than silently skipped.

---

## Current Status

✅ **Working end-to-end:**
- Demo app (ECS Fargate) behind an ALB, in private subnets, with real alarms
- CloudWatch → EventBridge → Step Functions workflow
- Lambda analysis via Amazon Bedrock (Claude Sonnet 4.5)
- Urgency-based routing: only MEDIUM/HIGH/CRITICAL reach human approval
- Human approval gate (Mission Control dashboard)
- Slack notifications
- Terraform 8-module architecture
- GitHub Actions CI/CD pipeline with 34 automated tests and security scanning

⏳ **Next up:** see the Roadmap below.

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
- VPC and networking (ALB, NAT Gateway, private subnets)

**AI/ML Integration**
- LLM API integration (Claude via Amazon Bedrock)
- Prompt engineering (constrained prompts, decision guidance)
- RAG (Retrieval-Augmented Generation) for runbooks
- Safe AI guardrails (allowlists, deterministic execution)

**Engineering & Operations**
- Incident response automation
- Audit trails and compliance
- Real-time monitoring and alerting
- Cost awareness and optimization
- Debugging cross-region IAM, networking mismatches, and silent failures

---

## Roadmap

| Phase | Focus |
|---|---|
| **Now** | Terraform completeness (Mission Control permissions), expanded runbook catalog |
| **Q3 2026** | Multi-region support, advanced cost analytics |
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

**Note:** the ALB has `enable_deletion_protection = true`. Set it to `false`
and re-apply before running `terraform destroy`.

---

## Screenshots & Demo

A real run of the demo environment, from a healthy service to an incident
resolved with human approval.

**1. Orders API — healthy**
*Continuously monitored by the platform. This is the normal state CloudWatch observes at every moment.*

<img width="1004" height="594" alt="Orders API dashboard, service healthy" src="https://github.com/user-attachments/assets/44dd7bd3-087e-4458-b50a-6911a84c797d" />

**2. Orders API — degraded**
*The service starts failing and errors build up past the acceptable limit. This is the trigger that fires the CloudWatch alarm.*

<img width="1086" height="556" alt="Orders API dashboard, service broken" src="https://github.com/user-attachments/assets/86cf60a5-73e7-45ab-b676-d31790eb7b56" />

**3. Slack notification**
*The explanation lands directly in Slack: problem summary, root cause, and proposed action, ready for review.*

<img width="947" height="445" alt="Slack summary of the problem, part 1" src="https://github.com/user-attachments/assets/3f50ebc0-f631-4e03-971d-74c269363c5a" />
<img width="1335" height="574" alt="Slack summary of the problem, part 2" src="https://github.com/user-attachments/assets/9f79c9e9-82d6-4977-8573-e06de392bd45" />

**4. Mission Control — approval pending**
*The suggested action waits here until a person decides. The platform explicitly states the target was resolved by the system, not chosen by the AI.*

<img width="981" height="497" alt="Mission Control dashboard, approve or reject" src="https://github.com/user-attachments/assets/abd8e089-33fb-4b53-b3fd-1331687b3252" />

**5. Mission Control — incident history**
*Every workflow execution, with status, start time, and end time, kept automatically.*

<img width="973" height="630" alt="Mission Control dashboard, incident history" src="https://github.com/user-attachments/assets/33497dc0-2f07-4de4-a651-8240d815d9e0" />

**6. Mission Control — costs**
*Real spend over the last 7 days, and which AWS services weigh most on the bill, in full transparency.*

<img width="975" height="580" alt="Mission Control dashboard, cost report" src="https://github.com/user-attachments/assets/a2660e9e-dd19-4405-91fb-49739f9ad10b" />

**7. Mission Control — runbook assistant**
*A real operational question, answered using the team's own documentation via RAG.*

<img width="973" height="630" alt="Mission Control dashboard, runbook assistant answer" src="https://github.com/user-attachments/assets/74fc61fd-c7ab-4e28-b083-7ac943106d91" />

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
