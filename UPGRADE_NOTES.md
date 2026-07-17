Upgrade Notes

These are the changes I made after going back through my AI Ops project and fixing the things that were either broken or just poorly designed. This is written the way I'd explain it to another student, not like release notes from a company.

Bugs that would have stopped deployment
There was a circular dependency between the monitoring, step_functions and lambda modules. Terraform couldn't resolve it because each module depended on another. I fixed it by moving the SNS topic into the root module and passing it into monitoring, so the dependency loop is gone.
I had aws_account_id = "" sitting in terraform.tfvars. That silently overrode the real account ID with an empty value. The account ID now always comes from aws_caller_identity, so there's nothing to configure manually.
I originally had my own email address and AWS account ID committed in the Terraform files. Those values now live in a gitignored terraform.tfvars, and I've included a .tfvars.example file instead.
My test suite was quietly testing the wrong Lambda. All four functions use a file called main.py, so Python cached the first import main and reused it for every test. That meant most of the tests weren't testing what they claimed to be. I switched to importlib so each Lambda is loaded under its own module name.
Monitoring fixes

There were a few monitoring issues that would have caused problems in production.

The Lambda error alarm didn't include a FunctionName dimension, so it counted errors from every Lambda in the account, including the platform itself.
The EventBridge rule wasn't filtering alarms, so it reacted to every CloudWatch alarm in the AWS account instead of only this project.

To fix this, I split alarms into two groups:

watch- alarms trigger the AI workflow.
selfmon- alarms only monitor the platform itself and send notifications.

This completely removes the possibility of the platform triggering itself in a feedback loop.

I also:

Removed duplicate EventBridge rules and IAM resources.
Gave EventBridge its own execution role instead of reusing the Step Functions role.
Added retries and an SQS dead-letter queue so failed events aren't silently lost.
Security changes

This was the part I spent the most time on.

The biggest problem was that the AI was responsible for deciding which resource to remediate. The CloudWatch alarm doesn't contain enough information to make that decision reliably, so the model was effectively guessing. That also meant the alarm's reason field could potentially influence what resource the AI chose.

I replaced that design completely.

There's now a Terraform-managed REMEDIATION_MAP which explicitly maps each alarm to the resources and actions that are allowed. The AI can only recommend actions from that predefined list. If the alarm isn't recognised, or the suggested action isn't allowed, the workflow automatically falls back to log_only.

The AI still explains the problem, but it never gets to decide what infrastructure it can touch.

Other security improvements include:

Giving every Lambda its own IAM role instead of sharing one.
Restricting the remediator to resources tagged AIOpsManaged=true.
Limiting Bedrock and SNS permissions to only the resources used by this project.
Removing the unused states:SendTaskSuccess permission.
Restricting the GitHub Actions role so iam:PassRole only works for this project's IAM roles.
Replacing the previous lstrip() JSON parsing with proper regex extraction.
Validating resource names and performing a second allowlist check inside the remediator.
CI/CD

I also stopped deploying everything manually from my laptop.

The GitHub Actions workflow now runs on every push and includes:

Ruff
Pytest
terraform fmt
terraform validate
TFLint
Checkov

For pull requests, Terraform generates a plan and posts it as a PR comment so I can review it before merging.

Deployments to AWS require approval through a protected GitHub environment, so nothing gets applied automatically just because I pushed a commit.

Authentication uses GitHub OIDC, which means there are no long-lived AWS access keys stored in GitHub.

I also added a separate destroy workflow. Before anything can be destroyed it:

Requires manually triggering the workflow.
Requires typing a confirmation phrase.
Records who requested the destroy and why.
Generates a destroy plan for review.
Requires approval through a protected environment.
Applies the exact reviewed plan instead of generating a new one.
Demo application

I added a small FastAPI application that runs on ECS Fargate Spot. It's disabled by default so it doesn't cost anything unless I'm demonstrating the project.

It exposes a /chaos/on endpoint that intentionally breaks the application and publishes CloudWatch metrics. Since the fault only exists in the running task, restarting the ECS service through the workflow genuinely fixes the application. The recovery isn't simulated—it's the same process the platform would use in a real deployment.

Refactoring
Replaced four almost identical Terraform Lambda blocks with a single for_each.
Rebuilt the CloudWatch dashboard so it generates widgets from the Lambda list instead of defining each one manually.
Rewrote the README to explain the architecture, deployment process and design trade-offs more clearly.
Manual changes still needed
api_gateway/main.tf
The deployment trigger hash doesn't include the health endpoint resources, so changing that endpoint won't trigger a redeployment. Those resources still need to be added.
Remove the unused Access-Control-Allow-Origin: * response header from the runbook Lambda.
step_functions/main.tf

No functional changes are needed. I just want to update the comments to make it clear that remediation targets now come from REMEDIATION_MAP rather than being selected by the model. 