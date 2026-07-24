# functions/anomaly_analyser/main.py.anthropic-api
#
# DEVELOPMENT VERSION: Uses Anthropic API Direct (Claude 3.5 Sonnet)
# For rapid iteration and testing (no Bedrock access needed)
#
# SAME security features as Bedrock version:
# - Deterministic remediation mapping (ADR 004)
# - Robust JSON extraction
# - Prompt-injection resistance
#
# NOTE: For production, use Bedrock version (main.py)
# This version is for developers who want to iterate quickly

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
# ANTHROPIC API CONFIGURATION (Development)
# ═══════════════════════════════════════════════════════════════════════════
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # sk-ant-v0-...
ANTHROPIC_MODEL   = "claude-3-5-sonnet-20241022"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

AWS_REGION        = os.environ.get("AWS_REGION_NAME", "us-east-1")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
SNS_TOPIC_ARN     = os.environ.get("SNS_TOPIC_ARN", "")
ENVIRONMENT       = os.environ.get("ENVIRONMENT", "dev")

try:
    REMEDIATION_MAP = json.loads(os.environ.get("REMEDIATION_MAP", "{}"))
except json.JSONDecodeError:
    logger.error("REMEDIATION_MAP is not valid JSON — falling back to empty map")
    REMEDIATION_MAP = {}

VALID_ACTIONS   = {"restart_ecs_service", "scale_asg", "log_only"}
VALID_URGENCIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

sns = boto3.client("sns", region_name=AWS_REGION)


# ═══════════════════════════════════════════════════════════════════════════
# ANTHROPIC API / CLAUDE INTEGRATION
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
    Call Claude 3.5 Sonnet via Anthropic API Direct.
    
    Benefits (development/testing):
    ✓ No AWS account setup required for Bedrock
    ✓ Immediate access (no approval process)
    ✓ Easy to iterate on prompts
    ✓ Fast response times
    ✓ Lower latency for development
    
    WARNING: For production, use Bedrock (VPC-integrated, more secure).
    
    On failure: returns safe fallback JSON (fail-safe design).
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set — cannot call Claude")
        return json.dumps(FALLBACK_ANALYSIS)
    
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })
    
    try:
        req = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=body.encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            text = result.get("content", [{}])[0].get("text", "")
            logger.info(f"✓ Claude API response received ({len(text)} chars)")
            return text
    except Exception as e:  # noqa: BLE001
        logger.error(f"Claude API call failed: {e}")
        return json.dumps(FALLBACK_ANALYSIS)


def extract_json(text: str) -> dict | None:
    """Extract the first {...} block from model output.
    Handles bare JSON, fenced JSON, and preamble text."""
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
    Which actions are allowed?
    
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
    Analyze a CloudWatch alarm using Claude via Anthropic API.
    
    Flow:
    1. Extract alarm details from event
    2. Look up allowed remediation actions (from Terraform map)
    3. Call Claude with constrained prompt (no resource naming)
    4. Validate Claude's recommendation against allowlist
    5. Return analysis + Slack notification
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

    # Constrained prompt: Claude can only suggest from allowed_actions
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

    # Call Anthropic API (development)
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

    # Format Slack notification
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


# ═══════════════════════════════════════════════════════════════════════════
# HUMAN APPROVAL PHASE
# ═══════════════════════════════════════════════════════════════════════════

def notify_and_wait(event: dict) -> dict:
    """
    Notify human via Slack/SNS and wait for approval.
    Step Functions pauses at ZERO COST during this wait.
    """
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
        f"*Target (resolved by platform):* `{analysis.get('resource') or 'N/A'}`\n\n"
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
    except Exception as e:  # noqa: BLE001
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