

output "analyser_role_arn" { value = aws_iam_role.analyser.arn }
output "runbook_role_arn" { value = aws_iam_role.runbook.arn }
output "cost_reporter_role_arn" { value = aws_iam_role.cost_reporter.arn }
output "remediator_role_arn" { value = aws_iam_role.remediator.arn }
output "step_functions_role_arn" { value = aws_iam_role.step_functions.arn }
output "eventbridge_sfn_role_arn" { value = aws_iam_role.eventbridge_sfn.arn }
output "github_actions_role_arn" { value = aws_iam_role.github_actions.arn }
