# functions/tests/test_all.py
#
# FIXED: All anomaly_analyser tests now mock call_claude (not call_bedrock)
# because the deployed code uses Anthropic API Direct, not Bedrock.
#
# The suite loads each Lambda's main.py under a unique module name with
# importlib, ensuring Python doesn't cache modules across test classes.
#
# No real AWS calls, no cost. Run: pytest functions/tests/ -v

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Env vars must exist before the modules are imported (they read env at import)
os.environ.update({
    "BEDROCK_MODEL_ID":      "anthropic.claude-3-haiku-20240307-v1:0",
    "AWS_REGION_NAME":       "us-east-1",
    "SLACK_WEBHOOK_URL":     "",
    "SNS_TOPIC_ARN":         "",
    "ENVIRONMENT":           "test",
    "COST_ALERT_THRESHOLD":  "10",
    "RUNBOOKS_BUCKET_NAME":  "test-bucket",
    "AWS_DEFAULT_REGION":    "us-east-1",
    "AWS_ACCESS_KEY_ID":     "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "REMEDIATION_MAP": json.dumps({
        "test-watch-demo-app-errors": {
            "resource": "demo-cluster/demo-service",
            "allowed_actions": ["restart_ecs_service", "log_only"],
        }
    }),
})

FUNCTIONS_DIR = Path(__file__).resolve().parent.parent


