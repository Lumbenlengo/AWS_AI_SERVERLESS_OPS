# functions/anomaly_analyser/main.py

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

# ═══════════════════════════════════════════════════════════════════════════
# BEDROCK CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

SLACK_WEBHOOK_URL    = os.environ.get("SLACK_WEBHOOK_URL", "")
SNS_TOPIC_ARN        = os.environ.get("SNS_TOPIC_ARN", "")
ENVIRONMENT          = os.environ.get("ENVIRONMENT", "dev")
MISSION_CONTROL_URL  = os.environ.get("MISSION_CONTROL_URL", "")

try:
    REMEDIATION_MAP = json.loads(os.environ.get("REMEDIATION_MAP", "{}"))
except json.JSONDecodeError:
    logger.error("REMEDIATION_MAP is not valid JSON — falling back to empty map")
    REMEDIATION_MAP = {}

VALID_ACTIONS   = {"restart_ecs_service", "scale_asg", "log_only"}
VALID_URGENCIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

URGENCY_EMOJI = {"LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴", "CRITICAL": "🚨"}

sns     = boto3.client("sns", region_name=AWS_REGION)
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)


# ═══════════════════════════════════════════════════════════════════════════
# BEDROCK / CLAUDE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

FALLBACK_ANALYSIS = {
    "summary": "AI analysis temporarily unavailable",
    "root_cause": "API service error — manual investigation required",
    "impact": "Unknown",
    "recommended_action": "log_only",
    "urgency": "MEDIUM",
    "confidence": "LOW",
    "next_steps": ["Review CloudWatch logs manually"],
}


def call_claude(prompt: str, max_tokens: int = 600) -> str:
    """
    Call Claude via Amazon Bedrock (Messages API format).
    On failure: returns safe fallback JSON (fail-safe design).
    """
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })

    try:
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        text = result.get("content", [{}])[0].get("text", "")
        logger.info(f"✓ Bedrock response received ({len(text)} chars)")
        return text
    except Exception as e:  # noqa: BLE001
        logger.error(f"Bedrock call failed: {e}", exc_info=True)
        return json.dumps(FALLBACK_ANALYSIS)


