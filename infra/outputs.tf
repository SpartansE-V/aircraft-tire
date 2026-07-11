output "alb_dns_name" {
  description = "Public URL of the load balancer (HTTP)."
  value       = "http://${module.alb.dns_name}"
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "ecs_service_name" {
  value = module.ecs.service_name
}

output "github_actions_role_arn" {
  description = "Role ARN GitHub Actions assumes via OIDC. Set as the AWS_ROLE_ARN repo secret."
  value       = module.github_oidc.role_arn
}
