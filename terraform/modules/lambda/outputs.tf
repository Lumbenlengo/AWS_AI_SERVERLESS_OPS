output "anomaly_analyser_arn" { value = aws_lambda_function.fn["anomaly_analyser"].arn }
output "runbook_assistant_arn" { value = aws_lambda_function.fn["runbook_assistant"].arn }
output "cost_reporter_arn" { value = aws_lambda_function.fn["cost_reporter"].arn }
output "remediator_arn" { value = aws_lambda_function.fn["remediator"].arn }
