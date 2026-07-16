# functions/cost_reporter/main.py
#
# Runs every morning at 8am UTC via EventBridge.
#
# Pipeline:
#   1. Query Cost Explorer for the last 7 days, grouped by AWS service
#   2. Compute: daily average, 7-day total, spend trend, top services
#   3. If average > threshold OR trend is significant: ask Bedrock to explain
#   4. Send a Slack summary with AI explanation and actionable advice
#   5. If over budget: also publish to SNS for email alert

import json
import boto3
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from collections import defaultdict

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BEDROCK_MODEL_ID     = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
AWS_REGION           = os.environ.get("AWS_REGION_NAME", "us-east-1")
SLACK_WEBHOOK_URL    = os.environ.get("SLACK_WEBHOOK_URL", "")
SNS_TOPIC_ARN        = os.environ.get("SNS_TOPIC_ARN", "")
COST_ALERT_THRESHOLD = float(os.environ.get("COST_ALERT_THRESHOLD", "10"))
ENVIRONMENT          = os.environ.get("ENVIRONMENT", "dev")

# Cost Explorer is a global service — must use us-east-1
ce      = boto3.client("ce",              region_name="us-east-1")
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
sns     = boto3.client("sns",             region_name=AWS_REGION)


def get_cost_data(days: int = 7) -> dict:
    """Fetch daily costs grouped by AWS service for the last N days."""
    end   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    response = ce.get_cost_and_usage(
        TimePeriod   = {"Start": start, "End": end},
        Granularity  = "DAILY",
        Metrics      = ["UnblendedCost"],
        GroupBy      = [{"Type": "DIMENSION", "Key": "SERVICE"}]
    )

    costs_by_date = {}
    for day in response.get("ResultsByTime", []):
        date = day["TimePeriod"]["Start"]
        costs_by_date[date] = {
            g["Keys"][0]: round(float(g["Metrics"]["UnblendedCost"]["Amount"]), 4)
            for g in day.get("Groups", [])
            if float(g["Metrics"]["UnblendedCost"]["Amount"]) > 0.001
        }
    return costs_by_date


def compute_summary(costs: dict) -> dict:
    """Compute totals, averages, trend, and top services."""
    daily_totals   = {date: round(sum(s.values()), 4) for date, s in costs.items()}
    service_totals = defaultdict(float)
    for services in costs.values():
        for svc, cost in services.items():
            service_totals[svc] += cost

    total_7d  = sum(daily_totals.values())
    avg_daily = total_7d / max(len(daily_totals), 1)
    top_svcs  = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)[:8]

    # Trend: last 3 days vs first 4 days
    sorted_dates = sorted(daily_totals.keys())
    if len(sorted_dates) >= 6:
        recent_avg = sum(daily_totals[d] for d in sorted_dates[-3:]) / 3
        older_avg  = sum(daily_totals[d] for d in sorted_dates[:4]) / 4
        trend_pct  = ((recent_avg - older_avg) / max(older_avg, 0.01)) * 100
    else:
        trend_pct = 0.0

    return {
        "total_7d":     round(total_7d, 2),
        "avg_daily":    round(avg_daily, 2),
        "threshold":    COST_ALERT_THRESHOLD,
        "exceeds":      avg_daily > COST_ALERT_THRESHOLD,
        "trend_pct":    round(trend_pct, 1),
        "daily_totals": daily_totals,
        "top_services": top_svcs,
        "environment":  ENVIRONMENT
    }


