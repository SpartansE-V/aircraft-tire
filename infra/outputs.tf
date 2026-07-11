output "alb_dns_names" {
  description = "Public URL of each service's load balancer (HTTP)."
  value       = { for k, v in module.alb : k => "http://${v.dns_name}" }
}

output "ecr_repository_urls" {
  value = { for k, v in module.ecr : k => v.repository_url }
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_names" {
  value = { for k, v in module.ecs : k => v.service_name }
}

output "uploads_bucket_name" {
  value = module.uploads.bucket_name
}

output "github_actions_role_arn" {
  description = "Role ARN GitHub Actions assumes via OIDC. Set as the AWS_ROLE_ARN repo secret."
  value       = module.github_oidc.role_arn
}
