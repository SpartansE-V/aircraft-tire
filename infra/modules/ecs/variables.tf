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

variable "launch_type" {
  description = "FARGATE or EC2. EC2 is required for GPU tasks - Fargate has no GPU support."
  type        = string
  default     = "FARGATE"

  validation {
    condition     = contains(["FARGATE", "EC2"], var.launch_type)
    error_message = "launch_type must be FARGATE or EC2."
  }
}

variable "capacity_provider_name" {
  description = "ECS capacity provider to use when launch_type = \"EC2\". Ignored for FARGATE."
  type        = string
  default     = null
}

variable "gpu_count" {
  description = "Number of GPUs to request via container resourceRequirements. 0 = no GPU requirement."
  type        = number
  default     = 0
}

variable "enable_autoscaling" {
  description = "Whether to create an Application Auto Scaling target/policy for this service."
  type        = bool
  default     = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
