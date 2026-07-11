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

variable "cors_origins" {
  description = "Value for the CORS_ORIGINS env var (app service only)."
  type        = string
  default     = "http://localhost:3000"
}

variable "image_tag_app" {
  description = "Image tag to deploy for the app service. CI overrides this per build (commit SHA)."
  type        = string
  default     = "latest"
}

variable "image_tag_reconstructor" {
  description = "Image tag to deploy for the 3d-reconstructor service. CI overrides this per build (commit SHA)."
  type        = string
  default     = "latest"
}

variable "image_tag_web" {
  description = "Image tag to deploy for the web (frontend) service. CI overrides this per build (commit SHA)."
  type        = string
  default     = "latest"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role, as org/repo."
  type        = string
  default     = "SpartansE-V/aircraft-tire"
}
