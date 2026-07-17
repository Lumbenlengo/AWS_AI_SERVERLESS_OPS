# ADR 002 — Amazon Bedrock over Self-Hosted LLM

**Status:** Accepted  
**Date:** 2025-01-15  

## Context

The AI analysis requires a large language model. Options: host open-source LLM on EC2 GPU, or use Amazon Bedrock.

## Decision

Use Amazon Bedrock with Claude 3 Haiku for operational analysis tasks.

## Reasons

| Factor | Self-Hosted (g4dn.xlarge) | Amazon Bedrock |
|---|---|---|
| Monthly cost | ~$380/month (always-on GPU) | ~$0.01/month (100 invocations) |
| Latency | 2-5 seconds (cold) | 1-3 seconds |
| Maintenance | CUDA drivers, model updates, quantisation | None |
| Scaling | Manual EC2 resize | Automatic |
| Scope | AI project | Infrastructure project using AI |

This is an **infrastructure project that uses AI** — not an AI project. The correct scope is using a managed AI service so the project demonstrates infrastructure patterns: event-driven architecture, Step Functions orchestration, IAM least privilege, Terraform IaC.

## Consequences

- Bedrock API availability depends on AWS. Fallback: the anomaly analyser returns safe fallback JSON if Bedrock fails, so the Step Functions workflow continues
- Model behaviour can change across Claude versions. Mitigated by pinning the model ID in `terraform.tfvars`

**Interview answer:**
*"I used Bedrock rather than running my own model because this is an infrastructure project. My value is in the event-driven architecture, the human approval gate, the Terraform modules — not in GPU management. Bedrock costs $0.01/month at this invocation volume versus $380/month for a GPU instance."*

---

# ADR 003 — API Gateway over ALB for Runbook Assistant

**Status:** Accepted  
**Date:** 2025-01-15  

## Context

The runbook assistant needs an HTTPS endpoint. Both API Gateway and ALB can serve Lambda.

## Decision

Use API Gateway REST API with API key authentication and a usage plan.

## Why NOT ALB

ALB is the right choice for the application's main traffic (thousands of users, low latency requirement).

API Gateway adds capabilities ALB cannot provide:
- **API keys**: individual clients get their own key — revocable, auditable
- **Usage plans**: 1000 requests/day limit prevents runaway automation costs
- **Request throttling**: 10 requests/second burst limit per key
- **Stage variables**: different config for dev/staging/prod without code changes

The runbook assistant is an **operational tool** accessed by engineers and Slack bots — not end users. API key auth is appropriate. ALB would be over-engineered for this use case.

## Consequences

- API Gateway adds ~$3.50 per million requests vs $0.008/LCU-hour for ALB
- At 1000 requests/day: API Gateway costs ~$0.0035/month — negligible
- API keys stored in Secrets Manager so they can be rotated without code changes

**Interview answer:**
*"I chose API Gateway over ALB specifically because I needed API key authentication and usage plans. ALB cannot throttle individual API keys or enforce daily quotas. For this operational endpoint — accessed by engineers, not end users — API keys with a usage plan are exactly the right access control pattern. The ALB handles user traffic on the main application."*
