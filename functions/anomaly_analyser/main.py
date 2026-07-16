# functions/anomaly_analyser/main.py
#
# FIXED vs previous version — three security/correctness issues:
#
# 1. THE AI NO LONGER CHOOSES THE REMEDIATION TARGET (ADR 004).
#    The alarm event contains only a name and a reason string — the model was
#    being asked to "fill in" the resource ARN, which it could only hallucinate.
#    Now the target comes from REMEDIATION_MAP (Terraform-managed, deterministic):
#        alarm name -> { resource, allowed_actions }
#    The AI recommends an action; the code validates it against allowed_actions
#    and attaches the resource itself. Unknown alarm -> log_only, always.
#
# 2. ROBUST JSON EXTRACTION. The old fence-stripping used lstrip("```json"),
#    which strips a CHARACTER SET, not a prefix — a latent bug. Now we extract
#    the first balanced {...} block with a regex.
#
# 3. PROMPT-INJECTION AWARENESS. The alarm 'reason' is untrusted free text
#    that flows into the prompt. Because the model can no longer name resources
#    and its action choice is allowlist-validated, injected instructions cannot
#    redirect remediation. The reason is also length-capped before prompting.

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BEDROCK_MODEL_ID  = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
AWS_REGION        = os.environ.get("AWS_REGION_NAME", "us-east-1")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
SNS_TOPIC_ARN     = os.environ.get("SNS_TOPIC_ARN", "")
ENVIRONMENT       = os.environ.get("ENVIRONMENT", "dev")

# Deterministic alarm -> remediation target mapping, injected by Terraform.
# Example: {"myproj-dev-watch-demo-app-errors":
#             {"resource": "demo-cluster/demo-service",
#              "allowed_actions": ["restart_ecs_service", "log_only"]}}
try:
    REMEDIATION_MAP = json.loads(os.environ.get("REMEDIATION_MAP", "{}"))
except json.JSONDecodeError:
    logger.error("REMEDIATION_MAP is not valid JSON — falling back to empty map")
    REMEDIATION_MAP = {}

VALID_ACTIONS   = {"restart_ecs_service", "scale_asg", "log_only"}
VALID_URGENCIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
sns     = boto3.client("sns", region_name=AWS_REGION)


# ─── BEDROCK ──────────────────────────────────────────────────────────────────

FALLBACK_ANALYSIS = {
    "summary": "AI analysis temporarily unavailable",
    "root_cause": "Bedrock service error — manual investigation required",
    "impact": "Unknown",
    "recommended_action": "log_only",
    "urgency": "MEDIUM",
    "confidence": "LOW",
    "next_steps": ["Review CloudWatch logs manually"],
}


def call_bedrock(prompt: str, max_tokens: int = 600) -> str:
    """Call Bedrock Claude; on failure return safe fallback JSON so Step
    Functions always receives a parseable, non-actioning response."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    try:
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]
    except Exception as e:  # noqa: BLE001 — deliberate catch-all: fail safe, never fail open
        logger.error(f"Bedrock call failed: {e}")
        return json.dumps(FALLBACK_ANALYSIS)


def extract_json(text: str) -> dict | None:
    """Extract the first {...} block from model output. Handles bare JSON,
    fenced JSON, and preamble text. Returns None if nothing parses."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────

def send_slack(message: str) -> None:
    if not SLACK_WEBHOOK_URL:
        logger.info("SLACK_WEBHOOK_URL not set — skipping Slack notification")
        return
    payload = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info(f"Slack: {resp.status}")
    except urllib.error.URLError as e:
        logger.error(f"Slack failed: {e}")


def send_sns(subject: str, message: str) -> None:
    if not SNS_TOPIC_ARN:
        return
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)
    except Exception as e:  # noqa: BLE001
        logger.error(f"SNS publish failed: {e}")


# ─── ANALYSE ──────────────────────────────────────────────────────────────────

def resolve_remediation(alarm_name: str) -> dict:
    """Deterministic lookup: which resource does this alarm map to, and what
    is the AI allowed to recommend for it? Unknown alarms get log_only."""
    entry = REMEDIATION_MAP.get(alarm_name)
    if entry:
        return {
            "resource": entry.get("resource", ""),
            "allowed_actions": [a for a in entry.get("allowed_actions", []) if a in VALID_ACTIONS] or ["log_only"],
        }
    return {"resource": "", "allowed_actions": ["log_only"]}


