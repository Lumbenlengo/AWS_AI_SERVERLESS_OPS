# Runbook: Deployment Rollback

## When to Use
Error rate spiked immediately after a new deployment. ECS tasks failing health checks after a new image was pushed.

## Step 1 — Confirm a deployment caused the incident

```bash
aws ecs describe-services \
  --cluster ai-ops-serverless-dev \
  --services ai-ops-serverless-dev-api \
  --query 'services[0].deployments[*].{Status:status,CreatedAt:createdAt,TaskDef:taskDefinition}' \
  --output table
```

## Step 2 — Identify the previous working task definition

```bash
CURRENT=$(aws ecs describe-services \
  --cluster ai-ops-serverless-dev \
  --services ai-ops-serverless-dev-api \
  --query 'services[0].taskDefinition' --output text)

FAMILY=$(echo $CURRENT | cut -d'/' -f2 | cut -d':' -f1)
REVISION=$(echo $CURRENT | cut -d':' -f2)
PREVIOUS=$((REVISION - 1))

echo "Rolling back from $REVISION to $PREVIOUS"
```

## Step 3 — Execute rollback

```bash
aws ecs update-service \
  --cluster ai-ops-serverless-dev \
  --service ai-ops-serverless-dev-api \
  --task-definition "${FAMILY}:${PREVIOUS}" \
  --force-new-deployment \
  --no-cli-pager

aws ecs wait services-stable \
  --cluster ai-ops-serverless-dev \
  --services ai-ops-serverless-dev-api

echo "Rollback complete"
```

## Step 4 — Verify recovery

```bash
for i in {1..5}; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://api.patriciolumbe.com/health)
  echo "Attempt $i: HTTP $STATUS"
  sleep 5
done
```

## Success Criteria
- HTTP 200 from /health for 5 consecutive checks
- Error rate below 0.1% in CloudWatch
- ECS service showing "ACTIVE" with desired count met
