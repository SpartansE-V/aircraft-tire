variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-southeast-1"
}

variable "project_name" {
  description = "Short name used to prefix/tag all resources."
  type        = string
  default     = "aircraft-tire"
}

variable "vpc_cidr" {
  description = "CIDR block for the service VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "azs" {
  description = "Availability zones to spread subnets across."
  type        = list(string)
  default     = ["ap-southeast-1a", "ap-southeast-1b"]
}

variable "container_port" {
  description = "Port the container listens on (matches app/main.py + Dockerfile)."
  type        = number
  default     = 8000
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Fargate task memory (MiB)."
  type        = number
  default     = 512
}

variable "desired_count" {
  description = "Number of Fargate tasks to run."
  type        = number
  default     = 2
}

variable "cors_origins" {
  description = "Value for the CORS_ORIGINS env var."
  type        = string
  default     = "http://localhost:3000"
}

variable "image_tag" {
  description = "Container image tag to deploy. CI overrides this per build (commit SHA)."
  type        = string
  default     = "latest"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role, as org/repo."
  type        = string
  default     = "SpartansE-V/aircraft-tire"
}
