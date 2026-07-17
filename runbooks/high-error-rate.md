# Runbook: High Error Rate Response

## Trigger
Lambda error anomaly detection alarm fires, or 5xx error rate exceeds threshold.

## Step 1 — Check current Lambda error rate

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum \
  --query 'sort_by(Datapoints, &Timestamp)[*].{Time:Timestamp,Errors:Sum}' \
  --output table
```

## Step 2 — Check Lambda logs for the root cause

```bash
aws logs tail /aws/lambda/ai-ops-serverless-dev-anomaly-analyser \
  --since 30m \
  --format short

# Filter for ERROR level only
aws logs filter-log-events \
  --log-group-name /aws/lambda/ai-ops-serverless-dev-anomaly-analyser \
  --start-time $(date -d '30 minutes ago' +%s%3N) \
  --filter-pattern "ERROR" \
  --query 'events[*].message' \
  --output text
```

## Step 3 — Check Step Functions execution history

```bash
aws stepfunctions list-executions \
  --state-machine-arn $(cd terraform/environments/dev && terraform output -raw step_functions_arn) \
  --status-filter FAILED \
  --query 'executions[*].{Name:name,Status:status,StartDate:startDate}' \
  --output table
```

## Common Causes

| Cause | Fix |
|---|---|
| Bedrock throttling | Check Bedrock service quotas, add retry with backoff |
| Lambda timeout | Increase timeout in Terraform, check Bedrock model latency |
| IAM permission error | Run `aws iam simulate-principal-policy` to check permissions |
| Malformed event | Check CloudWatch Events pattern in EventBridge rule |

## Success Criteria
- Lambda error count returns to 0 in CloudWatch
- Step Functions executions completing successfully
