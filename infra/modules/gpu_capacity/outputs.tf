output "capacity_provider_name" {
  value = aws_ecs_capacity_provider.gpu.name
}

output "security_group_id" {
  value = aws_security_group.instances.id
}
