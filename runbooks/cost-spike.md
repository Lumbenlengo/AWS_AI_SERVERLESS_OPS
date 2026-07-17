# Runbook: AWS Cost Spike Investigation

## Trigger
Daily cost reporter Lambda alerts when average daily spend exceeds the configured threshold.

## Step 1 — Identify top cost drivers

```bash
aws ce get-cost-and-usage \
  --time-period Start=$(date -d '7 days ago' +%Y-%m-%d),End=$(date +%Y-%m-%d) \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[*].Groups[*].{Service:Keys[0],Cost:Metrics.UnblendedCost.Amount}' \
  --output json | python3 -c "
import sys, json
data = json.load(sys.stdin)
totals = {}
for day in data:
  for g in day:
    totals[g['Service']] = totals.get(g['Service'], 0) + float(g['Cost'])
for svc, cost in sorted(totals.items(), key=lambda x: -x[1])[:10]:
  print(f'\${cost:8.2f}  {svc}')
"
```

## Step 2 — Check for runaway Lambda invocations

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum \
  --query 'sort_by(Datapoints, &Timestamp)[*].{Hour:Timestamp,Invocations:Sum}' \
  --output table
```

## Emergency Stop — Kill switch for runaway Lambda

```bash
# Set reserved concurrency to 0 — Lambda stops accepting invocations immediately
aws lambda put-function-concurrency \
  --function-name ai-ops-serverless-dev-cost-reporter \
  --reserved-concurrent-executions 0

# Re-enable after investigation
aws lambda delete-function-concurrency \
  --function-name ai-ops-serverless-dev-cost-reporter
```

## Common Causes

| Cause | Fix |
|---|---|
| Lambda in infinite retry loop | Set concurrency to 0, check DLQ |
| EventBridge rule firing too frequently | Check rule schedule expression |
| Bedrock model calls in tight loop | Add rate limiting, check retry logic |
| Step Functions executing thousands of times | Check EventBridge pattern specificity |