def analyse_alarm(event: dict) -> dict:
    detail      = event.get("detail", {})
    alarm_name  = detail.get("alarmName", event.get("alarm_name", "Unknown Alarm"))
    alarm_state = detail.get("state", {}).get("value", "ALARM")
    # Untrusted free text — cap length before it enters the prompt
    reason      = str(detail.get("state", {}).get("reason", "No reason provided"))[:1500]
    timestamp   = datetime.now(timezone.utc).isoformat()

    remediation = resolve_remediation(alarm_name)
    logger.info(
        f"Analysing: {alarm_name} | state={alarm_state} | "
        f"target={remediation['resource'] or 'none'} | allowed={remediation['allowed_actions']}"
    )

    prompt = f"""You are a senior AWS Site Reliability Engineer responding to a CloudWatch alarm.
Analyse this alarm and return ONLY a valid JSON object. No markdown, no preamble.

ALARM:
- Name: {alarm_name}
- State: {alarm_state}
- Reason: {reason}
- Environment: {ENVIRONMENT}
- Time: {timestamp}

The remediation actions available for this specific alarm are: {remediation['allowed_actions']}
You may only recommend one of those. Do not name any AWS resources — the platform
resolves the target itself.

Return exactly this structure:
{{
  "summary": "One sentence plain-English summary for a non-technical stakeholder",
  "root_cause": "Most likely technical root cause",
  "impact": "What users or the business experience right now",
  "recommended_action": "one of {remediation['allowed_actions']}",
  "urgency": "One of: LOW | MEDIUM | HIGH | CRITICAL",
  "confidence": "One of: LOW | MEDIUM | HIGH",
  "next_steps": ["Step 1 for the on-call engineer", "Step 2", "Step 3"]
}}"""

    raw      = call_bedrock(prompt)
    analysis = extract_json(raw)

    if analysis is None:
        logger.warning("Could not parse Bedrock JSON — using text as summary")
        analysis = dict(FALLBACK_ANALYSIS)
        analysis["summary"]    = raw[:300]
        analysis["root_cause"] = "AI response could not be parsed"

    # ── Validation layer: the model's output is a SUGGESTION, not a command ──
    action = analysis.get("recommended_action", "log_only")
    if action not in remediation["allowed_actions"]:
        logger.warning(f"Model recommended disallowed action '{action}' — forcing log_only")
        analysis["recommended_action"] = "log_only"
        analysis["action_note"] = f"AI suggested '{action}' but it is not permitted for this alarm"

    if analysis.get("urgency") not in VALID_URGENCIES:
        analysis["urgency"] = "MEDIUM"

    # The resource ALWAYS comes from the map — never from the model
    analysis["resource"]        = remediation["resource"]
    analysis["allowed_actions"] = remediation["allowed_actions"]
    analysis["alarm_name"]      = alarm_name
    analysis["alarm_state"]     = alarm_state
    analysis["timestamp"]       = timestamp

    urgency_emoji = {"LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴", "CRITICAL": "🚨"}.get(analysis["urgency"], "⚠️")
    slack_msg = (
        f"{urgency_emoji} *CloudWatch Alarm: {alarm_name}* | {ENVIRONMENT.upper()}\n"
        f"*Urgency:* {analysis['urgency']}\n"
        f"*Summary:* {analysis.get('summary')}\n"
        f"*Root Cause:* {analysis.get('root_cause')}\n"
        f"*Recommended Action:* `{analysis['recommended_action']}` on `{analysis['resource'] or 'n/a'}`\n"
        f"*Next Steps:*\n"
        + "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(analysis.get("next_steps", [])))
    )
    send_slack(slack_msg)
    send_sns(
        subject=f"[{ENVIRONMENT.upper()}] {urgency_emoji} Alarm: {alarm_name}",
        message=(
            f"{analysis.get('summary')}\n\nRoot Cause: {analysis.get('root_cause')}"
            f"\n\nAction: {analysis['recommended_action']} on {analysis['resource'] or 'n/a'}"
        ),
    )

    logger.info(f"Analysis complete: urgency={analysis['urgency']} action={analysis['recommended_action']}")
    return analysis


# ─── NOTIFY AND WAIT ─────────────────────────────────────────────────────────

def notify_and_wait(event: dict) -> dict:
    """Send the approval request (with task token commands) to Slack + SNS,
    then return. Step Functions pauses at zero cost until the human responds."""
    task_token = event.get("taskToken", "")
    analysis   = event.get("analysis", {})
    alarm_name = analysis.get("alarm_name", "Unknown Alarm")

    approve_cmd = (
        "aws stepfunctions send-task-success "
        f"--task-token '{task_token}' "
        '--task-output \'{"approved": true}\''
    )
    reject_cmd = (
        "aws stepfunctions send-task-success "
        f"--task-token '{task_token}' "
        '--task-output \'{"approved": false}\''
    )

    message = (
        f"🤖 *AI Ops: Human Approval Required*\n"
        f"*Alarm:* `{alarm_name}` ({ENVIRONMENT.upper()})\n"
        f"*AI Summary:* {analysis.get('summary', 'N/A')}\n"
        f"*Root Cause:* {analysis.get('root_cause', 'N/A')}\n"
        f"*Urgency:* {analysis.get('urgency', 'UNKNOWN')}\n"
        f"*Proposed Action:* `{analysis.get('recommended_action', 'log_only')}`\n"
        f"*Target (resolved by platform, not AI):* `{analysis.get('resource') or 'N/A'}`\n\n"
        f"✅ *To APPROVE (execute the fix):*\n```{approve_cmd}```\n\n"
        f"❌ *To REJECT (no action):*\n```{reject_cmd}```\n\n"
        f"⏰ This request expires in 24 hours."
    )
    send_slack(message)
    send_sns(
        subject=f"[ACTION REQUIRED] AI Ops approval needed: {alarm_name}",
        message=f"Approve:\n{approve_cmd}\n\nReject:\n{reject_cmd}",
    )

    logger.info(f"Approval notification sent for: {alarm_name}")
    return {"status": "waiting_for_approval", "alarm_name": alarm_name}


# ─── HANDLER ─────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")
    action = event.get("action", "analyse")

    try:
        if action == "notify_and_wait":
            return notify_and_wait(event)
        return analyse_alarm(event)
    except Exception as e:  # noqa: BLE001 — contract with Step Functions: never raise
        logger.error(f"Handler failed: {e}", exc_info=True)
        return {
            "summary": f"Handler error: {e}",
            "recommended_action": "log_only",
            "urgency": "MEDIUM",
            "resource": "",
            "confidence": "LOW",
            "alarm_name": event.get("detail", {}).get("alarmName", "unknown"),
            "error": str(e),
        }