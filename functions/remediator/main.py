# functions/remediator/main.py
#
# Executes remediation ONLY after human approval in Step Functions.
#
# Defence in depth — three independent controls before anything mutates:
#   1. Action allowlist:   only restart_ecs_service | scale_asg | log_only
#   2. Resource validation: strict format check (no injection via resource string)
#   3. IAM tag condition:  the role can only touch resources tagged
#                          AIOpsManaged=true (enforced by AWS, not this code)
#
# Anything that fails validation degrades to log_only — never to an error,
# and never to a "best effort" mutation.

import json
import logging
import os
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AWS_REGION    = os.environ.get("AWS_REGION_NAME", "us-east-1")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
ENVIRONMENT   = os.environ.get("ENVIRONMENT", "dev")

ecs         = boto3.client("ecs", region_name=AWS_REGION)
autoscaling = boto3.client("autoscaling", region_name=AWS_REGION)
sns         = boto3.client("sns", region_name=AWS_REGION)

# ECS target: "cluster/service". ASG target: a bare ASG name.
ECS_RESOURCE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,255}/[a-zA-Z0-9_-]{1,255}$")
ASG_RESOURCE_RE = re.compile(r"^[a-zA-Z0-9._/-]{1,255}$")

MAX_ASG_INCREMENT = 1  # never scale by more than one instance per approval


def notify(subject: str, message: str) -> None:
    if not SNS_TOPIC_ARN:
        return
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)
    except Exception as e:  # noqa: BLE001
        logger.error(f"SNS publish failed: {e}")


# ─── ACTIONS ─────────────────────────────────────────────────────────────────

def log_only(resource: str, analysis: dict) -> dict:
    logger.info(f"log_only: no mutation performed. summary={analysis.get('summary', '')}")
    notify(
        subject=f"[{ENVIRONMENT.upper()}] AI Ops: logged, no action taken",
        message=f"Analysis: {analysis.get('summary', 'n/a')}\nResource: {resource or 'n/a'}",
    )
    return {"action": "log_only", "status": "success", "resource": resource}


def restart_ecs_service(resource: str) -> dict:
    """Force a new deployment of an ECS service. resource = 'cluster/service'."""
    if not ECS_RESOURCE_RE.match(resource or ""):
        logger.error(f"Invalid ECS resource format: '{resource}'")
        return {"action": "restart_ecs_service", "status": "failed",
                "error": f"invalid resource format: '{resource}' (expected cluster/service)"}

    cluster, service = resource.split("/", 1)
    try:
        response = ecs.update_service(cluster=cluster, service=service, forceNewDeployment=True)
        status = response.get("service", {}).get("status", "UNKNOWN")
        logger.info(f"ECS restart issued: {cluster}/{service} status={status}")
        notify(
            subject=f"[{ENVIRONMENT.upper()}] AI Ops: ECS service restarted",
            message=f"Forced new deployment of {service} in {cluster} after human approval.",
        )
        return {"action": "restart_ecs_service", "status": "success",
                "cluster": cluster, "service": service, "service_status": status}
    except Exception as e:  # noqa: BLE001
        logger.error(f"ECS restart failed: {e}")
        notify(
            subject=f"[{ENVIRONMENT.upper()}] AI Ops: ECS restart FAILED",
            message=f"update_service failed for {resource}: {e}",
        )
        return {"action": "restart_ecs_service", "status": "failed", "error": str(e)}


def scale_asg(resource: str) -> dict:
    """Increase an ASG's desired capacity by 1, respecting MaxSize."""
    if not ASG_RESOURCE_RE.match(resource or ""):
        logger.error(f"Invalid ASG resource format: '{resource}'")
        return {"action": "scale_asg", "status": "failed",
                "error": f"invalid resource format: '{resource}'"}

    try:
        described = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[resource])
        groups = described.get("AutoScalingGroups", [])
        if not groups:
            return {"action": "scale_asg", "status": "failed", "error": f"ASG '{resource}' not found"}

        current  = groups[0]["DesiredCapacity"]
        max_size = groups[0]["MaxSize"]

        if current >= max_size:
            logger.warning(f"ASG {resource} already at MaxSize={max_size} — skipping")
            notify(
                subject=f"[{ENVIRONMENT.upper()}] AI Ops: ASG scale skipped",
                message=f"{resource} is already at maximum capacity ({max_size}).",
            )
            return {"action": "scale_asg", "status": "skipped",
                    "reason": "at_max_size", "desired": current, "max": max_size}

        new_desired = min(current + MAX_ASG_INCREMENT, max_size)
        autoscaling.update_auto_scaling_group(AutoScalingGroupName=resource, DesiredCapacity=new_desired)
        logger.info(f"ASG {resource} scaled {current} -> {new_desired}")
        notify(
            subject=f"[{ENVIRONMENT.upper()}] AI Ops: ASG scaled",
            message=f"{resource} desired capacity {current} -> {new_desired} after human approval.",
        )
        return {"action": "scale_asg", "status": "success",
                "previous_desired": current, "new_desired": new_desired}
    except Exception as e:  # noqa: BLE001
        logger.error(f"ASG scale failed: {e}")
        return {"action": "scale_asg", "status": "failed", "error": str(e)}


# ─── HANDLER ─────────────────────────────────────────────────────────────────

ACTIONS = {
    "restart_ecs_service": lambda resource, analysis: restart_ecs_service(resource),
    "scale_asg":           lambda resource, analysis: scale_asg(resource),
    "log_only":            log_only,
}


def lambda_handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")

    action   = event.get("action", "log_only")
    resource = event.get("resource", "") or ""
    analysis = event.get("analysis", {}) or {}

    # Control 1: allowlist. Unknown/missing action degrades to log_only.
    if action not in ACTIONS:
        logger.warning(f"Unknown action '{action}' — degrading to log_only")
        action = "log_only"

    # Control 2: the analyser already restricted actions per-alarm; honour it
    # again here in case the payload was tampered with in transit.
    allowed = analysis.get("allowed_actions")
    if allowed and action not in allowed:
        logger.warning(f"Action '{action}' not in allowed_actions {allowed} — degrading to log_only")
        action = "log_only"

    result = ACTIONS[action](resource, analysis)
    logger.info(f"Remediation result: {json.dumps(result)}")
    return {"statusCode": 200, "result": result}
