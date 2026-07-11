variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "cluster_id" {
  description = "Shared ECS cluster ID this service runs on."
  type        = string
}

variable "cluster_name" {
  description = "Shared ECS cluster name (used for the autoscaling target's resource_id)."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "alb_security_group_id" {
  type = string
}

variable "target_group_arn" {
  type = string
}

variable "ecr_repository_url" {
  type = string
}

variable "image_tag" {
  type = string
}

variable "container_port" {
  type = number
}

variable "task_cpu" {
  type = number
}

variable "task_memory" {
  type = number
}

variable "desired_count" {
  type = number
}

variable "environment" {
  description = "Container environment variables."
  type = list(object({
    name  = string
    value = string
  }))
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}
