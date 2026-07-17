# Makefile — Developer shortcuts for the AI Ops Serverless Platform

.PHONY: help init plan apply destroy test smoke logs ask cost-report trigger-workflow push

ENVIRONMENT  ?= dev
AWS_REGION   ?= us-east-1
TF_DIR       := terraform/environments/dev

help:
	@echo ""
	@echo "  AI Ops Serverless Platform — Commands"
	@echo "  ─────────────────────────────────────"
	@echo "  make init             terraform init"
	@echo "  make plan             terraform plan"
	@echo "  make apply            terraform apply"
	@echo "  make destroy          terraform destroy"
	@echo "  make test             run Lambda unit tests"
	@echo "  make smoke            test the runbook API endpoint"
	@echo "  make ask Q='...'      ask the runbook assistant a question"
	@echo "  make cost-report      trigger cost analysis now"
	@echo "  make trigger-workflow start Step Functions with test event"
	@echo "  make logs             tail anomaly analyser logs"
	@echo "  make push             git add, commit, push"
	@echo ""

init:
	cd $(TF_DIR) && terraform init

plan:
	cd $(TF_DIR) && terraform plan -var-file="terraform.tfvars" -no-color

apply:
	cd $(TF_DIR) && terraform apply -var-file="terraform.tfvars" -auto-approve

destroy:
	@read -p "Type 'yes' to destroy all resources: " c && [ "$$c" = "yes" ]
	cd $(TF_DIR) && terraform destroy -var-file="terraform.tfvars" -auto-approve

test:
	python3 -m pytest functions/ -v --tb=short 2>&1 || true

smoke:
	@API_URL=$$(cd $(TF_DIR) && terraform output -raw api_url 2>/dev/null) && \
	API_KEY=$$(aws secretsmanager get-secret-value \
		--secret-id ai-ops-serverless/$(ENVIRONMENT)/api-gateway/ops-key \
		--query SecretString --output text 2>/dev/null) && \
	echo "Testing: $$API_URL" && \
	curl -s -X POST "$$API_URL" \
		-H "Content-Type: application/json" \
		-H "x-api-key: $$API_KEY" \
		-d '{"question": "What is the rollback procedure?"}' | python3 -m json.tool

ask:
	@test -n "$(Q)" || (echo "Usage: make ask Q='How do I roll back?'" && exit 1)
	@API_URL=$$(cd $(TF_DIR) && terraform output -raw api_url 2>/dev/null) && \
	API_KEY=$$(aws secretsmanager get-secret-value \
		--secret-id ai-ops-serverless/$(ENVIRONMENT)/api-gateway/ops-key \
		--query SecretString --output text 2>/dev/null) && \
	curl -s -X POST "$$API_URL" \
		-H "Content-Type: application/json" \
		-H "x-api-key: $$API_KEY" \
		-d "{\"question\": \"$(Q)\"}" | \
	python3 -c "import sys,json; d=json.load(sys.stdin); print('\nAnswer:\n' + d.get('body','{}'))" 2>/dev/null || \
	curl -s -X POST "$$API_URL" \
		-H "Content-Type: application/json" \
		-H "x-api-key: $$API_KEY" \
		-d "{\"question\": \"$(Q)\"}" | python3 -m json.tool

cost-report:
	aws lambda invoke \
		--function-name ai-ops-serverless-$(ENVIRONMENT)-cost-reporter \
		--payload file://events/cost-reporter-trigger.json \
		--cli-binary-format raw-in-base64-out \
		--region $(AWS_REGION) \
		/tmp/cost-output.json && cat /tmp/cost-output.json | python3 -m json.tool

trigger-workflow:
	@SFN_ARN=$$(cd $(TF_DIR) && terraform output -raw step_functions_arn 2>/dev/null) && \
	echo "Starting workflow: $$SFN_ARN" && \
	aws stepfunctions start-execution \
		--state-machine-arn "$$SFN_ARN" \
		--input file://events/step-functions-input.json \
		--region $(AWS_REGION) | python3 -m json.tool

logs:
	aws logs tail /aws/lambda/ai-ops-serverless-$(ENVIRONMENT)-anomaly-analyser \
		--follow --since 5m --format short --region $(AWS_REGION)

push:
	git add --all
	git status --short
	git commit -m "chore: update ai-ops-serverless-platform"
	git push origin main