def extract_json(text: str) -> dict | None:
    """Extract the first {...} block from model output."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════

def send_slack(message: str) -> None:
    """Send alert to Slack webhook (optional)."""
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
            logger.info(f"Slack notification sent: {resp.status}")
    except urllib.error.URLError as e:
        logger.error(f"Slack notification failed: {e}")


def send_sns(subject: str, message: str) -> None:
    """Send alert via SNS (email fallback)."""
    if not SNS_TOPIC_ARN:
        return
    try:
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)
        logger.info(f"SNS notification sent: {subject[:50]}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"SNS publish failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ALARM ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def resolve_remediation(alarm_name: str) -> dict:
    """
    Deterministic lookup: which AWS resource does this alarm map to?
    This mapping is injected by Terraform and is the SOURCE OF TRUTH.
    The AI model CANNOT override this — it can only suggest allowed actions.
    """
    entry = REMEDIATION_MAP.get(alarm_name)
    if entry:
        return {
            "resource": entry.get("resource", ""),
            "allowed_actions": [a for a in entry.get("allowed_actions", []) if a in VALID_ACTIONS] or ["log_only"],
        }
    logger.warning(f"Alarm '{alarm_name}' not in REMEDIATION_MAP — defaulting to log_only")
    return {"resource": "", "allowed_actions": ["log_only"]}


def analyse_alarm(event: dict) -> dict:
    """
    Analyze a CloudWatch alarm using Claude via Amazon Bedrock.

    Slack behaviour: this function ONLY sends a Slack message when urgency
    is LOW (auto-logged, no approval needed). Anything else is left to
    notify_and_wait(), which sends exactly ONE clean message with the
    approval link — avoids two near-duplicate messages per alarm.
    """
    detail      = event.get("detail", {})
    alarm_name  = detail.get("alarmName", event.get("alarm_name", "Unknown Alarm"))
    alarm_state = detail.get("state", {}).get("value", "ALARM")
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

IMPORTANT: The remediation actions available for this specific alarm are: {remediation['allowed_actions']}
You MUST recommend ONLY one of those actions. Do NOT name any AWS resources — the platform
resolves the target itself from a deterministic map.

Return exactly this JSON structure:
{{
  "summary": "One sentence plain-English summary for a non-technical stakeholder",
  "root_cause": "Most likely technical root cause (brief)",
  "impact": "What users or the business experience right now",
  "recommended_action": "one of {remediation['allowed_actions']}",
  "urgency": "One of: LOW | MEDIUM | HIGH | CRITICAL",
  "confidence": "One of: LOW | MEDIUM | HIGH",
  "next_steps": ["Step 1 for the on-call engineer", "Step 2", "Step 3"]
}}"""

    raw      = call_claude(prompt)
    analysis = extract_json(raw)

    if analysis is None:
        logger.warning("Could not parse Claude JSON — using text as summary")
        analysis = dict(FALLBACK_ANALYSIS)
        analysis["summary"]    = raw[:300]
        analysis["root_cause"] = "AI response could not be parsed"

    # ──────────────────────────────────────────────────────────────────────
    # VALIDATION LAYER: AI's output is a SUGGESTION, not a COMMAND
    # ──────────────────────────────────────────────────────────────────────
    action = analysis.get("recommended_action", "log_only")
    if action not in remediation["allowed_actions"]:
        logger.warning(f"Model recommended disallowed action '{action}' — forcing log_only")
        analysis["recommended_action"] = "log_only"
        analysis["action_note"] = f"AI suggested '{action}' but it is not permitted for this alarm"

    if analysis.get("urgency") not in VALID_URGENCIES:
        analysis["urgency"] = "MEDIUM"

    # Resource ALWAYS comes from the map — never from the model
    analysis["resource"]        = remediation["resource"]
    analysis["allowed_actions"] = remediation["allowed_actions"]
    analysis["alarm_name"]      = alarm_name
    analysis["alarm_state"]     = alarm_state
    analysis["timestamp"]       = timestamp

    urgency_emoji = URGENCY_EMOJI.get(analysis["urgency"], "⚠️")

    # Only LOW urgency gets its own Slack message — short, informative,
    # no action needed. Everything else is handled by notify_and_wait().
    if analysis["urgency"] == "LOW":
        slack_msg = (
            f"{urgency_emoji} *{alarm_name}*  ·  {ENVIRONMENT.upper()}\n"
            f"Auto-logged, no action needed.\n"
            f"> {analysis.get('summary')}"
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


# ═══════════════════════════════════════════════════════════════════════════
# HUMAN APPROVAL PHASE
# ═══════════════════════════════════════════════════════════════════════════

def notify_and_wait(event: dict) -> dict:
    """
    Notify human via ONE clean Slack message + wait for approval.
    Step Functions pauses at ZERO COST during this wait.

    No task token or CLI command is shown in Slack — approval happens via
    the Mission Control link, keeping the message short and readable.
    """
    analysis   = event.get("analysis", {})
    alarm_name = analysis.get("alarm_name", "Unknown Alarm")
    urgency    = analysis.get("urgency", "MEDIUM")
    urgency_emoji = URGENCY_EMOJI.get(urgency, "⚠️")

    next_steps = analysis.get("next_steps", [])
    steps_block = "\n".join(f"   {i + 1}. {s}" for i, s in enumerate(next_steps)) if next_steps else ""

    mc_line = (
        f"👉 <{MISSION_CONTROL_URL}|Open Mission Control to approve or reject>"
        if MISSION_CONTROL_URL else
        "⚠️ Mission Control URL not configured — approve via AWS Console (Step Functions)."
    )

    message = (
        f"{urgency_emoji} *{alarm_name}*  ·  {ENVIRONMENT.upper()}  ·  needs approval\n"
        f"\n"
        f"*Summary*\n> {analysis.get('summary', 'N/A')}\n"
        f"\n"
        f"*Root cause*\n> {analysis.get('root_cause', 'N/A')}\n"
        f"\n"
        f"*Proposed fix:* `{analysis.get('recommended_action', 'log_only')}` "
        f"on `{analysis.get('resource') or 'N/A'}`\n"
        + (f"\n*Next steps*\n{steps_block}\n" if steps_block else "")
        + f"\n{mc_line}\n"
        f"⏰ Expires in 24 hours."
    )
    send_slack(message)
    send_sns(
        subject=f"[ACTION REQUIRED] AI Ops approval needed: {alarm_name}",
        message=f"Open Mission Control to approve or reject:\n{MISSION_CONTROL_URL}",
    )

    logger.info(f"Approval notification sent for: {alarm_name}")
    return {"status": "waiting_for_approval", "alarm_name": alarm_name}


# ═══════════════════════════════════════════════════════════════════════════
# LAMBDA HANDLER
# ═══════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """Main entry point for AWS Lambda."""
    logger.info(f"Event: {json.dumps(event)}")
    action = event.get("action", "analyse")

    try:
        if action == "notify_and_wait":
            return notify_and_wait(event)
        return analyse_alarm(event)
    except Exception as e:
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