def call_bedrock_cost(summary: dict) -> str:
    """Ask Bedrock to explain the cost trend and suggest optimisations."""
    top_str   = "\n".join(f"  - {svc}: ${cost:.2f}" for svc, cost in summary["top_services"][:5])
    daily_str = "\n".join(f"  - {d}: ${t:.2f}" for d, t in sorted(summary["daily_totals"].items()))
    direction = "increasing" if summary["trend_pct"] > 5 else ("decreasing" if summary["trend_pct"] < -5 else "stable")

    prompt = f"""You are an AWS FinOps expert. Analyse this 7-day cost report and provide concise, actionable insights.

COST SUMMARY:
- 7-day total: ${summary['total_7d']}
- Daily average: ${summary['avg_daily']} (threshold: ${summary['threshold']})
- Trend: {direction} ({summary['trend_pct']:+.1f}% recent vs earlier this week)
- Environment: {ENVIRONMENT}

TOP SPENDERS:
{top_str}

DAILY BREAKDOWN:
{daily_str}

Provide:
1. Two sentences explaining the trend in plain English for a non-technical manager
2. Three specific, actionable steps to reduce spend on the highest-cost services
3. One sentence on whether this requires immediate action

Maximum 200 words total. Be direct."""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}]
    })
    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


def send_slack(message: str) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    payload = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL, data=payload,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            logger.info(f"Slack: {r.status}")
    except urllib.error.URLError as e:
        logger.error(f"Slack failed: {e}")


def send_sns_alert(summary: dict, ai_text: str) -> None:
    if not SNS_TOPIC_ARN or not summary["exceeds"]:
        return
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"[{ENVIRONMENT.upper()}] 🚨 Cost Alert: ${summary['avg_daily']:.2f}/day (threshold ${summary['threshold']:.2f})",
            Message=f"Daily average: ${summary['avg_daily']:.2f}\nThreshold: ${summary['threshold']:.2f}\n\n{ai_text}"
        )
    except Exception as e:
        logger.error(f"SNS failed: {e}")


def lambda_handler(event, context):
    """Triggered daily at 8am UTC by EventBridge."""
    logger.info(f"Cost reporter triggered: {json.dumps(event)}")

    try:
        costs   = get_cost_data(days=7)
        summary = compute_summary(costs)
        logger.info(f"avg=${summary['avg_daily']:.2f}, trend={summary['trend_pct']:+.1f}%, exceeds={summary['exceeds']}")

        if summary["exceeds"] or abs(summary["trend_pct"]) > 20:
            ai_text = call_bedrock_cost(summary)
        else:
            ai_text = (
                f"Cost is within budget (${summary['avg_daily']:.2f}/day vs "
                f"${summary['threshold']:.2f} threshold). Trend is stable. No action required."
            )

        trend_emoji = "📈" if summary["trend_pct"] > 5 else ("📉" if summary["trend_pct"] < -5 else "➡️")
        alert_emoji = "🚨" if summary["exceeds"] else "✅"
        top_str = "\n".join(f"  • {svc}: ${cost:.2f}" for svc, cost in summary["top_services"][:5])

        slack_msg = (
            f"{alert_emoji} *Daily AWS Cost Report — {ENVIRONMENT.upper()}*\n"
            f"*Status:* {'OVER BUDGET' if summary['exceeds'] else 'Within Budget'}\n"
            f"*7-Day Average:* ${summary['avg_daily']:.2f}/day (budget: ${summary['threshold']:.2f}/day)\n"
            f"*7-Day Total:* ${summary['total_7d']:.2f}\n"
            f"*Trend:* {trend_emoji} {summary['trend_pct']:+.1f}%\n\n"
            f"*Top Spenders:*\n{top_str}\n\n"
            f"*AI Analysis:*\n{ai_text}"
        )
        send_slack(slack_msg)
        send_sns_alert(summary, ai_text)

        return {
            "statusCode":  200,
            "avg_daily":   summary["avg_daily"],
            "threshold":   summary["threshold"],
            "exceeds":     summary["exceeds"],
            "trend_pct":   summary["trend_pct"],
            "ai_analysis": ai_text
        }

    except Exception as e:
        logger.error(f"Cost reporter failed: {e}", exc_info=True)
        send_slack(f"🚨 *Cost Reporter Error* ({ENVIRONMENT}): `{str(e)}`")
        raise
