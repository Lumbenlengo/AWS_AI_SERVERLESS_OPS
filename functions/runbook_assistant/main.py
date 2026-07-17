# functions/runbook_assistant/main.py
#
# Answers operational questions using your Markdown runbooks as context.
#
# RAG pattern (Retrieval-Augmented Generation):
#   1. Engineer POSTs {"question": "How do I roll back an ECS deployment?"}
#   2. Lambda lists all .md files in the S3 runbooks bucket
#   3. Scores each file by keyword relevance to the question
#   4. Loads the top 2 most relevant runbooks as context
#   5. Sends: system prompt + runbook context + question → Bedrock Claude
#   6. Returns: structured JSON with the answer and source runbook names
#
# In production you would replace step 3-4 with a Bedrock Knowledge Base
# (vector embeddings + semantic search). This implementation uses keyword
# scoring to keep infrastructure cost near zero for a portfolio project.
#
# API contract:
#   POST /ask
#   Headers: x-api-key: <your-key>
#   Body: {"question": "string"}
#   Response: {"question": "string", "answer": "string", "sources": ["string"]}

import json
import boto3
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

BEDROCK_MODEL_ID     = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
AWS_REGION           = os.environ.get("AWS_REGION_NAME", "us-east-1")
RUNBOOKS_BUCKET_NAME = os.environ.get("RUNBOOKS_BUCKET_NAME", "")
ENVIRONMENT          = os.environ.get("ENVIRONMENT", "dev")

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
s3      = boto3.client("s3", region_name=AWS_REGION)

# Keyword map — maps runbook filenames to terms that indicate relevance
KEYWORD_MAP = {
    "deploy-rollback.md":   ["rollback", "deploy", "revert", "undo", "previous", "release", "version"],
    "high-error-rate.md":   ["error", "5xx", "500", "503", "slow", "timeout", "fail", "latency"],
    "cost-spike.md":        ["cost", "bill", "expensive", "budget", "spend", "charge", "price"],
    "incident-response.md": ["incident", "outage", "down", "alert", "on-call", "page", "escalate"],
}


def load_runbooks() -> dict:
    """Load all .md files from the S3 runbooks bucket. Returns {filename: content}."""
    if not RUNBOOKS_BUCKET_NAME:
        logger.warning("RUNBOOKS_BUCKET_NAME not set — answering without runbook context")
        return {}

    runbooks = {}
    try:
        objects = s3.list_objects_v2(Bucket=RUNBOOKS_BUCKET_NAME)
        for obj in objects.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".md"):
                body = s3.get_object(Bucket=RUNBOOKS_BUCKET_NAME, Key=key)
                runbooks[key] = body["Body"].read().decode("utf-8")
                logger.info(f"Loaded runbook: {key} ({len(runbooks[key])} chars)")
    except Exception as e:
        logger.warning(f"Could not load runbooks: {e}")

    return runbooks


def select_relevant(question: str, runbooks: dict) -> tuple:
    """
    Score each runbook by keyword overlap with the question.
    Returns (combined_context_string, list_of_source_filenames).
    """
    q = question.lower()
    scores = {}

    for filename, keywords in KEYWORD_MAP.items():
        if filename in runbooks:
            score = sum(1 for kw in keywords if kw in q)
            if score > 0:
                scores[filename] = score

    # Sort by score, take top 2
    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]

    # If no keyword match, use the first 2 runbooks as generic context
    if not top:
        top = [(k, 0) for k in list(runbooks.keys())[:2]]

    context_parts = []
    sources       = []
    for filename, _ in top:
        if filename in runbooks:
            context_parts.append(f"=== {filename} ===\n{runbooks[filename]}")
            sources.append(filename)

    return "\n\n".join(context_parts), sources


def call_bedrock(question: str, context: str) -> str:
    """Ask Bedrock Claude the question, optionally with runbook context."""
    system_prompt = (
        "You are an expert AWS DevOps engineer and SRE. "
        "Answer operational questions clearly, step-by-step, and concisely. "
        "When runbook documentation is provided, base your answer on it. "
        "If it does not cover the question, answer from your AWS expertise. "
        "Format multi-step answers with numbered steps."
    )

    user_content = (
        f"RUNBOOK DOCUMENTATION:\n{context}\n\nQUESTION: {question}"
        if context else
        f"QUESTION: {question}"
    )

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}]
    })

    response = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


def lambda_handler(event, context):
    """API Gateway proxy integration handler."""
    logger.info(f"Event: {json.dumps(event)}")

    # Parse body — handles both API Gateway proxy and direct Lambda invocation
    try:
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        elif isinstance(event.get("body"), dict):
            body = event["body"]
        else:
            body = event

        question = body.get("question", "").strip()
    except (json.JSONDecodeError, AttributeError):
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Invalid JSON in request body"})
        }

    if not question:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Missing 'question' field"})
        }

    if len(question) > 2000:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Question exceeds 2000 character limit"})
        }

    logger.info(f"Question: {question}")

    runbooks        = load_runbooks()
    context_str, sources = select_relevant(question, runbooks)
    logger.info(f"Using {len(sources)} runbook(s): {sources}")

    try:
        answer = call_bedrock(question, context_str)
        logger.info(f"Answer: {len(answer)} chars")
    except Exception as e:
        logger.error(f"Bedrock call failed: {e}", exc_info=True)
        return {
            "statusCode": 503,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "AI service temporarily unavailable", "question": question})
        }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps({
            "question":    question,
            "answer":      answer,
            "sources":     sources,
            "model":       BEDROCK_MODEL_ID,
            "environment": ENVIRONMENT
        })
    }
