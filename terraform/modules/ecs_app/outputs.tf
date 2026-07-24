output "cluster_name" { value = aws_ecs_cluster.demo.name }
output "service_name" { value = aws_ecs_service.app.name }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "watch_alarm_name" { value = aws_cloudwatch_metric_alarm.app_errors.alarm_name }
output "alb_dns_name" { value = aws_lb.app.dns_name }
output "alb_url" { value = "http://${aws_lb.app.dns_name}" }