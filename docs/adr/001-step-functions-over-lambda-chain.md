# ADR 001 — Step Functions over Lambda Chaining

**Status:** Accepted  
**Date:** 2025-01-15  
**Author:** Patricio Lumbe

---

## Context

The AI Ops remediation workflow requires four sequential steps:
1. Detect anomaly (CloudWatch alarm fires)
2. Analyse with AI (Bedrock Claude)
3. Notify a human and wait for approval
4. Execute remediation

The naive implementation puts all four steps inside one Lambda function.

---

## Options Considered

### Option A — Single Lambda (rejected)

```python
def lambda_handler(event, context):
    analysis = call_bedrock(event)
    send_slack(analysis)
    wait_for_human()   # impossible — 15 min timeout
    execute_fix()
```

Problems:
- Lambda maximum execution timeout is 15 minutes — cannot wait for human approval
- If step 3 fails, step 1 and 2 retry unnecessarily  
- No per-step retry logic
- No audit trail of which step failed and when
- Debugging requires reading one monolithic log stream

### Option B — Lambda chaining via SNS (rejected)

Each Lambda publishes to SNS which triggers the next Lambda.

Problems:
- No central execution visibility
- State must be passed through SNS message body — fragile
- Human approval requires a separate DynamoDB polling table
- Five separate CloudWatch log groups to correlate during an incident

### Option C — Step Functions Standard Workflow (chosen)

---

## Decision

Use AWS Step Functions Standard Workflow with the `waitForTaskToken` pattern for human approval.

The state machine definition lives in `terraform/modules/step_functions/main.tf`.
Changes to the workflow are version-controlled and reviewed in PRs.

---

## Consequences

**Positive:**
- Each state transition is independently retried with configurable backoff
- `waitForTaskToken` pauses at zero cost — Step Functions charges per transition, not per elapsed time
- Full execution history (inputs, outputs, durations, errors) visible in AWS Console for 90 days
- Adding a new step requires one new state in the ASL JSON — no architectural changes

**Negative:**
- Step Functions Standard costs $0.025 per 1,000 state transitions
- At ~100 incidents/month × 5 states each: ~$0.01/month — negligible
- The ASL JSON definition is verbose — a 6-state machine requires ~80 lines

**Interview answer:**
*"I chose Step Functions over a single Lambda because the workflow needs to pause for human approval — sometimes for hours. Lambda has a 15-minute timeout. With Step Functions waitForTaskToken, the workflow pauses at zero cost until the engineer responds. Every state transition is logged independently, so when a workflow fails I can see exactly which step failed without reading a monolithic log."*
