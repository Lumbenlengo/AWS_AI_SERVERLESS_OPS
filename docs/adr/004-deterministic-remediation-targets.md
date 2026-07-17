# ADR 004 — The AI Never Chooses the Remediation Target

**Status:** Accepted
**Date:** 2026-07-09

---

## Context

Version 1 of the anomaly analyser asked the LLM to fill in a `resource` field:

```json
{ "resource": "The specific AWS resource name/ARN to act on, or empty string" }
```

This was a design flaw with two failure modes:

1. **Hallucination.** A CloudWatch alarm event carries only an alarm name and a
   free-text reason. The resource to act on is simply *not in the input* — so the
   model could only invent a plausible-looking `cluster/service` string. A human
   reviewing the Slack approval sees a confident, well-formatted target and
   approves an action against a resource nobody verified.

2. **Prompt injection.** The alarm `reason` field is untrusted free text that
   flows into the prompt. Anything that can influence an alarm description
   (resource names, deployment messages) could influence which resource the
   model names — and the model's output flowed directly into `ecs:UpdateService`
   with wildcard IAM permissions.

An LLM output that selects the target of an infrastructure mutation is an
unacceptable trust boundary, human approval gate or not: the human is approving
what the model *claims*, not what the system *verified*.

## Decision

Split responsibility along the trust boundary:

| Concern | Owner | Mechanism |
|---|---|---|
| **What happened & why** (explanation, urgency, next steps) | AI | Bedrock Claude, free to be creative |
| **What may be done** (action allowlist per alarm) | Infrastructure | `REMEDIATION_MAP` in Terraform |
| **What is acted on** (the resource) | Infrastructure | `REMEDIATION_MAP` in Terraform |
| **Whether it happens** | Human | `waitForTaskToken` approval |
| **Whether it *can* happen** | AWS IAM | tag condition `AIOpsManaged=true` |

`REMEDIATION_MAP` is a Terraform-managed, version-controlled mapping:

```json
{
  "ai-ops-serverless-dev-watch-demo-app-errors": {
    "resource": "ai-ops-serverless-dev-demo/ai-ops-serverless-dev-demo-app",
    "allowed_actions": ["restart_ecs_service", "log_only"]
  }
}
```

The analyser resolves the target from this map by alarm name. The model is told
which actions it may recommend; if it recommends anything else, the code forces
`log_only`. Unknown alarms always resolve to `log_only` with no target.

The remediator independently re-validates: action allowlist, strict resource
format regex, and — enforced by AWS itself, not our code — an IAM condition
limiting `ecs:UpdateService` / `autoscaling:UpdateAutoScalingGroup` to
resources tagged `AIOpsManaged=true`.

## Consequences

**Positive**
- Hallucinated or injected resource names are structurally impossible to act on.
- Adding a remediable workload is an explicit, reviewed Terraform change —
  an audit trail of *what the platform is allowed to touch*.
- The IAM tag condition means even a bug in the validation code cannot mutate
  an untagged resource. Defence in depth with independent layers.

**Negative**
- Less "magic": the platform cannot remediate a workload nobody registered.
  This is the point — implicit blast radius is how automation incidents happen.
- The map lives in Lambda env vars; at ~50+ registered workloads it should move
  to DynamoDB or AppConfig. Acceptable at demo scale.

**The principle**, generalised: *LLMs explain and recommend inside an
allowlist; deterministic systems select targets; humans approve; IAM enforces.*