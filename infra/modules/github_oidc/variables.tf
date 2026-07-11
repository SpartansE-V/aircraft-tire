variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "github_repo" {
  description = "GitHub repo allowed to assume this role, as org/repo."
  type        = string
}

variable "tfstate_bucket" {
  type = string
}

variable "tfstate_key_prefix" {
  type = string
}

variable "tfstate_lock_table" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