def load_lambda(name: str):
    """Load functions/<name>/main.py under a unique module name."""
    path = FUNCTIONS_DIR / name / "main.py"
    spec = importlib.util.spec_from_file_location(f"{name}_main", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{name}_main"] = module
    spec.loader.exec_module(module)
    return module


analyser   = load_lambda("anomaly_analyser")
assistant  = load_lambda("runbook_assistant")
remediator = load_lambda("remediator")

os.environ.update({
    "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123:stateMachine:test",
    "RUNBOOK_LAMBDA_ARN": "arn:aws:lambda:us-east-1:123:function:runbook",
    "CONSOLE_KEY": "test-console-key",
})
console = load_lambda("mission_control")


# ─────────────────────────────────────────────────────────────────────────────
# ANOMALY ANALYSER
# ─────────────────────────────────────────────────────────────────────────────

GOOD_ANALYSIS = json.dumps({
    "summary": "Lambda errors spiked due to Bedrock throttling",
    "root_cause": "Bedrock rate limit exceeded during peak traffic",
    "impact": "5% of AI analysis requests are failing",
    "recommended_action": "log_only",
    "urgency": "MEDIUM",
    "confidence": "HIGH",
    "next_steps": ["Check Bedrock service quotas", "Review retry logic"],
})


def make_alarm_event(alarm_name="test-watch-demo-app-errors"):
    return {
        "detail-type": "CloudWatch Alarm State Change",
        "source": "aws.cloudwatch",
        "detail": {
            "alarmName": alarm_name,
            "state": {"value": "ALARM", "reason": "Error rate exceeded threshold"},
        },
    }


class TestAnomalyAnalyser:

    def test_analyse_alarm_returns_structured_dict(self):
        """✅ FIXED: Using call_claude (Anthropic API) instead of call_bedrock"""
        with patch.object(analyser, "call_claude", return_value=GOOD_ANALYSIS), \
             patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.analyse_alarm(make_alarm_event())

        assert result["alarm_name"] == "test-watch-demo-app-errors"
        assert result["urgency"] == "MEDIUM"
        assert "recommended_action" in result
        assert "timestamp" in result

    def test_resource_comes_from_map_not_model(self):
        """ADR 004: even if the model names a resource, the map wins.
        ✅ FIXED: Using call_claude instead of call_bedrock"""
        model_output = json.dumps({**json.loads(GOOD_ANALYSIS),
                                   "resource": "evil-cluster/evil-service",
                                   "recommended_action": "restart_ecs_service"})
        with patch.object(analyser, "call_claude", return_value=model_output), \
             patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.analyse_alarm(make_alarm_event())

        assert result["resource"] == "demo-cluster/demo-service"

    def test_unknown_alarm_degrades_to_log_only(self):
        """✅ FIXED: Using call_claude instead of call_bedrock"""
        model_output = json.dumps({**json.loads(GOOD_ANALYSIS),
                                   "recommended_action": "restart_ecs_service"})
        with patch.object(analyser, "call_claude", return_value=model_output), \
             patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.analyse_alarm(make_alarm_event("some-unmapped-alarm"))

        assert result["recommended_action"] == "log_only"
        assert result["resource"] == ""

    def test_disallowed_action_is_forced_to_log_only(self):
        """✅ FIXED: Using call_claude instead of call_bedrock"""
        model_output = json.dumps({**json.loads(GOOD_ANALYSIS),
                                   "recommended_action": "scale_asg"})  # not allowed for this alarm
        with patch.object(analyser, "call_claude", return_value=model_output), \
             patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.analyse_alarm(make_alarm_event())

        assert result["recommended_action"] == "log_only"

    def test_handles_malformed_claude_json(self):
        """✅ FIXED: Using call_claude instead of call_bedrock"""
        with patch.object(analyser, "call_claude", return_value="Sorry, I cannot help."), \
             patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.analyse_alarm(make_alarm_event())

        assert result["recommended_action"] == "log_only"
        assert result["confidence"] == "LOW"

    def test_handles_fenced_json(self):
        """✅ FIXED: Using call_claude instead of call_bedrock"""
        fenced = f"Here is the analysis:\n```json\n{GOOD_ANALYSIS}\n```"
        with patch.object(analyser, "call_claude", return_value=fenced), \
             patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.analyse_alarm(make_alarm_event())

        assert result["urgency"] == "MEDIUM"
        assert result["root_cause"].startswith("Bedrock rate limit")

    def test_notify_and_wait_returns_correct_status(self):
        with patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.notify_and_wait({
                "taskToken": "fake-token-123",
                "analysis": {"alarm_name": "test-alarm", "summary": "Test",
                             "recommended_action": "log_only", "urgency": "HIGH", "resource": ""},
            })
        assert result["status"] == "waiting_for_approval"
        assert result["alarm_name"] == "test-alarm"

    def test_handler_never_raises(self):
        """✅ FIXED: Using call_claude instead of call_bedrock"""
        with patch.object(analyser, "call_claude", side_effect=Exception("total failure")), \
             patch.object(analyser, "send_slack"), patch.object(analyser, "send_sns"):
            result = analyser.lambda_handler({"bad": "event"}, {})
        assert isinstance(result, dict)
        assert "recommended_action" in result


# ─────────────────────────────────────────────────────────────────────────────
# RUNBOOK ASSISTANT
# ─────────────────────────────────────────────────────────────────────────────

class TestRunbookAssistant:

    def _event(self, question):
        return {"httpMethod": "POST", "body": json.dumps({"question": question})}

    def test_returns_200_with_answer(self):
        with patch.object(assistant, "call_bedrock", return_value="1. Do X. 2. Do Y."), \
             patch.object(assistant, "load_runbooks", return_value={}):
            result = assistant.lambda_handler(self._event("How do I roll back?"), {})
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "answer" in body and "question" in body

    def test_returns_400_for_missing_question(self):
        result = assistant.lambda_handler({"httpMethod": "POST", "body": "{}"}, {})
        assert result["statusCode"] == 400

    def test_returns_400_for_empty_question(self):
        result = assistant.lambda_handler(self._event("  "), {})
        assert result["statusCode"] == 400

    def test_returns_400_for_too_long_question(self):
        result = assistant.lambda_handler(self._event("x" * 2001), {})
        assert result["statusCode"] == 400

    def test_returns_503_on_bedrock_failure(self):
        with patch.object(assistant, "call_bedrock", side_effect=Exception("down")), \
             patch.object(assistant, "load_runbooks", return_value={}):
            result = assistant.lambda_handler(self._event("How do I deploy?"), {})
        assert result["statusCode"] == 503

    def test_direct_invocation_works(self):
        with patch.object(assistant, "call_bedrock", return_value="Step 1."), \
             patch.object(assistant, "load_runbooks", return_value={}):
            result = assistant.lambda_handler({"question": "How do I check costs?"}, {})
        assert result["statusCode"] == 200

    def test_select_relevant_runbooks_by_keyword(self):
        runbooks = {
            "deploy-rollback.md": "# Deploy Rollback\n\nSteps...",
            "high-error-rate.md": "# High Error Rate\n\nSteps...",
            "cost-spike.md": "# Cost Spike\n\nSteps...",
        }
        _, sources = assistant.select_relevant("how do I roll back a deployment", runbooks)
        assert "deploy-rollback.md" in sources

    def test_select_relevant_falls_back(self):
        runbooks = {"deploy-rollback.md": "content", "cost-spike.md": "content2"}
        _, sources = assistant.select_relevant("unrelated quantum physics question", runbooks)
        assert len(sources) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# REMEDIATOR
# ─────────────────────────────────────────────────────────────────────────────

class TestRemediator:

    def test_log_only_returns_success(self):
        with patch.object(remediator, "notify"):
            result = remediator.log_only("", {"summary": "Test"})
        assert result["action"] == "log_only"
        assert result["status"] == "success"

    def test_handler_defaults_to_log_only(self):
        with patch.object(remediator, "notify"):
            result = remediator.lambda_handler(
                {"action": "unknown_action", "resource": "", "analysis": {}}, {})
        assert result["statusCode"] == 200
        assert result["result"]["action"] == "log_only"

    def test_handler_honours_allowed_actions(self):
        """Even a valid action is refused if the analysis didn't allow it."""
        with patch.object(remediator, "notify"):
            result = remediator.lambda_handler({
                "action": "restart_ecs_service",
                "resource": "c/s",
                "analysis": {"allowed_actions": ["log_only"]},
            }, {})
        assert result["result"]["action"] == "log_only"

    def test_restart_ecs_parses_cluster_service_format(self):
        mock_ecs = MagicMock()
        mock_ecs.update_service.return_value = {"service": {"status": "ACTIVE"}}
        with patch.object(remediator, "ecs", mock_ecs), patch.object(remediator, "notify"):
            result = remediator.restart_ecs_service("my-cluster/my-service")
        mock_ecs.update_service.assert_called_once_with(
            cluster="my-cluster", service="my-service", forceNewDeployment=True)
        assert result["status"] == "success"

    def test_restart_ecs_rejects_bad_format(self):
        mock_ecs = MagicMock()
        with patch.object(remediator, "ecs", mock_ecs), patch.object(remediator, "notify"):
            result = remediator.restart_ecs_service("no-slash-here")
        mock_ecs.update_service.assert_not_called()
        assert result["status"] == "failed"

    def test_restart_ecs_handles_aws_error(self):
        mock_ecs = MagicMock()
        mock_ecs.update_service.side_effect = Exception("ServiceNotFoundException")
        with patch.object(remediator, "ecs", mock_ecs), patch.object(remediator, "notify"):
            result = remediator.restart_ecs_service("bad-cluster/bad-service")
        assert result["status"] == "failed"
        assert "error" in result

    def test_scale_asg_increments_desired_by_one(self):
        mock_asg = MagicMock()
        mock_asg.describe_auto_scaling_groups.return_value = {
            "AutoScalingGroups": [{"DesiredCapacity": 3, "MaxSize": 10}]}
        with patch.object(remediator, "autoscaling", mock_asg), patch.object(remediator, "notify"):
            result = remediator.scale_asg("my-asg")
        mock_asg.update_auto_scaling_group.assert_called_once_with(
            AutoScalingGroupName="my-asg", DesiredCapacity=4)
        assert result["status"] == "success"
        assert result["new_desired"] == 4

    def test_scale_asg_skips_at_max_size(self):
        mock_asg = MagicMock()
        mock_asg.describe_auto_scaling_groups.return_value = {
            "AutoScalingGroups": [{"DesiredCapacity": 10, "MaxSize": 10}]}
        with patch.object(remediator, "autoscaling", mock_asg), patch.object(remediator, "notify"):
            result = remediator.scale_asg("my-asg")
        mock_asg.update_auto_scaling_group.assert_not_called()
        assert result["status"] == "skipped"


# ─────────────────────────────────────────────────────────────────────────────
# OPS CONSOLE (MISSION CONTROL)
# ─────────────────────────────────────────────────────────────────────────────

class TestOpsConsole:

    def test_authed_requires_matching_key(self):
        assert not console.authed({"headers": {}})
        assert not console.authed({"headers": {"x-console-key": "wrong"}})
        assert console.authed({"headers": {"x-console-key": "test-console-key"}})

    def test_root_path_serves_html_without_auth(self):
        result = console.lambda_handler(
            {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/"}, {})
        assert result["statusCode"] == 200
        assert "AI Ops Console" in result["body"]

    def test_api_without_key_is_rejected(self):
        result = console.lambda_handler(
            {"requestContext": {"http": {"method": "GET"}}, "rawPath": "/api/incidents", "headers": {}}, {})
        assert result["statusCode"] == 401

    def test_get_pending_extracts_task_token(self):
        mock_sfn = MagicMock()
        mock_sfn.list_executions.return_value = {"executions": [
            {"executionArn": "arn:ex:1", "name": "exec-1", "startDate": "2026-07-09T10:00:00Z", "status": "RUNNING"}
        ]}
        payload = {"taskToken": "tok-abc", "analysis": {"alarm_name": "watch-x", "urgency": "HIGH"}}
        mock_sfn.get_execution_history.return_value = {"events": [
            {"type": "TaskScheduled", "taskScheduledEventDetails": {"parameters": json.dumps({"Payload": payload})}},
        ]}
        with patch.object(console, "sfn", mock_sfn):
            pending = console.get_pending()
        assert len(pending) == 1
        assert pending[0]["task_token"] == "tok-abc"

    def test_get_pending_ignores_ai_analysis_invoke(self):
        """The AI_Analysis Task invoke has no taskToken and must not be
        mistaken for the waitForTaskToken state."""
        mock_sfn = MagicMock()
        mock_sfn.list_executions.return_value = {"executions": [
            {"executionArn": "arn:ex:2", "name": "exec-2", "startDate": "2026-07-09T10:00:00Z", "status": "RUNNING"}
        ]}
        mock_sfn.get_execution_history.return_value = {"events": [
            {"type": "TaskScheduled", "taskScheduledEventDetails": {
                "parameters": json.dumps({"Payload": {"detail": {"alarmName": "x"}}})}},
        ]}
        with patch.object(console, "sfn", mock_sfn):
            assert console.get_pending() == []

    def test_decide_sends_task_success_with_approval(self):
        mock_sfn = MagicMock()
        with patch.object(console, "sfn", mock_sfn):
            result = console.decide({"taskToken": "tok-abc", "approved": True})
        kwargs = mock_sfn.send_task_success.call_args.kwargs
        assert kwargs["taskToken"] == "tok-abc"
        assert json.loads(kwargs["output"])["approved"] is True
        assert result["statusCode"] == 200

    def test_decide_without_token_is_400(self):
        result = console.decide({"approved": True})
        assert result["statusCode"] == 400

    def test_decide_expired_token_is_409_not_500(self):
        mock_sfn = MagicMock()
        mock_sfn.send_task_success.side_effect = Exception("TaskTimedOut")
        with patch.object(console, "sfn", mock_sfn):
            result = console.decide({"taskToken": "expired", "approved": True})
        assert result["statusCode"] == 409

    def test_ask_proxies_and_unwraps_runbook_response(self):
        mock_lam = MagicMock()
        inner = json.dumps({"answer": "Do X then Y", "sources": ["deploy-rollback.md"]})
        mock_lam.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps({"statusCode": 200, "body": inner}).encode())
        }
        with patch.object(console, "lam", mock_lam):
            result = console.ask({"question": "How do I roll back?"})
        assert result["statusCode"] == 200
        assert json.loads(result["body"])["answer"] == "Do X then Y"

    def test_ask_rejects_empty_or_too_long_question(self):
        assert console.ask({"question": ""})["statusCode"] == 400
        assert console.ask({"question": "x" * 2001})["statusCode"] == 400